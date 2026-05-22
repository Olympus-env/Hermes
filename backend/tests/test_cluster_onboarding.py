"""Tests du cluster onboarding→ARGOS (issues #2, #3, #5, #6).

Couvre : re-filtrage des AO existants, verrou d'onboarding + endpoint
d'initialisation, et exposition du score réel (None si non analysé) dans
l'API des appels d'offre.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes import onboarding
from hermes.agents.argos.filtre import FiltreVeille, enregistrer_filtre, refiltrer_existants
from hermes.db.models import AnalyseKrinos, AppelOffre, StatutAO
from hermes.db.session import get_engine


def _ao(session: Session, titre: str, statut: StatutAO = StatutAO.BRUT) -> int:
    ao = AppelOffre(
        url_source=f"https://example.test/{titre}",
        titre=titre,
        statut=statut,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    return ao.id


# --------------------------------------------------------------------------- #
# #6 — re-filtrage des AO existants
# --------------------------------------------------------------------------- #


def test_refiltrage_exclut_les_ao_hors_perimetre():
    with Session(get_engine()) as session:
        garde = _ao(session, "Maintenance applicative Java")
        sortant = _ao(session, "Nettoyage des locaux")

        bilan = refiltrer_existants(
            session, FiltreVeille(inclus=("java",), exclus=("nettoyage",))
        )

        assert bilan.exclus == 1
        assert bilan.conserves == 1
        assert session.get(AppelOffre, garde).statut == StatutAO.BRUT
        assert session.get(AppelOffre, sortant).statut == StatutAO.HORS_FILTRE


def test_refiltrage_reintegre_quand_filtre_redevient_compatible():
    with Session(get_engine()) as session:
        ao_id = _ao(session, "Audit cybersécurité", statut=StatutAO.HORS_FILTRE)

        bilan = refiltrer_existants(session, FiltreVeille(inclus=("cyber",)))

        assert bilan.reintegres == 1
        # Pas d'analyse → réintégré en BRUT pour repasser dans le pipeline.
        assert session.get(AppelOffre, ao_id).statut == StatutAO.BRUT


def test_refiltrage_reintegre_en_analyse_si_analyse_existante():
    with Session(get_engine()) as session:
        ao_id = _ao(session, "Audit cyber avec analyse", statut=StatutAO.HORS_FILTRE)
        session.add(
            AnalyseKrinos(
                appel_offre_id=ao_id,
                resume="r",
                score=42.0,
                justification_score="j",
            )
        )
        session.commit()

        refiltrer_existants(session, FiltreVeille(inclus=("cyber",)))
        assert session.get(AppelOffre, ao_id).statut == StatutAO.ANALYSE


def test_refiltrage_ne_touche_pas_les_statuts_engages():
    with Session(get_engine()) as session:
        ao_id = _ao(session, "Nettoyage déjà à répondre", statut=StatutAO.A_REPONDRE)

        refiltrer_existants(session, FiltreVeille(inclus=("java",), exclus=("nettoyage",)))
        # Décision humaine préservée malgré le mot-clé exclu.
        assert session.get(AppelOffre, ao_id).statut == StatutAO.A_REPONDRE


# --------------------------------------------------------------------------- #
# #3 — verrou onboarding + initialisation
# --------------------------------------------------------------------------- #


def test_initialiser_marque_onboarding_termine():
    from hermes.main import app

    with Session(get_engine()) as session:
        assert onboarding.est_termine(session) is False

    with TestClient(app) as client:
        r = client.post("/argos/initialiser")
        assert r.status_code == 200
        assert "refiltrage" in r.json()

    with Session(get_engine()) as session:
        assert onboarding.est_termine(session) is True


def test_put_filtre_refiltre_les_existants():
    from hermes.main import app

    with Session(get_engine()) as session:
        _ao(session, "Prestation de nettoyage")

    with TestClient(app) as client:
        r = client.put(
            "/argos/filtre", json={"inclus": ["java"], "exclus": ["nettoyage"]}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["refiltrage"]["exclus"] == 1

    with Session(get_engine()) as session:
        statuts = session.exec(select(AppelOffre.statut)).all()
        assert StatutAO.HORS_FILTRE in statuts


# --------------------------------------------------------------------------- #
# Migration : backfill du verrou onboarding (install antérieure à 1.0.1)
# --------------------------------------------------------------------------- #


def test_backfill_neutre_sur_install_vierge():
    with Session(get_engine()) as session:
        assert onboarding.backfill_si_deja_utilise(session) is False
        assert onboarding.est_termine(session) is False


def test_backfill_active_si_filtre_deja_enregistre():
    with Session(get_engine()) as session:
        enregistrer_filtre(session, FiltreVeille(inclus=("java",)))
        assert onboarding.backfill_si_deja_utilise(session) is True
        assert onboarding.est_termine(session) is True


def test_backfill_active_si_des_ao_existent():
    with Session(get_engine()) as session:
        _ao(session, "AO préexistant")
        assert onboarding.backfill_si_deja_utilise(session) is True
        assert onboarding.est_termine(session) is True


# --------------------------------------------------------------------------- #
# #2 — score réel exposé (None si non analysé), hors_filtre masqué
# --------------------------------------------------------------------------- #


def test_liste_expose_score_reel_et_non_analyse():
    from hermes.main import app

    with Session(get_engine()) as session:
        analyse_id = _ao(session, "AO analysé", statut=StatutAO.ANALYSE)
        _ao(session, "AO jamais analysé")
        session.add(
            AnalyseKrinos(
                appel_offre_id=analyse_id,
                resume="r",
                score=63.5,
                justification_score="j",
            )
        )
        session.commit()

    with TestClient(app) as client:
        items = client.get("/appels-offre").json()["items"]
        par_titre = {i["titre"]: i for i in items}

        assert par_titre["AO analysé"]["score"] == 63.5
        assert par_titre["AO analysé"]["analyse_disponible"] is True
        # Jamais analysé : score None, pas 0 (issue #2).
        assert par_titre["AO jamais analysé"]["score"] is None
        assert par_titre["AO jamais analysé"]["analyse_disponible"] is False


def test_liste_masque_les_hors_filtre_par_defaut():
    from hermes.main import app

    with Session(get_engine()) as session:
        _ao(session, "AO visible")
        _ao(session, "AO écarté", statut=StatutAO.HORS_FILTRE)

    with TestClient(app) as client:
        defaut = client.get("/appels-offre").json()
        assert defaut["total"] == 1
        assert defaut["items"][0]["titre"] == "AO visible"

        # Accessible explicitement pour audit.
        explicite = client.get("/appels-offre?statut=hors_filtre").json()
        assert explicite["total"] == 1

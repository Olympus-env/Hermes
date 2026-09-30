"""Tests de GET /tableau-de-bord (agrégats de l'Accueil)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    LogAgent,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)
from hermes.db.session import get_engine


def _ao(session: Session, n: int, statut: StatutAO, jours: float | None = None) -> AppelOffre:
    limite = datetime.now(UTC) + timedelta(days=jours) if jours is not None else None
    ao = AppelOffre(
        url_source=f"https://example.test/ao/{n}",
        reference_externe=f"REF-{n}",
        titre=f"AO {n}",
        statut=statut,
        date_limite=limite,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    return ao


def test_base_vide_renvoie_des_zeros():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/tableau-de-bord")
    assert r.status_code == 200
    d = r.json()
    assert (d["total_ao"], d["urgents"], d["score_eleve"], d["a_repondre"]) == (0, 0, 0, 0)
    assert d["par_statut"]["brut"] == 0 and len(d["par_statut"]) == len(StatutAO)
    assert d["reponses"]["en_attente"] == 0
    assert d["activite"] == []
    assert d["genere_le"].endswith("+00:00")


def test_compteurs_pipeline_et_reponses():
    from hermes.main import app

    with Session(get_engine()) as s:
        a = _ao(s, 1, StatutAO.ANALYSE, jours=3)  # urgent, score élevé
        b = _ao(s, 2, StatutAO.A_REPONDRE, jours=30)
        _ao(s, 3, StatutAO.BRUT, jours=-2)  # échéance passée : pas urgent
        _ao(s, 4, StatutAO.REJETE, jours=2)  # inactif : pas urgent
        _ao(s, 5, StatutAO.HORS_FILTRE)  # exclu du total
        s.add_all(
            [
                AnalyseKrinos(appel_offre_id=a.id, resume="r", score=40, justification_score="j"),
                AnalyseKrinos(
                    appel_offre_id=a.id,
                    resume="r",
                    score=82,
                    justification_score="j",
                    cree_le=datetime.now(UTC) + timedelta(seconds=5),
                ),
                AnalyseKrinos(appel_offre_id=b.id, resume="r", score=69, justification_score="j"),
                # v1 rejetée puis v2 en attente : seule la dernière compte.
                ReponseHermion(
                    appel_offre_id=a.id, version=1, contenu="x", statut=StatutReponse.REJETEE
                ),
                ReponseHermion(
                    appel_offre_id=a.id, version=2, contenu="x", statut=StatutReponse.EN_ATTENTE
                ),
                ReponseHermion(
                    appel_offre_id=b.id, version=1, contenu="x", statut=StatutReponse.VALIDEE
                ),
            ]
        )
        s.commit()

    with TestClient(app) as client:
        d = client.get("/tableau-de-bord").json()
    assert d["total_ao"] == 4
    assert d["urgents"] == 1
    assert d["score_eleve"] == 1  # 82 (dernière analyse) ; 69 < 70
    assert d["a_repondre"] == 1
    assert d["par_statut"]["hors_filtre"] == 1 and d["par_statut"]["rejete"] == 1
    assert d["reponses"]["en_attente"] == 1
    assert d["reponses"]["validee"] == 1
    assert d["reponses"]["rejetee"] == 0


def test_activite_agents_ordre_inverse_et_filtre():
    from hermes.main import app

    base = datetime.now(UTC)
    with Session(get_engine()) as s:
        s.add_all(
            [
                LogAgent(agent="ARGOS", message="a1", cree_le=base),
                LogAgent(agent="HERMES", message="démarrage", cree_le=base + timedelta(seconds=1)),
                LogAgent(agent="KRINOS", message="k1", cree_le=base + timedelta(seconds=2)),
                LogAgent(agent="HERMION", message="h1", cree_le=base + timedelta(seconds=3)),
            ]
        )
        s.commit()

    with TestClient(app) as client:
        d = client.get("/tableau-de-bord?limite_activite=2").json()
        assert [x["message"] for x in d["activite"]] == ["h1", "k1"]
        tous = client.get("/tableau-de-bord").json()["activite"]
        assert [x["agent"] for x in tous] == ["HERMION", "KRINOS", "ARGOS"]
        assert client.get("/tableau-de-bord?limite_activite=0").status_code == 422


def test_beaucoup_d_ao_actifs_et_sans_echeance():
    """Plus de 32 000 ids ne doivent pas casser la requête ; sans date_limite = non urgent."""
    from hermes.main import app

    with Session(get_engine()) as s:
        s.add_all(
            AppelOffre(url_source=f"https://example.test/{i}", reference_externe=f"B{i}",
                       titre=f"AO {i}", statut=StatutAO.ANALYSE)
            for i in range(33_000)
        )
        s.commit()
        ao = _ao(s, 999_999, StatutAO.BRUT)  # sans échéance
        s.add(AnalyseKrinos(appel_offre_id=ao.id, resume="r", score=90, justification_score="j"))
        s.commit()

    with TestClient(app) as client:
        d = client.get("/tableau-de-bord").json()
    assert d["total_ao"] == 33_001
    assert d["urgents"] == 0
    assert d["score_eleve"] == 1

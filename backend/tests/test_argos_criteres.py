"""Tests des critères de filtrage avancés (Boucle 2) : query builders,
mapping nature, garde-fou client dates, persistance rétro-compatible."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session

from hermes.agents.argos.base import AOCollecte, CriteresAvances
from hermes.agents.argos.boamp import _construire_where
from hermes.agents.argos.filtre import (
    FiltreVeille,
    charger_criteres,
    charger_filtre,
    enregistrer_criteres,
    enregistrer_filtre,
)
from hermes.agents.argos.ted import _construire_query
from hermes.db.session import get_engine, init_db

# --------------------------------------------------------------------------- #
# Modèle CriteresAvances
# --------------------------------------------------------------------------- #


def test_actif_detecte_chaque_critere():
    assert CriteresAvances().actif is False
    assert CriteresAvances(cpv=("64200000",)).actif is True
    assert CriteresAvances(departements=("75",)).actif is True
    assert CriteresAvances(date_publication_depuis="2026-06-01").actif is True


def test_natures_pour_mappe_par_portail():
    c = CriteresAvances(natures=("services", "travaux", "fournitures"))
    assert c.natures_pour("boamp") == ("SERVICES", "TRAVAUX", "FOURNITURES")
    assert c.natures_pour("ted") == ("services", "works", "supplies")


def test_natures_pour_ignore_valeur_inconnue():
    c = CriteresAvances(natures=("services", "bidon"))
    assert c.natures_pour("ted") == ("services",)


# --------------------------------------------------------------------------- #
# Garde-fou client sur les dates
# --------------------------------------------------------------------------- #


def _ao_dates(pub=None, fin=None) -> AOCollecte:
    return AOCollecte(
        titre="AO",
        url_source="https://example.test/x",
        date_publication=pub,
        date_limite=fin,
    )


def test_correspond_client_publication_hors_borne():
    c = CriteresAvances(date_publication_depuis="2026-06-01")
    avant = _ao_dates(pub=datetime(2026, 5, 1, tzinfo=UTC))
    apres = _ao_dates(pub=datetime(2026, 6, 15, tzinfo=UTC))
    assert c.correspond_client(avant) is False
    assert c.correspond_client(apres) is True


def test_correspond_client_deadline_bornes():
    c = CriteresAvances(deadline_min="2026-07-01", deadline_max="2026-07-31")
    trop_tot = _ao_dates(fin=datetime(2026, 6, 20, tzinfo=UTC))
    ok = _ao_dates(fin=datetime(2026, 7, 15, tzinfo=UTC))
    trop_tard = _ao_dates(fin=datetime(2026, 8, 10, tzinfo=UTC))
    assert c.correspond_client(trop_tot) is False
    assert c.correspond_client(ok) is True
    assert c.correspond_client(trop_tard) is False


def test_correspond_client_sans_date_ne_rejette_pas():
    """Un AO sans date n'est jamais écarté par le garde-fou client."""
    c = CriteresAvances(date_publication_depuis="2026-06-01", deadline_min="2026-07-01")
    assert c.correspond_client(_ao_dates()) is True


# --------------------------------------------------------------------------- #
# Query builder BOAMP (ODSQL)
# --------------------------------------------------------------------------- #


def test_where_descripteurs_et_departements():
    c = CriteresAvances(descripteurs=("informatique",), departements=("75", "92"))
    where = _construire_where((), (), c)
    assert where == (
        '(search(descripteur_libelle, "informatique")) AND '
        '(code_departement = "75" OR code_departement = "92")'
    )


def test_where_nature_et_dates():
    c = CriteresAvances(
        natures=("services",),
        date_publication_depuis="2026-06-01",
        deadline_min="2026-07-01",
        deadline_max="2026-07-31",
    )
    where = _construire_where((), (), c)
    assert where == (
        '(type_marche = "SERVICES") AND '
        "dateparution >= date'2026-06-01' AND "
        "datelimitereponse >= date'2026-07-01' AND "
        "datelimitereponse <= date'2026-07-31'"
    )


def test_where_combine_motscles_criteres_et_exclus():
    c = CriteresAvances(departements=("75",))
    where = _construire_where(("SMS",), ("nettoyage",), c)
    assert where == (
        '(search(objet, "SMS")) AND (code_departement = "75") '
        'AND NOT (search(objet, "nettoyage"))'
    )


def test_where_sans_clause_positive_reste_none():
    # Aucun mot-clé ni critère positif (exclus seul) → None (derniers avis).
    assert _construire_where((), ("nettoyage",), CriteresAvances()) is None


# --------------------------------------------------------------------------- #
# Query builder TED (eForms)
# --------------------------------------------------------------------------- #


def test_query_cpv_nature_dates():
    c = CriteresAvances(
        cpv=("64200000",),
        natures=("services",),
        date_publication_depuis="2026-06-01",
        deadline_min="2026-07-01",
    )
    query = _construire_query(("sms",), c)
    assert query == (
        'place-of-performance IN (FRA) AND (notice-title ~ "sms") AND '
        "classification-cpv IN (64200000) AND contract-nature IN (services) AND "
        "publication-date >= 20260601 AND "
        "deadline-receipt-tender-date-lot >= 20260701 "
        "SORT BY publication-date DESC"
    )


def test_query_pays_configurable():
    c = CriteresAvances(pays=("FRA", "ESP"))
    query = _construire_query((), c)
    assert query == "place-of-performance IN (FRA, ESP) SORT BY publication-date DESC"


def test_query_defaut_france_sans_criteres():
    assert _construire_query(()) == (
        "place-of-performance IN (FRA) SORT BY publication-date DESC"
    )


# --------------------------------------------------------------------------- #
# Persistance rétro-compatible
# --------------------------------------------------------------------------- #


def test_persistance_criteres_round_trip():
    init_db()
    with Session(get_engine()) as session:
        enregistrer_criteres(
            session,
            CriteresAvances(
                cpv=("64200000",),
                natures=("services",),
                departements=("75",),
                date_publication_depuis="2026-06-01",
            ),
        )
    with Session(get_engine()) as session:
        relu = charger_criteres(session)
    assert relu.cpv == ("64200000",)
    assert relu.natures == ("services",)
    assert relu.departements == ("75",)
    assert relu.date_publication_depuis == "2026-06-01"


def test_criteres_et_motscles_coexistent_sans_ecrasement():
    """Écrire l'un ne doit pas effacer l'autre (même paramètre JSON)."""
    init_db()
    with Session(get_engine()) as session:
        enregistrer_filtre(session, FiltreVeille(inclus=("java",)))
        enregistrer_criteres(session, CriteresAvances(departements=("75",)))
    with Session(get_engine()) as session:
        # Réécrire les mots-clés ne doit pas perdre les critères avancés.
        enregistrer_filtre(session, FiltreVeille(inclus=("python",)))
    with Session(get_engine()) as session:
        assert charger_filtre(session).inclus == ("python",)
        assert charger_criteres(session).departements == ("75",)


def test_normalisation_criteres():
    init_db()
    with Session(get_engine()) as session:
        nettoye = enregistrer_criteres(
            session,
            CriteresAvances(
                cpv=("64200000", "abc"),  # 'abc' non numérique → écarté
                natures=("Services", "bidon"),  # casse normalisée, 'bidon' écarté
                pays=("fra",),  # → majuscules
                date_publication_depuis="2026-13-99",  # date invalide → None
            ),
        )
    assert nettoye.cpv == ("64200000",)
    assert nettoye.natures == ("services",)
    assert nettoye.pays == ("FRA",)
    assert nettoye.date_publication_depuis is None


def test_endpoint_put_get_criteres_avances():
    from fastapi.testclient import TestClient

    from hermes.main import app

    init_db()
    with TestClient(app) as client:
        r = client.put(
            "/argos/filtre",
            json={
                "inclus": ["sms"],
                "exclus": [],
                "avance": {
                    "cpv": ["64200000"],
                    "natures": ["services"],
                    "departements": ["75"],
                    "date_publication_depuis": "2026-06-01",
                },
            },
        )
        assert r.status_code == 200
        assert r.json()["avance"]["cpv"] == ["64200000"]
        assert r.json()["actif"] is True

        r = client.get("/argos/filtre")
        assert r.json()["avance"]["natures"] == ["services"]
        assert r.json()["avance"]["departements"] == ["75"]

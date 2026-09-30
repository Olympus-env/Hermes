"""Profil métier structuré : API, composition du texte, absence de données sensibles."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.agents.argos.filtre import FiltreVeille, enregistrer_filtre
from hermes.agents.krinos import analyzer, jev
from hermes.agents.profil_metier import (
    LONGUEUR_MAX_TEXTE,
    ProfilMetier,
    composer_texte,
    enregistrer_profil,
)
from hermes.db.session import get_engine, init_db


def _client():
    from hermes.main import app

    init_db()
    return TestClient(app)


def test_api_aller_retour():
    with _client() as c:
        corps = {
            "activite": "ESN Java",
            "secteurs": ["numérique"],
            "codes_cpv": ["72000000-5"],
            "zone_geographique": "Île-de-France",
            "effectif": 25,
            "ca_tranche": "1-5 M€",
            "certifications": ["ISO 27001"],
            "types_marches": ["services"],
            "references_types": ["Refonte SI mairie"],
        }
        r = c.put("/profil/metier", json=corps)
        assert r.status_code == 200
        assert c.get("/profil/metier").json() == corps


def test_api_refuse_donnees_sensibles():
    with _client() as c:
        assert c.put("/profil/metier", json={"nom": "Dupont"}).status_code == 422
        assert c.put("/profil/metier", json={"activite": "a@b.fr"}).status_code == 422
        r = c.put("/profil/metier", json={"references_types": ["SIRET 123 456 789 00012"]})
        assert r.status_code == 422
        assert c.put("/profil/metier", json={"codes_cpv": ["abc"]}).status_code == 422


def test_texte_borne():
    profil = ProfilMetier(
        activite="x" * 400,
        references_types=["r" * 190 for _ in range(15)],
    )
    assert len(composer_texte(profil, ["java"])) <= LONGUEUR_MAX_TEXTE


def test_profil_metier_analyzer_combine_profil_et_mots_cles():
    init_db()
    with Session(get_engine()) as s:
        enregistrer_filtre(s, FiltreVeille(inclus=("maintenance",)))
        enregistrer_profil(s, ProfilMetier(activite="ESN Java", effectif=12))
        texte = analyzer._profil_metier(s)
    assert "ESN Java" in texte and "12 personnes" in texte and "maintenance" in texte
    assert len(texte) <= LONGUEUR_MAX_TEXTE


def test_state_jev_conserve_profil_long_sans_identite():
    profil = composer_texte(ProfilMetier(activite="a" * 400, secteurs=["b" * 190] * 5))
    state = jev.construire_state(
        titre="t",
        objet="o",
        acheteur="a",
        type_marche="",
        budget="",
        date_limite="",
        profil_metier=profil,
        extrait_documents="",
    )
    assert state["profil_metier"] == profil
    assert "@" not in str(state)

"""Tests filtre ARGOS — mots-clés inclus/exclus."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes.agents import pythia
from hermes.agents.argos.base import AOCollecte
from hermes.agents.argos.filtre import (
    FiltreVeille,
    charger_filtre,
    enregistrer_filtre,
)
from hermes.db.models import AppelOffre, Parametre
from hermes.db.session import get_engine, init_db


def _ao(titre="", objet=None, emetteur=None) -> AOCollecte:
    return AOCollecte(
        titre=titre,
        url_source=f"https://example.test/{titre.replace(' ', '_')}",
        objet=objet,
        emetteur=emetteur,
    )


def test_filtre_vide_est_inactif():
    filtre = FiltreVeille()
    assert filtre.actif is False
    assert filtre.correspond(_ao(titre="N'importe quoi")) is True


def test_filtre_inclus_match_titre_insensible_casse_et_accents():
    filtre = FiltreVeille(inclus=("Maintenance",))
    assert filtre.correspond(_ao(titre="MAINTENANCE applicative")) is True
    assert filtre.correspond(_ao(titre="Maïntenance pour test")) is True
    assert filtre.correspond(_ao(titre="Nettoyage des locaux")) is False


def test_filtre_inclus_match_objet_et_emetteur():
    filtre = FiltreVeille(inclus=("java",))
    assert filtre.correspond(_ao(titre="AO", objet="Maintenance Java")) is True
    assert filtre.correspond(_ao(titre="AO", emetteur="Java Corp")) is True
    assert filtre.correspond(_ao(titre="AO", objet="Python")) is False


def test_filtre_exclus_prioritaire_sur_inclus():
    filtre = FiltreVeille(inclus=("maintenance",), exclus=("nettoyage",))
    assert filtre.correspond(_ao(titre="Maintenance des espaces verts et nettoyage")) is False
    assert filtre.correspond(_ao(titre="Maintenance applicative")) is True


def test_filtre_exclus_seul_garde_tout_sauf_exclus():
    filtre = FiltreVeille(exclus=("nettoyage",))
    assert filtre.actif is True
    assert filtre.correspond(_ao(titre="Marche de prestations IT")) is True
    assert filtre.correspond(_ao(titre="Nettoyage")) is False


def test_enregistrer_et_charger_filtre():
    init_db()
    with Session(get_engine()) as session:
        nettoye = enregistrer_filtre(
            session,
            FiltreVeille(inclus=("Java", "Java ", "  java  "), exclus=("Nettoyage",)),
        )
        # Dédoublonnage insensible casse/espaces
        assert nettoye.inclus == ("Java",)
        assert nettoye.exclus == ("Nettoyage",)

    with Session(get_engine()) as session:
        relu = charger_filtre(session)
        assert relu.inclus == ("Java",)
        assert relu.exclus == ("Nettoyage",)


def test_charger_filtre_vide_si_absent():
    init_db()
    with Session(get_engine()) as session:
        filtre = charger_filtre(session)
    assert filtre.actif is False


def test_charger_filtre_tolere_json_corrompu():
    init_db()
    with Session(get_engine()) as session:
        session.add(
            Parametre(
                cle="argos.filtre.mots_cles",
                valeur="ceci n'est pas du JSON",
            )
        )
        session.commit()
        filtre = charger_filtre(session)
    assert filtre.actif is False


def test_endpoint_get_put_filtre():
    from hermes.main import app

    init_db()
    with TestClient(app) as client:
        # GET initial : vide
        r = client.get("/argos/filtre")
        assert r.status_code == 200
        data = r.json()
        assert data == {"inclus": [], "exclus": [], "actif": False}

        # PUT : enregistre
        r = client.put(
            "/argos/filtre",
            json={"inclus": ["Java", "PostgreSQL"], "exclus": ["nettoyage"]},
        )
        assert r.status_code == 200
        assert r.json()["inclus"] == ["Java", "PostgreSQL"]
        assert r.json()["exclus"] == ["nettoyage"]
        assert r.json()["actif"] is True

        # GET re-lit
        r = client.get("/argos/filtre")
        assert r.status_code == 200
        assert r.json()["inclus"] == ["Java", "PostgreSQL"]


def test_runner_applique_filtre(monkeypatch):
    """Le runner doit rejeter les AO ne matchant pas le filtre actif."""
    from hermes.agents.argos import runner
    from hermes.agents.argos.base import Scraper

    class FauxScraper(Scraper):
        nom = "faux-filtre"
        url_base = "https://example.test"

        async def collecter(self, limite: int = 20) -> list[AOCollecte]:
            return [
                _ao(titre="Maintenance applicative Java"),
                _ao(titre="Nettoyage des espaces verts"),
                _ao(titre="Audit cyber"),
            ]

    init_db()
    with Session(get_engine()) as session:
        enregistrer_filtre(
            session,
            FiltreVeille(inclus=("java", "cyber"), exclus=("nettoyage",)),
        )

    import asyncio

    with Session(get_engine()) as session:
        resultat = asyncio.run(runner.executer_collecte(FauxScraper(), session))

    assert resultat.ao_trouves == 3
    assert resultat.ao_nouveaux == 2  # Java + cyber
    assert resultat.ao_filtres == 1  # nettoyage rejeté

    with Session(get_engine()) as session:
        titres = sorted(
            t for t in session.exec(select(AppelOffre.titre)).all()
        )
    assert titres == ["Audit cyber", "Maintenance applicative Java"]


def test_runner_sans_filtre_garde_tout(monkeypatch):
    from hermes.agents.argos import runner
    from hermes.agents.argos.base import Scraper

    class FauxScraper(Scraper):
        nom = "faux-sans-filtre"
        url_base = "https://example.test"

        async def collecter(self, limite: int = 20) -> list[AOCollecte]:
            return [
                _ao(titre="AO 1"),
                _ao(titre="AO 2"),
            ]

    init_db()
    import asyncio

    with Session(get_engine()) as session:
        resultat = asyncio.run(runner.executer_collecte(FauxScraper(), session))

    assert resultat.ao_nouveaux == 2
    assert resultat.ao_filtres == 0


@pytest.mark.parametrize(
    "titre,attendu",
    [
        ("Marché de TÉLÉMÉDECINE", True),
        ("Telemedecine en ehpad", True),
        ("Travaux de toiture", False),
    ],
)
def test_filtre_normalisation_accents(titre, attendu):
    filtre = FiltreVeille(inclus=("telemedecine",))
    assert filtre.correspond(_ao(titre=titre)) is attendu


# --------------------------------------------------------------------------- #
# Suggestion mots-clés via PYTHIA
# --------------------------------------------------------------------------- #


def _faux_reponse_pythia(payload: dict):
    return pythia.ReponsePythia(
        texte=__import__("json").dumps(payload, ensure_ascii=False),
        modele="mistral:7b-instruct-q4_K_M",
        duree_ms=10,
    )


def test_suggerer_renvoie_mots_cles_normalises(monkeypatch):
    from hermes.agents.argos import filtre as mod

    async def fake_generer(prompt, *, system=None, format_json=False, **_):
        assert format_json is True
        assert "ACME" in prompt
        return _faux_reponse_pythia(
            {
                "inclus": ["maintenance applicative", "Java", "java", "  AMO  "],
                "exclus": ["Nettoyage", "espaces verts"],
                "raisonnement": "ESN logicielle Java/AMO — exclus = marchés physiques.",
            }
        )

    monkeypatch.setattr(mod.pythia, "generer", fake_generer)

    import asyncio

    suggestion = asyncio.run(
        mod.suggerer_mots_cles(entreprise="ACME", activite="ESN Java", infos="")
    )
    # Déduplication insensible casse + trim
    assert suggestion.inclus == ("maintenance applicative", "Java", "AMO")
    assert suggestion.exclus == ("Nettoyage", "espaces verts")
    assert "ESN" in suggestion.raisonnement


def test_suggerer_refuse_profil_vide():
    import asyncio

    from hermes.agents.argos import filtre as mod

    with pytest.raises(pythia.ErreurPythia):
        asyncio.run(mod.suggerer_mots_cles(entreprise="", activite=""))


def test_suggerer_rejette_sortie_sans_inclus(monkeypatch):
    from hermes.agents.argos import filtre as mod

    async def fake_generer(*args, **kwargs):
        return _faux_reponse_pythia({"inclus": [], "exclus": ["x"], "raisonnement": "rien"})

    monkeypatch.setattr(mod.pythia, "generer", fake_generer)

    import asyncio

    with pytest.raises(pythia.ErreurPythia):
        asyncio.run(mod.suggerer_mots_cles(entreprise="X", activite="Y"))


def test_endpoint_suggerer_renvoie_200(monkeypatch):
    from hermes.agents.argos import filtre as mod
    from hermes.main import app

    async def fake_generer(*args, **kwargs):
        return _faux_reponse_pythia(
            {
                "inclus": ["maintenance", "java"],
                "exclus": ["nettoyage"],
                "raisonnement": "ok",
            }
        )

    monkeypatch.setattr(mod.pythia, "generer", fake_generer)

    init_db()
    with TestClient(app) as client:
        r = client.post(
            "/argos/filtre/suggerer",
            json={"entreprise": "ACME", "activite": "ESN Java", "infos": ""},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["inclus"] == ["maintenance", "java"]
    assert data["exclus"] == ["nettoyage"]
    assert data["raisonnement"] == "ok"


def test_endpoint_suggerer_502_si_pythia_down(monkeypatch):
    from hermes.agents.argos import filtre as mod
    from hermes.main import app

    async def fake_generer(*args, **kwargs):
        raise pythia.ErreurPythia("connexion refusée")

    monkeypatch.setattr(mod.pythia, "generer", fake_generer)

    init_db()
    with TestClient(app) as client:
        r = client.post(
            "/argos/filtre/suggerer",
            json={"entreprise": "ACME", "activite": "ESN", "infos": ""},
        )
    assert r.status_code == 502

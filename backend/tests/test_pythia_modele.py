"""Tests des routes /pythia/modele/* (status + téléchargement)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from hermes.agents import pythia
from hermes.db.session import init_db


@pytest.fixture(autouse=True)
def _reset_etat():
    """Remet à zéro l'état partagé de téléchargement entre tests."""
    from hermes.api import pythia as api_pythia

    api_pythia._etat = api_pythia.EtatTelechargement()
    yield


def test_status_modele_installe(monkeypatch):
    from hermes.main import app

    async def fake_disponible(*args, **kwargs):
        return True

    async def fake_installe(nom=None):
        return True

    monkeypatch.setattr(pythia, "est_disponible", fake_disponible)
    monkeypatch.setattr(pythia, "modele_installe", fake_installe)

    init_db()
    with TestClient(app) as client:
        r = client.get("/pythia/modele/status")

    assert r.status_code == 200
    data = r.json()
    assert data["installe"] is True
    assert data["ollama_disponible"] is True
    assert data["progression"]["en_cours"] is False


def test_status_modele_absent_ollama_off(monkeypatch):
    from hermes.main import app

    async def fake_disponible(*args, **kwargs):
        return False

    monkeypatch.setattr(pythia, "est_disponible", fake_disponible)

    init_db()
    with TestClient(app) as client:
        r = client.get("/pythia/modele/status")

    assert r.status_code == 200
    data = r.json()
    assert data["ollama_disponible"] is False
    assert data["installe"] is False


def test_telecharger_refuse_si_ollama_down(monkeypatch):
    from hermes.main import app

    async def fake_disponible(*args, **kwargs):
        return False

    monkeypatch.setattr(pythia, "est_disponible", fake_disponible)

    init_db()
    with TestClient(app) as client:
        r = client.post("/pythia/modele/telecharger")

    assert r.status_code == 502


def test_telecharger_demarre_et_suit_progression(monkeypatch):
    from hermes.api import pythia as api_pythia
    from hermes.main import app

    async def fake_disponible(*args, **kwargs):
        return True

    async def fake_telechargement(modele):
        # Simule un stream avec 3 événements
        yield {"status": "pulling manifest"}
        yield {"status": "downloading", "completed": 500_000_000, "total": 4_000_000_000}
        yield {"status": "downloading", "completed": 4_000_000_000, "total": 4_000_000_000}

    monkeypatch.setattr(pythia, "est_disponible", fake_disponible)
    monkeypatch.setattr(pythia, "telecharger_modele", fake_telechargement)

    init_db()
    with TestClient(app) as client:
        r = client.post("/pythia/modele/telecharger")
        assert r.status_code == 200
        # Le téléchargement tourne en background — on attend qu'il finisse
        # en pollant l'état.
        for _ in range(20):
            r = client.get("/pythia/modele/status")
            if not r.json()["progression"]["en_cours"]:
                break
            import time

            time.sleep(0.05)

    etat = api_pythia.etat_global()
    assert etat.statut == "success"
    assert etat.octets_telecharges == 4_000_000_000
    assert etat.octets_total == 4_000_000_000
    assert etat.erreur is None


def test_telecharger_idempotent(monkeypatch):
    """Un deuxième POST pendant qu'un téléchargement est en cours ne le double pas."""
    from hermes.main import app

    async def fake_disponible(*args, **kwargs):
        return True

    barriere = asyncio.Event()
    appels = {"n": 0}

    async def fake_telechargement(modele):
        appels["n"] += 1
        yield {"status": "downloading", "completed": 0, "total": 1000}
        # Bloque jusqu'à ce que le test libère la barrière
        await barriere.wait()
        yield {"status": "downloading", "completed": 1000, "total": 1000}

    monkeypatch.setattr(pythia, "est_disponible", fake_disponible)
    monkeypatch.setattr(pythia, "telecharger_modele", fake_telechargement)

    init_db()
    with TestClient(app) as client:
        r1 = client.post("/pythia/modele/telecharger")
        assert r1.status_code == 200
        # Deuxième POST — doit renvoyer l'état en cours sans démarrer un 2e job
        r2 = client.post("/pythia/modele/telecharger")
        assert r2.status_code == 200

        # Débloque le faux téléchargement
        barriere.set()

    # Le nombre d'invocations doit être exactement 1.
    assert appels["n"] == 1


def test_progression_pourcent_calcule():
    from hermes.api import pythia as api_pythia

    etat = api_pythia.EtatTelechargement(
        octets_telecharges=2_000_000_000,
        octets_total=4_000_000_000,
    )
    p = api_pythia._progression_read(etat)
    assert p.pourcent == 50.0


def test_modele_installe_exige_tag_exact(monkeypatch):
    async def fake_lister():
        return ["qwen3:4b", "nomic-embed-text:latest"]

    monkeypatch.setattr(pythia, "lister_modeles", fake_lister)

    assert asyncio.run(pythia.modele_installe("qwen3:8b")) is False
    assert asyncio.run(pythia.modele_installe("qwen3:4b")) is True


def test_modele_installe_accepte_latest_sans_suffixe(monkeypatch):
    async def fake_lister():
        return ["mistral"]

    monkeypatch.setattr(pythia, "lister_modeles", fake_lister)

    assert asyncio.run(pythia.modele_installe("mistral:latest")) is True


def test_telechargement_ndjson_error_passe_en_erreur(monkeypatch):
    from hermes.api import pythia as api_pythia
    from hermes.main import app

    async def fake_disponible(*args, **kwargs):
        return True

    async def fake_telechargement(modele):
        yield {"status": "pulling manifest"}
        yield {"error": "modele introuvable"}

    monkeypatch.setattr(pythia, "est_disponible", fake_disponible)
    monkeypatch.setattr(pythia, "telecharger_modele", fake_telechargement)

    init_db()
    with TestClient(app) as client:
        r = client.post("/pythia/modele/telecharger")
        assert r.status_code == 200
        for _ in range(20):
            r = client.get("/pythia/modele/status")
            if not r.json()["progression"]["en_cours"]:
                break
            import time

            time.sleep(0.05)

    etat = api_pythia.etat_global()
    assert etat.statut == "erreur"
    assert etat.erreur == "modele introuvable"

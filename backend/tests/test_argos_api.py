"""Tests d'intégration HTTP pour les endpoints ARGOS."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_endpoint_scrapers_liste():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/argos/scrapers")
        assert r.status_code == 200
        assert "boamp" in r.json()["disponibles"]


def test_endpoint_portails_initialement_vide():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/argos/portails")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


def test_endpoint_collecter_portail_inconnu():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.post("/argos/collecter/nexistepas")
        assert r.status_code == 404


def test_endpoint_collecter_tous(monkeypatch):
    from hermes.agents.argos.base import AOCollecte, ResultatCollecte
    from hermes.main import app

    async def fake_collecte(scraper, session, *, limite=20):
        return ResultatCollecte(
            portail=scraper.nom,
            items=[AOCollecte(titre="AO test", url_source="https://example.test/ao")],
            ao_trouves=1,
            ao_nouveaux=1,
            ao_dedoublonnes=0,
            duree_ms=12,
        )

    monkeypatch.setattr("hermes.api.argos.executer_collecte", fake_collecte)

    with TestClient(app) as client:
        r = client.post("/argos/collecter")
        assert r.status_code == 200
        data = r.json()
        assert data["succes"] is True
        assert data["ao_trouves"] == 1
        assert data["ao_nouveaux"] == 1
        assert data["resultats"][0]["portail"] == "boamp"


def test_endpoint_scheduler_etat():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/argos/scheduler")
        assert r.status_code == 200
        data = r.json()
        assert "en_marche" in data
        assert "jobs" in data


def test_endpoint_portail_credentials_ne_renvoie_pas_secret():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.put(
            "/argos/portails/portail-prive",
            json={
                "url_base": "https://prive.example.test",
                "type": "prive",
                "actif": True,
                "frequence_minutes": 60,
            },
        )
        assert r.status_code == 200
        assert r.json()["credentials_configures"] is False

        r = client.put(
            "/argos/portails/portail-prive/credentials",
            json={"credentials": {"login": "demo", "password": "ultra-secret"}},
        )
        assert r.status_code == 200

        r = client.get("/argos/portails")
        assert r.status_code == 200
        body = r.text
        assert "ultra-secret" not in body
        portail = next(p for p in r.json() if p["nom"] == "portail-prive")
        assert portail["credentials_configures"] is True


def test_endpoint_supprime_credentials():
    from hermes.main import app

    with TestClient(app) as client:
        client.put(
            "/argos/portails/portail-prive",
            json={"url_base": "https://prive.example.test", "type": "prive"},
        )
        client.put(
            "/argos/portails/portail-prive/credentials",
            json={"credentials": {"token": "abc"}},
        )

        r = client.delete("/argos/portails/portail-prive/credentials")
        assert r.status_code == 200

        r = client.get("/argos/portails")
        portail = next(p for p in r.json() if p["nom"] == "portail-prive")
        assert portail["credentials_configures"] is False

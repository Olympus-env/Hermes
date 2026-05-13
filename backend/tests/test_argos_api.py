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


def test_endpoint_scheduler_etat():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/argos/scheduler")
        assert r.status_code == 200
        data = r.json()
        assert "en_marche" in data
        assert "jobs" in data

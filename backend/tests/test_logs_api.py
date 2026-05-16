"""Tests de l'API journal des agents (tâche V1 #5)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.db.models import LogAgent, NiveauLog
from hermes.db.session import get_engine, init_db


def _seed(session: Session) -> None:
    session.add_all(
        [
            LogAgent(agent="ARGOS", niveau=NiveauLog.INFO, message="collecte 1"),
            LogAgent(agent="KRINOS", niveau=NiveauLog.INFO, message="analyse 1"),
            LogAgent(
                agent="HERMION", niveau=NiveauLog.WARNING, message="rédaction lente"
            ),
            LogAgent(agent="HERMES", niveau=NiveauLog.ERROR, message="pipeline KO"),
        ]
    )
    session.commit()


def test_liste_complete_et_tri_desc():
    from hermes.main import app

    init_db()
    with Session(get_engine()) as s:
        _seed(s)

    with TestClient(app) as client:
        r = client.get("/logs")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 4
        assert len(data["items"]) == 4
        # Le plus récent d'abord (HERMES inséré en dernier).
        assert data["items"][0]["agent"] == "HERMES"


def test_filtre_par_agent_et_niveau():
    from hermes.main import app

    init_db()
    with Session(get_engine()) as s:
        _seed(s)

    with TestClient(app) as client:
        r = client.get("/logs?agent=KRINOS")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["agent"] == "KRINOS"

        r = client.get("/logs?niveau=error")
        assert r.json()["total"] == 1
        assert r.json()["items"][0]["message"] == "pipeline KO"


def test_pagination():
    from hermes.main import app

    init_db()
    with Session(get_engine()) as s:
        _seed(s)

    with TestClient(app) as client:
        r = client.get("/logs?limit=2&offset=0")
        data = r.json()
        assert data["total"] == 4
        assert len(data["items"]) == 2
        assert data["limit"] == 2

        r2 = client.get("/logs?limit=2&offset=2")
        assert len(r2.json()["items"]) == 2
        # Pas de chevauchement entre les deux pages.
        ids_p1 = {i["id"] for i in data["items"]}
        ids_p2 = {i["id"] for i in r2.json()["items"]}
        assert ids_p1.isdisjoint(ids_p2)


def test_niveau_invalide_rejete():
    from hermes.main import app

    init_db()
    with TestClient(app) as client:
        r = client.get("/logs?niveau=pasunniveau")
        assert r.status_code == 422

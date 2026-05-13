"""Tests de fumée — Phase 1.

Vérifient que :
- l'app FastAPI démarre,
- /health répond,
- la BDD MNEMOSYNE est créée avec ses 8 tables.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _tmp_db(tmp_path_factory):
    """BDD isolée pour les tests."""
    tmpdir = tmp_path_factory.mktemp("hermes_test")
    os.environ["HERMES_DB_PATH"] = str(tmpdir / "test.db")
    os.environ["HERMES_STORAGE_PATH"] = str(tmpdir / "storage")
    os.environ["HERMES_LOG_PATH"] = str(tmpdir / "logs")
    yield tmpdir


def test_app_demarre():
    from fastapi.testclient import TestClient

    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["app"] == "HERMES"


def test_root():
    from fastapi.testclient import TestClient

    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["app"] == "HERMES"


def test_info_avec_bdd():
    from fastapi.testclient import TestClient

    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/info")
        assert r.status_code == 200
        data = r.json()
        assert "ARGOS" in data["agents"]
        assert "KRINOS" in data["agents"]
        assert "HERMION" in data["agents"]
        assert data["portails_configures"] == 0


def test_tables_creees():
    """Vérifie que les 8 tables MNEMOSYNE sont présentes."""
    from sqlmodel import SQLModel

    from hermes.db.session import get_engine, init_db

    init_db()
    tables_attendues = {
        "appels_offre",
        "documents",
        "analyses_krinos",
        "reponses_hermion",
        "portails",
        "base_connaissances",
        "parametres",
        "logs_agents",
    }
    tables_reelles = set(SQLModel.metadata.tables.keys())
    manquantes = tables_attendues - tables_reelles
    assert not manquantes, f"Tables manquantes : {manquantes}"


def test_crud_portail():
    """Création / lecture d'un portail de test."""
    from sqlmodel import Session, select

    from hermes.db.models import Portail, TypePortail
    from hermes.db.session import get_engine, init_db

    init_db()
    with Session(get_engine()) as s:
        p = Portail(nom="BOAMP-test", url_base="https://www.boamp.fr", type=TypePortail.PUBLIC)
        s.add(p)
        s.commit()

        rec = s.exec(select(Portail).where(Portail.nom == "BOAMP-test")).first()
        assert rec is not None
        assert rec.actif is True
        assert rec.frequence_minutes == 360

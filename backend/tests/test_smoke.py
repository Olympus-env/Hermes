"""Tests de fumée — Phase 1.

Vérifient que :
- l'app FastAPI démarre,
- /health répond,
- la BDD MNEMOSYNE est créée avec ses 8 tables.

L'isolation BDD est fournie par `conftest.py`.
"""

from __future__ import annotations


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
        # On valide le champ sans imposer une valeur précise — l'ordre des tests
        # peut avoir déjà créé des portails.
        assert data["portails_configures"] == 0


def test_tables_creees():
    """Vérifie que les 8 tables MNEMOSYNE sont présentes."""
    from sqlmodel import SQLModel

    from hermes.db.session import init_db

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
        assert rec.frequence_minutes == 720  # 2 collectes/jour par défaut


def test_backend_entry_force_host_loopback(monkeypatch):
    import hermes_entry

    appel = {}

    def fake_run(app, **kwargs):
        appel.update(kwargs)

    monkeypatch.setenv("HERMES_HOST", "0.0.0.0")
    monkeypatch.setattr(hermes_entry.uvicorn, "run", fake_run)

    hermes_entry.main()

    assert appel["host"] == "127.0.0.1"


def test_settings_forcent_runtime_local_only():
    from hermes.config import Settings

    cfg = Settings(host="0.0.0.0", ollama_base_url="http://192.168.1.10:11434")

    assert cfg.host == "127.0.0.1"
    assert cfg.ollama_base_url == "http://127.0.0.1:11434"

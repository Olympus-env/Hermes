"""Configuration globale des tests — isole MNEMOSYNE dans un répertoire temporaire.

Important : ce fichier est chargé par pytest AVANT toute collecte de tests,
donc les variables d'environnement sont posées avant que `hermes.config.Settings`
ne soit instancié.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="hermes_test_"))
os.environ["HERMES_DB_PATH"] = str(_TMP_DIR / "test.db")
os.environ["HERMES_STORAGE_PATH"] = str(_TMP_DIR / "storage")
os.environ["HERMES_LOG_PATH"] = str(_TMP_DIR / "logs")
os.environ["HERMES_DEBUG"] = "true"
os.environ["HERMES_SCHEDULER_AUTO_START"] = "false"
# TestClient envoie `Host: testserver` : autorisé uniquement en test.
os.environ["HERMES_HOTES_AUTORISES"] = '["127.0.0.1","localhost","testserver"]'


@pytest.fixture(autouse=True)
def _entete_csrf_par_defaut(monkeypatch):
    """Le frontend envoie X-Hermes-Client sur tout non-GET : les TestClient aussi.

    Les tests CSRF retirent l'en-tête explicitement (`client.headers.pop`).
    """
    from fastapi.testclient import TestClient

    init = TestClient.__init__

    def _init(self, *args, **kwargs):
        init(self, *args, **kwargs)
        self.headers.setdefault("X-Hermes-Client", "tests")

    monkeypatch.setattr(TestClient, "__init__", _init)


@pytest.fixture(autouse=True)
def _bdd_propre():
    """Vide MNEMOSYNE avant chaque test pour garantir l'isolation."""
    from sqlmodel import SQLModel

    from hermes.db.session import get_engine, init_db

    engine = get_engine()
    SQLModel.metadata.drop_all(engine)
    init_db()
    yield

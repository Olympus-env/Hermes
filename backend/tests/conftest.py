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


@pytest.fixture(autouse=True)
def _bdd_propre():
    """Vide MNEMOSYNE avant chaque test pour garantir l'isolation."""
    from sqlmodel import SQLModel

    from hermes.db.session import get_engine, init_db

    engine = get_engine()
    SQLModel.metadata.drop_all(engine)
    init_db()
    yield

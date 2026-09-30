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
# Juge local PYTHIA : coupé par défaut en test (les tests dédiés l'activent).
os.environ["HERMES_JUGE_LOCAL_ACTIF"] = "false"
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


@pytest.fixture(autouse=True)
def _laya_isole(monkeypatch, tmp_path):
    """Laya : jamais de modèle réel ni de réseau en pytest.

    Dossier des poids dans un répertoire temporaire, moteur simulé absent par défaut
    (chaque test injecte le sien via `laya._moteur`), et transport de téléchargement
    qui enregistre toute requête sortante — un test qui la déclenche sans l'avoir
    prévu échoue sur `requetes_reseau_laya`.
    """
    import httpx

    from hermes.agents.krinos import laya, laya_modele
    from hermes.config import settings

    requetes: list[httpx.Request] = []

    def refuser(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(599)

    monkeypatch.setattr(settings, "laya_actif", False)
    monkeypatch.setattr(settings, "laya_dossier", tmp_path / "laya")
    monkeypatch.setattr(settings, "laya_precision", "fp16")
    monkeypatch.setattr(settings, "laya_max_tokens", 1024)
    monkeypatch.setattr(laya, "_moteur", None)
    monkeypatch.setattr(laya_modele, "_transport", httpx.MockTransport(refuser))
    monkeypatch.setattr(laya_modele, "_etat", laya_modele.EtatTelechargement())
    laya_modele.oublier_verifications()  # cache d'empreintes et état « altéré » du process
    yield requetes

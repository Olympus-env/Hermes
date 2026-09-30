"""Intégrité du modèle Laya au chargement (#63) : SHA-256 complet au premier chargement du
moteur, mis en cache par process, refus + « à réinstaller » + journal KRINOS en cas
d'échec, aucun retéléchargement sans consentement. Fichiers factices, moteur simulé."""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes.agents.krinos import laya, laya_modele, laya_moteur
from hermes.agents.krinos.laya_moteur import ModeleLayaAltere
from hermes.agents.krinos.ponderation import Ponderation
from hermes.config import settings
from hermes.db.models import LogAgent
from hermes.db.session import get_engine
from hermes.main import app

from .laya_faux import MoteurSimule
from .test_laya_modele import CONTENUS, _telecharger, faux_manifeste  # noqa: F401

CIBLE = "onnx/model_fp16.onnx_data"


class FauxMoteurOnnx(MoteurSimule):
    """Remplace `MoteurOnnx` : pas d'ONNX Runtime, mais même contrat de construction."""

    def __init__(self, dossier, precision, *, max_len=1024):
        super().__init__()


@pytest.fixture
def modele_installe(faux_manifeste, monkeypatch):  # noqa: F811
    _telecharger("fp16")
    laya_moteur.liberer_moteurs()
    monkeypatch.setattr(laya_moteur, "MoteurOnnx", FauxMoteurOnnx)
    monkeypatch.setattr(settings, "laya_actif", True)
    yield faux_manifeste
    laya_moteur.liberer_moteurs()


def _juger() -> None:
    with Session(get_engine()) as session:
        asyncio.run(laya.juger(session, "état", Ponderation()))


def _alterer_meme_taille() -> None:
    cible = laya_modele.dossier_modele() / CIBLE
    cible.write_bytes(b"Z" * len(CONTENUS[CIBLE]))
    assert cible.stat().st_size == len(CONTENUS[CIBLE])


def test_fichier_altere_de_meme_taille_refuse_au_chargement(modele_installe):
    _alterer_meme_taille()
    # Taille et verifie.json ne suffisent plus à le détecter...
    assert laya_modele.statut_modele("fp16").installe is True
    n_requetes = len(modele_installe.requetes)
    # ... mais le premier chargement du moteur le rejette, journalise, et ne télécharge rien.
    with pytest.raises(ModeleLayaAltere) as exc:
        _juger()
    assert exc.value.fichiers == [CIBLE]
    assert len(modele_installe.requetes) == n_requetes
    with Session(get_engine()) as session:
        logs = session.exec(select(LogAgent).where(LogAgent.agent == "KRINOS")).all()
    assert len(logs) == 1 and "réinstaller" in logs[0].message and CIBLE in logs[0].message
    with pytest.raises(laya_moteur.ErreurLaya):
        _juger()  # toujours refusé (modèle à réinstaller), sans second log
    with Session(get_engine()) as session:
        assert len(session.exec(select(LogAgent)).all()) == 1


def test_api_marque_le_modele_a_reinstaller(modele_installe):
    with TestClient(app) as client:
        assert client.get("/krinos/laya/modele").json()["a_reinstaller"] == []
        _alterer_meme_taille()
        with pytest.raises(ModeleLayaAltere):
            _juger()
        corps = client.get("/krinos/laya/modele").json()
    assert corps["installe"] is False
    assert corps["a_reinstaller"] == [CIBLE] and CIBLE in corps["manquants"]


def test_reinstallation_consentie_repare_le_fichier(modele_installe):
    _alterer_meme_taille()
    with pytest.raises(ModeleLayaAltere):
        _juger()
    n = len(modele_installe.requetes)
    assert _telecharger("fp16").statut == "success"
    # Seul le fichier altéré est retéléchargé.
    assert [r.url.path.split("/")[-1] for r in modele_installe.requetes[n:]] == [
        "model_fp16.onnx_data"
    ]
    assert laya_modele.statut_modele("fp16").a_reinstaller == []
    _juger()  # se charge de nouveau


def test_fichier_sain_hache_une_seule_fois(modele_installe, monkeypatch):
    appels: list[str] = []
    reel = laya_modele.sha256_fichier
    monkeypatch.setattr(
        laya_modele, "sha256_fichier", lambda c: (appels.append(c.name), reel(c))[1]
    )
    _juger()
    assert len(appels) == len(laya_modele.fichiers_requis("fp16"))
    # Nouveau chargement du moteur dans le même process : aucun rehachage.
    laya_moteur.liberer_moteurs()
    _juger()
    assert laya_modele.verifier_integrite("fp16") == []
    assert len(appels) == len(laya_modele.fichiers_requis("fp16"))


def test_cache_invalide_quand_mtime_ou_taille_change(modele_installe, monkeypatch):
    appels: list[str] = []
    reel = laya_modele.sha256_fichier
    monkeypatch.setattr(
        laya_modele, "sha256_fichier", lambda c: (appels.append(c.name), reel(c))[1]
    )
    assert laya_modele.verifier_integrite("fp16") == []
    n = len(appels)
    cible = laya_modele.dossier_modele() / CIBLE
    contenu = cible.read_bytes()
    cible.write_bytes(b"Z" * len(contenu))  # même taille, mtime différent
    os.utime(cible, ns=(1, 1))
    assert laya_modele.verifier_integrite("fp16") == [CIBLE]
    assert len(appels) == n + 1

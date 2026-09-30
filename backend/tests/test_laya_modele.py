"""Tests du téléchargement consenti du modèle Laya : intégrité SHA-256, reprise,
consentement, aucune requête sans clic. Serveur simulé : aucun réseau réel."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from hermes.agents.krinos import laya_modele
from hermes.agents.krinos.laya_modele import FichierModele
from hermes.config import settings
from hermes.db.session import init_db
from hermes.main import app

CONTENUS = {
    "tokenizer.json": b"T" * 3000,
    "config.json": b'{"laya": {"max_len": 1024}}',
    "onnx/model_fp16.onnx": b"graphe" * 50,
    "onnx/model_fp16.onnx_data": bytes(range(256)) * 40,
    "onnx/model.onnx": b"g32" * 50,
    "onnx/model.onnx_data": bytes(range(255, -1, -1)) * 80,
}


def _fichier(chemin: str, contenu: bytes | None = None) -> FichierModele:
    c = CONTENUS[chemin] if contenu is None else contenu
    return FichierModele(chemin, hashlib.sha256(c).hexdigest(), len(c))


@pytest.fixture
def faux_manifeste(monkeypatch):
    """Manifeste minuscule + serveur simulé ; `serveur.requetes` liste les requêtes."""
    monkeypatch.setattr(laya_modele, "TOKENIZER", _fichier("tokenizer.json"))
    monkeypatch.setattr(laya_modele, "CONFIG", _fichier("config.json"))
    monkeypatch.setattr(
        laya_modele,
        "FICHIERS_PAR_PRECISION",
        {
            "fp16": (_fichier("onnx/model_fp16.onnx"), _fichier("onnx/model_fp16.onnx_data")),
            "fp32": (_fichier("onnx/model.onnx"), _fichier("onnx/model.onnx_data")),
        },
    )
    monkeypatch.setattr(laya_modele, "URL_BASE", "https://hf.example.test/depot/resolve/rev/")

    class Serveur:
        requetes: list[httpx.Request] = []
        corrompre: set[str] = set()
        ignorer_range = False
        statut: int = 200

        def handler(self, request: httpx.Request) -> httpx.Response:
            self.requetes.append(request)
            chemin = request.url.path.split("/resolve/rev/")[1]
            if self.statut != 200:
                return httpx.Response(self.statut)
            corps = CONTENUS[chemin]
            if chemin in self.corrompre:
                corps = b"X" * len(corps)
            m = re.match(r"bytes=(\d+)-", request.headers.get("range", ""))
            if m and not self.ignorer_range:
                return httpx.Response(206, content=corps[int(m.group(1)) :])
            return httpx.Response(200, content=corps)

    serveur = Serveur()
    serveur.requetes = []
    serveur.corrompre = set()
    monkeypatch.setattr(laya_modele, "_transport", httpx.MockTransport(serveur.handler))
    return serveur


def _telecharger(precision: str = "fp16") -> laya_modele.EtatTelechargement:
    etat = laya_modele.EtatTelechargement(precision=precision, en_cours=True)
    asyncio.run(laya_modele.executer_telechargement(etat, precision))
    return etat


def test_manifeste_reel_epingle_et_coherent():
    assert re.fullmatch(r"[0-9a-f]{40}", laya_modele.REVISION)
    assert laya_modele.URL_BASE.startswith("https://huggingface.co/onnx-community/")
    assert laya_modele.REVISION in laya_modele.URL_BASE
    for precision in laya_modele.PRECISIONS:
        fichiers = laya_modele.fichiers_requis(precision)
        assert all(re.fullmatch(r"[0-9a-f]{64}", f.sha256) and f.taille > 0 for f in fichiers)
        chemins = [f.chemin for f in fichiers]
        assert "tokenizer.json" in chemins and "config.json" in chemins
    assert 600e6 < laya_modele.taille_totale("fp16") < 800e6  # ~0,7 Go
    assert 1.2e9 < laya_modele.taille_totale("fp32") < 1.5e9  # ~1,3 Go
    with pytest.raises(laya_modele.ErreurLaya):
        laya_modele.fichiers_requis("int4")


def test_dossier_dans_le_dossier_de_donnees_hermes(monkeypatch):
    monkeypatch.setattr(settings, "laya_dossier", None)
    d = laya_modele.dossier_modele()
    assert d == settings.db_path.parent / "modeles" / "laya"


def test_telechargement_ok_verifie_sha256_et_installe(faux_manifeste):
    assert laya_modele.statut_modele("fp16").installe is False
    etat = _telecharger("fp16")
    assert etat.statut == "success" and etat.erreur is None and not etat.en_cours
    assert etat.octets_telecharges == etat.octets_total == laya_modele.taille_totale("fp16")
    st = laya_modele.statut_modele("fp16")
    assert st.installe and st.manquants == []
    assert laya_modele.verifier_integrite("fp16") == []
    # Seuls les fichiers de la précision demandée ont été téléchargés.
    assert laya_modele.statut_modele("fp32").installe is False
    assert not any("model.onnx" in r.url.path.split("/")[-1] for r in faux_manifeste.requetes)
    # Un second passage ne re-télécharge rien.
    n = len(faux_manifeste.requetes)
    _telecharger("fp16")
    assert len(faux_manifeste.requetes) == n


def test_fichier_corrompu_est_rejete(faux_manifeste):
    faux_manifeste.corrompre = {"onnx/model_fp16.onnx_data"}
    etat = _telecharger("fp16")
    assert etat.statut == "erreur" and "SHA-256" in (etat.erreur or "")
    dossier = laya_modele.dossier_modele()
    assert not (dossier / "onnx/model_fp16.onnx_data").exists()
    assert not (dossier / "onnx/model_fp16.onnx_data.part").exists()  # pas de reprise corrompue
    assert laya_modele.statut_modele("fp16").installe is False


def test_erreur_http_remontee_sans_planter(faux_manifeste):
    faux_manifeste.statut = 503
    etat = _telecharger("fp16")
    assert etat.statut == "erreur" and "503" in (etat.erreur or "")
    assert etat.en_cours is False


def test_reprise_sur_fichier_partiel(faux_manifeste):
    dossier = laya_modele.dossier_modele()
    (dossier / "onnx").mkdir(parents=True)
    contenu = CONTENUS["onnx/model_fp16.onnx_data"]
    (dossier / "onnx/model_fp16.onnx_data.part").write_bytes(contenu[:4000])
    etat = _telecharger("fp16")
    assert etat.statut == "success"
    demande = [r for r in faux_manifeste.requetes if r.url.path.endswith("model_fp16.onnx_data")]
    assert demande[0].headers["range"] == "bytes=4000-"
    assert laya_modele.verifier_integrite("fp16") == []


def test_serveur_sans_range_on_repart_de_zero(faux_manifeste):
    faux_manifeste.ignorer_range = True
    dossier = laya_modele.dossier_modele()
    (dossier / "onnx").mkdir(parents=True)
    (dossier / "onnx/model_fp16.onnx_data.part").write_bytes(b"\x00" * 100)
    assert _telecharger("fp16").statut == "success"
    assert laya_modele.verifier_integrite("fp16") == []


def test_fichier_altere_apres_coup_n_est_plus_installe(faux_manifeste):
    _telecharger("fp16")
    cible = laya_modele.dossier_modele() / "onnx/model_fp16.onnx_data"
    cible.write_bytes(cible.read_bytes()[:-1])  # tronqué
    assert laya_modele.statut_modele("fp16").installe is False
    cible.write_bytes(b"Z" * laya_modele.fichiers_requis("fp16")[3].taille)  # même taille
    assert laya_modele.verifier_integrite("fp16") == ["onnx/model_fp16.onnx_data"]


# --- API : consentement explicite, rien au démarrage ---------------------------------


def test_aucune_requete_sortante_au_demarrage_ni_a_la_lecture(faux_manifeste):
    init_db()
    with TestClient(app) as client:  # le démarrage de l'application ne télécharge rien
        assert client.get("/krinos/laya").status_code == 200
        assert client.get("/krinos/laya/modele").json()["installe"] is False
    assert faux_manifeste.requetes == []


def test_telechargement_refuse_sans_confirmation(faux_manifeste):
    init_db()
    with TestClient(app) as client:
        r = client.post("/krinos/laya/modele/telecharger", json={"precision": "fp16"})
        assert r.status_code == 400
        r = client.post(
            "/krinos/laya/modele/telecharger", json={"precision": "fp16", "confirme": False}
        )
        assert r.status_code == 400
        r = client.post(
            "/krinos/laya/modele/telecharger", json={"precision": "int4", "confirme": True}
        )
        assert r.status_code == 422
    assert faux_manifeste.requetes == []


def test_telechargement_confirme_avec_progression(faux_manifeste):
    init_db()
    with TestClient(app) as client:
        r = client.post(
            "/krinos/laya/modele/telecharger", json={"precision": "fp16", "confirme": True}
        )
        assert r.status_code == 200
        assert r.json()["octets_total"] == laya_modele.taille_totale("fp16")
        fin = time.time() + 20
        while time.time() < fin:
            modele = client.get("/krinos/laya/modele").json()
            if not modele["progression"]["en_cours"]:
                break
            time.sleep(0.05)
        assert modele["installe"] is True
        prog = modele["progression"]
        assert prog["statut"] == "success" and prog["pourcent"] == 100.0 and prog["erreur"] is None
        cfg = client.get("/krinos/laya").json()
        assert cfg["modele"]["installe"] is True
        assert cfg["actif"] is False  # installer ne suffit pas : activation = autre clic
        client.put("/krinos/laya", json={"actif": True})
        assert client.get("/krinos/laya").json()["operationnel"] is True
        assert client.post("/krinos/laya/modele/annuler").status_code == 200

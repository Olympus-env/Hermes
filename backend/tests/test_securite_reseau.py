"""Sécurité réseau (issue #14) : Host, CSRF, SSRF, plafond de taille, master.key."""

from __future__ import annotations

import io
import os
import stat
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import hermes.agents.krinos.downloader as downloader
from hermes.agents.krinos.downloader import (
    ErreurTelechargementDocument,
    ReponseDocument,
    _persister_document,
    _telecharger_url,
    _type_document,
    telecharger_documents_ao,
)
from hermes.db.models import AppelOffre, TypeDocument
from hermes.db.session import get_engine
from hermes.main import app
from hermes.securite import credentials

# --- Host / CSRF ---------------------------------------------------------


def test_host_etranger_refuse_400():
    with TestClient(app, base_url="http://evil.example") as client:
        assert client.get("/health").status_code == 400


def test_host_local_accepte():
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/health").status_code == 200


def test_post_sans_entete_client_refuse_403():
    with TestClient(app) as client:
        client.headers.pop("X-Hermes-Client")
        r = client.post("/orchestration/traiter")
        assert r.status_code == 403
        # Les lectures restent libres.
        assert client.get("/health").status_code == 200


def test_post_avec_entete_client_passe_le_garde_csrf():
    with TestClient(app) as client:
        r = client.post("/orchestration/traiter")
        assert r.status_code != 403


def test_preflight_cors_autorise_l_entete_client():
    with TestClient(app) as client:
        r = client.options(
            "/orchestration/traiter",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-hermes-client",
            },
        )
        assert r.status_code == 200
        assert "credentials" not in " ".join(k.lower() for k in r.headers)
        # Origine tierce : preflight refusé.
        r2 = client.options(
            "/orchestration/traiter",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-hermes-client",
            },
        )
        assert r2.status_code == 400


# --- SSRF ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/secret",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
        "file:///etc/passwd",
    ],
)
async def test_urls_non_publiques_refusees(url):
    with pytest.raises(ErreurTelechargementDocument):
        await _telecharger_url(url)


async def _ips_publiques(hote):
    if hote[0].isdigit():
        return [hote]  # IP littérale : renvoyée telle quelle
    return ["93.184.216.34"]


async def test_redirection_vers_ip_privee_refusee(monkeypatch):
    monkeypatch.setattr(downloader, "_resoudre_ips", _ips_publiques)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.test":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        raise AssertionError("la cible privée ne doit jamais être contactée")

    with pytest.raises(ErreurTelechargementDocument, match="non publique"):
        await _telecharger_url("http://example.test/a", transport=httpx.MockTransport(handler))


async def test_trop_de_redirections(monkeypatch):
    monkeypatch.setattr(downloader, "_resoudre_ips", _ips_publiques)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://example.test/b"})

    with pytest.raises(ErreurTelechargementDocument, match="redirections"):
        await _telecharger_url("http://example.test/a", transport=httpx.MockTransport(handler))


async def test_flux_au_dela_du_plafond_coupe(monkeypatch):
    monkeypatch.setattr(downloader, "_resoudre_ips", _ips_publiques)
    monkeypatch.setattr(downloader, "MAX_DOCUMENT_OCTETS", 1024)
    lus = 0

    async def flux():
        nonlocal lus
        for _ in range(100):
            lus += 512
            yield b"x" * 512

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=flux())  # sans Content-Length

    with pytest.raises(ErreurTelechargementDocument, match="volumineux"):
        await _telecharger_url("http://example.test/a", transport=httpx.MockTransport(handler))
    assert lus < 100 * 512  # coupé avant la fin du flux


async def test_content_length_trop_grand_refuse(monkeypatch):
    monkeypatch.setattr(downloader, "_resoudre_ips", _ips_publiques)
    monkeypatch.setattr(downloader, "MAX_DOCUMENT_OCTETS", 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x", headers={"content-length": "999999"})

    with pytest.raises(ErreurTelechargementDocument, match="volumineux"):
        await _telecharger_url("http://example.test/a", transport=httpx.MockTransport(handler))


async def test_telechargement_nominal(monkeypatch):
    monkeypatch.setattr(downloader, "_resoudre_ips", _ips_publiques)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.7 ok")

    r = await _telecharger_url("http://example.test/a", transport=httpx.MockTransport(handler))
    assert r.contenu == b"%PDF-1.7 ok"


# --- Best-effort ---------------------------------------------------------


async def test_echec_d_une_url_n_arrete_pas_les_suivantes(monkeypatch):
    async def faux(url: str) -> ReponseDocument:
        if "mauvais" in url:
            raise ErreurTelechargementDocument("boom")
        return ReponseDocument(contenu=b"%PDF-1.4 bon", content_type="application/pdf")

    monkeypatch.setattr(downloader, "_telecharger_url", faux)
    with Session(get_engine()) as session:
        ao = AppelOffre(titre="AO", url_source="https://example.test/x")
        session.add(ao)
        session.commit()
        session.refresh(ao)
        erreurs: list[str] = []
        res = await telecharger_documents_ao(
            session,
            ao,
            urls=["https://example.test/mauvais", "https://example.test/bon.pdf"],
            erreurs=erreurs,
        )
        assert len(res) == 1 and len(erreurs) == 1 and "mauvais" in erreurs[0]

        with pytest.raises(ErreurTelechargementDocument):
            await telecharger_documents_ao(session, ao, urls=["https://example.test/mauvais"])


# --- Noms et magic bytes -------------------------------------------------


def test_magic_bytes_priment_sur_l_extension():
    assert _type_document("http://x/a.html", "text/html", None, b"%PDF-1.4") == TypeDocument.PDF

    def zip_avec(nom: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(nom, "x")
        return buf.getvalue()

    docx = zip_avec("word/document.xml")
    xlsx = zip_avec("xl/workbook.xml")
    assert _type_document("http://x/a", None, None, docx) == TypeDocument.DOCX
    assert _type_document("http://x/a", None, None, xlsx) == TypeDocument.XLSX


def test_noms_identiques_contenus_differents_ne_s_ecrasent_pas():
    with Session(get_engine()) as session:
        ao = AppelOffre(titre="AO", url_source="https://example.test/x")
        session.add(ao)
        session.commit()
        session.refresh(ao)
        a = _persister_document(
            session, ao, "http://x/dce.pdf", ReponseDocument(b"%PDF-1 A", "application/pdf")
        )
        b = _persister_document(
            session, ao, "http://x/dce.pdf", ReponseDocument(b"%PDF-1 B", "application/pdf")
        )
        assert a.document.chemin_local != b.document.chemin_local
        assert a.document.nom_fichier.startswith(a.document.checksum_sha256[:12] + "-")


# --- master.key ----------------------------------------------------------


def test_master_key_creee_en_0600_puis_relue(tmp_path):
    chemin = tmp_path / "sous" / "master.key"
    k1 = credentials._charger_ou_generer_cle_fichier(chemin)
    assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600
    assert credentials._charger_ou_generer_cle_fichier(chemin) == k1

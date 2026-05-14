"""Tests KRINOS — extraction documentaire Phase 4."""

from __future__ import annotations

import hashlib

from sqlmodel import Session, select

from hermes.agents.krinos.downloader import ReponseDocument
from hermes.config import settings
from hermes.db.models import AppelOffre, Document, LogAgent, StatutAO, TypeDocument
from hermes.db.session import get_engine, init_db


def _ao_et_document(
    session: Session,
    nom: str,
    contenu: bytes,
    type_doc: TypeDocument,
) -> Document:
    chemin = settings.storage_path / nom
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)

    ao = AppelOffre(
        titre="AO KRINOS test",
        url_source="https://example.test/ao/krinos",
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)

    document = Document(
        appel_offre_id=ao.id,  # type: ignore[arg-type]
        nom_fichier=nom,
        chemin_local=nom,
        type=type_doc,
        taille_octets=0,
        checksum_sha256="pending",
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def test_extraire_html_persiste_contenu_et_checksum():
    from hermes.agents.krinos import extraire_document

    init_db()
    contenu = (
        b"<html><body><h1>Reglement consultation</h1>"
        b"<script>ignore()</script></body></html>"
    )
    with Session(get_engine()) as session:
        document = _ao_et_document(session, "docs/test.html", contenu, TypeDocument.HTML)

        extraction = extraire_document(document)

    assert "Reglement consultation" in extraction.texte
    assert "ignore" not in extraction.texte
    assert extraction.checksum_sha256 == hashlib.sha256(contenu).hexdigest()
    assert extraction.taille_octets == len(contenu)


def test_endpoint_extrait_document_et_journalise():
    from fastapi.testclient import TestClient

    from hermes.main import app

    init_db()
    with Session(get_engine()) as session:
        document = _ao_et_document(
            session,
            "docs/cctp.txt",
            b"CCTP maintenance applicative",
            TypeDocument.AUTRE,
        )
        document_id = document.id

    with TestClient(app) as client:
        r = client.post(f"/krinos/documents/{document_id}/extraire")

    assert r.status_code == 200
    data = r.json()
    assert data["document_id"] == document_id
    assert data["caracteres_extraits"] == len("CCTP maintenance applicative")

    with Session(get_engine()) as session:
        document = session.get(Document, document_id)
        assert document is not None
        assert document.contenu_extrait == "CCTP maintenance applicative"
        logs = session.exec(select(LogAgent).where(LogAgent.agent == "KRINOS")).all()
        assert logs


def test_endpoint_extrait_documents_ao_et_passe_en_analyse():
    from fastapi.testclient import TestClient

    from hermes.main import app

    init_db()
    with Session(get_engine()) as session:
        document = _ao_et_document(
            session,
            "docs/rc.txt",
            b"Reglement de consultation",
            TypeDocument.AUTRE,
        )
        ao_id = document.appel_offre_id

    with TestClient(app) as client:
        r = client.post(f"/krinos/appels-offre/{ao_id}/extraire")

    assert r.status_code == 200
    assert r.json()["documents_traites"] == 1

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        assert ao is not None
        assert ao.statut == StatutAO.ANALYSE


def test_endpoint_refuse_chemin_hors_storage():
    from fastapi.testclient import TestClient

    from hermes.main import app

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(titre="AO invalide", url_source="https://example.test/ao/bad")
        session.add(ao)
        session.commit()
        session.refresh(ao)
        document = Document(
            appel_offre_id=ao.id,  # type: ignore[arg-type]
            nom_fichier="bad.txt",
            chemin_local="../bad.txt",
            type=TypeDocument.AUTRE,
            checksum_sha256="pending",
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = document.id

    with TestClient(app) as client:
        r = client.post(f"/krinos/documents/{document_id}/extraire")

    assert r.status_code == 400
    assert "hors storage" in r.json()["detail"]


def test_endpoint_telecharge_document_depuis_url_source(monkeypatch):
    from fastapi.testclient import TestClient

    import hermes.agents.krinos.downloader as downloader
    from hermes.main import app

    async def fake_telecharger_url(url: str) -> ReponseDocument:
        assert url == "https://example.test/ao/source"
        return ReponseDocument(
            contenu=b"<html><body>Dossier consultation</body></html>",
            content_type="text/html; charset=utf-8",
            nom_fichier=None,
        )

    monkeypatch.setattr(downloader, "_telecharger_url", fake_telecharger_url)

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(titre="AO source", url_source="https://example.test/ao/source")
        session.add(ao)
        session.commit()
        session.refresh(ao)
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.post(f"/krinos/appels-offre/{ao_id}/documents/telecharger")

    assert r.status_code == 200
    data = r.json()
    assert data["nouveaux"] == 1
    assert data["documents"][0]["type"] == "html"

    with Session(get_engine()) as session:
        documents = session.exec(select(Document).where(Document.appel_offre_id == ao_id)).all()
        assert len(documents) == 1
        document = documents[0]
        assert document.taille_octets > 0
        assert (settings.storage_path / document.chemin_local).exists()


def test_endpoint_telechargement_dedoublonne_par_checksum(monkeypatch):
    from fastapi.testclient import TestClient

    import hermes.agents.krinos.downloader as downloader
    from hermes.main import app

    async def fake_telecharger_url(_url: str) -> ReponseDocument:
        return ReponseDocument(
            contenu=b"meme contenu",
            content_type="application/pdf",
            nom_fichier="dce.pdf",
        )

    monkeypatch.setattr(downloader, "_telecharger_url", fake_telecharger_url)

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(titre="AO dedupe", url_source="https://example.test/dce.pdf")
        session.add(ao)
        session.commit()
        session.refresh(ao)
        ao_id = ao.id

    with TestClient(app) as client:
        r1 = client.post(f"/krinos/appels-offre/{ao_id}/documents/telecharger")
        r2 = client.post(f"/krinos/appels-offre/{ao_id}/documents/telecharger")

    assert r1.status_code == 200
    assert r1.json()["nouveaux"] == 1
    assert r2.status_code == 200
    assert r2.json()["nouveaux"] == 0

    with Session(get_engine()) as session:
        documents = session.exec(select(Document).where(Document.appel_offre_id == ao_id)).all()
        assert len(documents) == 1

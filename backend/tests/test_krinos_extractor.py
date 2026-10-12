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
        checksum_sha256=hashlib.sha256(contenu).hexdigest(),
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


# --------------------------------------------------------------------------- #
# Intégrité SHA-256 (CDC §9.3, issue #91)
# --------------------------------------------------------------------------- #


def test_fichier_intact_extraction_normale_et_checksum_inchange():
    from hermes.agents.krinos.extractor import extraire_documents_appel_offre

    init_db()
    contenu = b"<html><body><p>Cahier des charges</p></body></html>"
    with Session(get_engine()) as session:
        document = _ao_et_document(session, "docs/intact.html", contenu, TypeDocument.HTML)
        ao = session.get(AppelOffre, document.appel_offre_id)
        reference = document.checksum_sha256

        rapport = extraire_documents_appel_offre(session, ao)

        assert rapport.documents_traites == 1
        assert not rapport.erreurs
        session.refresh(document)
        assert document.integrite_ok is True
        assert document.checksum_sha256 == reference
        assert "Cahier des charges" in (document.contenu_extrait or "")


def test_fichier_modifie_apres_telechargement_alerte_et_checksum_conserve():
    import pytest

    from hermes.agents.krinos import extraire_document
    from hermes.agents.krinos.extractor import (
        ErreurIntegriteDocument,
        extraire_documents_appel_offre,
    )

    init_db()
    original = b"<html><body><p>Version d'origine</p></body></html>"
    with Session(get_engine()) as session:
        document = _ao_et_document(session, "docs/altere.html", original, TypeDocument.HTML)
        ao = session.get(AppelOffre, document.appel_offre_id)
        reference = document.checksum_sha256
        (settings.storage_path / "docs/altere.html").write_bytes(
            b"<html><body><p>Contenu substitue</p></body></html>"
        )

        with pytest.raises(ErreurIntegriteDocument):
            extraire_document(document)

        rapport = extraire_documents_appel_offre(session, ao, best_effort=True)

        assert rapport.documents_traites == 0
        assert any("Intégrité compromise" in e for e in rapport.erreurs)
        session.refresh(document)
        assert document.integrite_ok is False
        assert document.checksum_sha256 == reference
        assert document.contenu_extrait is None
        logs = session.exec(select(LogAgent).where(LogAgent.niveau == "error")).all()
        assert any(
            "altere.html" in log.message and log.appel_offre_id == ao.id for log in logs
        )


def test_document_deja_extrait_puis_altere_est_ecarte_de_l_analyse():
    from hermes.agents.krinos import analyzer
    from hermes.agents.krinos.extractor import extraire_documents_appel_offre

    init_db()
    contenu = b"<html><body><p>Clause secrete</p></body></html>"
    with Session(get_engine()) as session:
        document = _ao_et_document(session, "docs/apres.html", contenu, TypeDocument.HTML)
        ao = session.get(AppelOffre, document.appel_offre_id)
        extraire_documents_appel_offre(session, ao)
        session.refresh(document)
        assert "Clause secrete" in analyzer._construire_contexte(session, ao)["documents"]

        (settings.storage_path / "docs/apres.html").write_bytes(contenu + b"<!-- injecte -->")
        extraire_documents_appel_offre(session, ao, best_effort=True)

        session.refresh(document)
        assert document.integrite_ok is False
        assert "Clause secrete" not in analyzer._construire_contexte(session, ao)["documents"]


def test_endpoint_extraction_fichier_altere_409_et_expose_integrite():
    from fastapi.testclient import TestClient

    from hermes.main import app

    init_db()
    with Session(get_engine()) as session:
        document = _ao_et_document(session, "docs/api.html", b"<p>ok</p>", TypeDocument.HTML)
        (settings.storage_path / "docs/api.html").write_bytes(b"<p>modifie</p>")
        document_id, ao_id = document.id, document.appel_offre_id

    with TestClient(app) as client:
        r = client.post(f"/krinos/documents/{document_id}/extraire")
        assert r.status_code == 409
        detail = client.get(f"/appels-offre/{ao_id}").json()

    assert detail["documents_alteres"] == ["docs/api.html"]
    with Session(get_engine()) as session:
        assert session.get(Document, document_id).integrite_ok is False


def test_migration_integrite_ok_idempotente():
    from hermes.db.session import _migrer_colonnes

    init_db()
    with get_engine().begin() as conn:
        _migrer_colonnes(conn)
        _migrer_colonnes(conn)
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info('documents')").fetchall()}
    assert "integrite_ok" in cols

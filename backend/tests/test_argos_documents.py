"""Tests Boucle 3 — liens documents : extraction TED, persistance, état AO."""

from __future__ import annotations

import asyncio
import json

from sqlmodel import Session, select

from hermes.agents.argos import runner
from hermes.agents.argos.base import AOCollecte, Scraper
from hermes.agents.argos.ted import _notice_vers_ao, _tous_les_liens
from hermes.agents.krinos.downloader import liens_documents_ao
from hermes.db.models import AppelOffre, Document, TypeDocument
from hermes.db.session import get_engine, init_db

# --------------------------------------------------------------------------- #
# Extraction des liens TED
# --------------------------------------------------------------------------- #


def test_tous_les_liens_un_par_famille_pdf_en_tete():
    links = {
        "html": {"FRA": "https://ted.europa.eu/fr/notice/x/html"},
        "pdf": {"FRA": "https://ted.europa.eu/fr/notice/x/pdf"},
        "xml": {"FRA": "https://ted.europa.eu/fr/notice/x/xml"},
    }
    assert _tous_les_liens(links) == [
        "https://ted.europa.eu/fr/notice/x/pdf",
        "https://ted.europa.eu/fr/notice/x/html",
        "https://ted.europa.eu/fr/notice/x/xml",
    ]


def test_tous_les_liens_dedoublonne_et_ignore_non_http():
    links = {
        "html": {"FRA": "https://x/html", "ENG": "https://x/html"},  # même URL
        "pdf": {"FRA": "ftp://x/pdf"},  # schéma non http → ignoré
    }
    assert _tous_les_liens(links) == ["https://x/html"]


def test_tous_les_liens_vide_si_pas_de_links():
    assert _tous_les_liens(None) == []
    assert _tous_les_liens({}) == []


def test_notice_vers_ao_remplit_liens_documents():
    notice = {
        "publication-number": "123-2026",
        "notice-title": "Marché de notification",
        "links": {
            "pdf": {"FRA": "https://ted/x/pdf"},
            "html": {"FRA": "https://ted/x/html"},
        },
    }
    ao = _notice_vers_ao(notice)
    assert ao.liens_documents == ["https://ted/x/pdf", "https://ted/x/html"]
    # url_source garde la priorité HTML (page lisible) de `_premier_lien`.
    assert ao.url_source == "https://ted/x/html"


# --------------------------------------------------------------------------- #
# Persistance par le runner
# --------------------------------------------------------------------------- #


def test_runner_persiste_liens_documents_en_json():
    class FauxScraper(Scraper):
        nom = "faux-docs"
        url_base = "https://example.test"

        async def collecter(self, limite: int = 20) -> list[AOCollecte]:
            return [
                AOCollecte(
                    titre="AO avec docs",
                    url_source="https://example.test/avis",
                    liens_documents=["https://example.test/a.pdf", "https://example.test/b.html"],
                )
            ]

    init_db()
    with Session(get_engine()) as session:
        asyncio.run(runner.executer_collecte(FauxScraper(), session))

    with Session(get_engine()) as session:
        ao = session.exec(select(AppelOffre)).first()
        assert ao is not None
        assert json.loads(ao.liens_documents) == [
            "https://example.test/a.pdf",
            "https://example.test/b.html",
        ]


# --------------------------------------------------------------------------- #
# Résolution des liens à télécharger
# --------------------------------------------------------------------------- #


def test_liens_documents_ao_utilise_les_liens_detectes():
    ao = AppelOffre(
        url_source="https://example.test/avis",
        titre="x",
        liens_documents=json.dumps(["https://example.test/a.pdf", "https://example.test/b.html"]),
    )
    assert liens_documents_ao(ao) == [
        "https://example.test/a.pdf",
        "https://example.test/b.html",
    ]


def test_liens_documents_ao_repli_sur_url_source():
    ao = AppelOffre(url_source="https://example.test/avis", titre="x", liens_documents=None)
    assert liens_documents_ao(ao) == ["https://example.test/avis"]


def test_liens_documents_ao_json_corrompu_repli():
    ao = AppelOffre(
        url_source="https://example.test/avis", titre="x", liens_documents="pas du json"
    )
    assert liens_documents_ao(ao) == ["https://example.test/avis"]


# --------------------------------------------------------------------------- #
# État documents exposé par l'API
# --------------------------------------------------------------------------- #


def test_api_expose_etat_documents():
    from fastapi.testclient import TestClient

    from hermes.main import app

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(
            url_source="https://example.test/avis",
            titre="AO documents",
            liens_documents=json.dumps(
                ["https://example.test/a.pdf", "https://example.test/b.html"]
            ),
        )
        session.add(ao)
        session.commit()
        session.refresh(ao)
        # Un seul des deux documents détectés est téléchargé.
        session.add(
            Document(
                appel_offre_id=ao.id,
                nom_fichier="a.pdf",
                chemin_local="appels_offre/1/a.pdf",
                type=TypeDocument.PDF,
                checksum_sha256="abc123",
            )
        )
        session.commit()
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.get(f"/appels-offre/{ao_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["documents_detectes"] == 2
    assert data["documents_telecharges"] == 1
    assert data["documents_manquants"] == 1

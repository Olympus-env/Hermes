"""Test bout en bout (CDC §3.2, phase 10) : collecte → réponse → export PDF.

Enchaîne, par les routes HTTP réelles et sans réseau ni Ollama :

    ARGOS (portail simulé) → KRINOS (téléchargement + extraction + analyse avec
    un faux PYTHIA) → HERMION (rédaction) → validation humaine (PATCH) → export PDF.

Invariant HERMES vérifié ici : le pipeline s'arrête à `en_attente` ; rien n'est
validé ni exporté sans appel humain explicite, même relancé plusieurs fois.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import fitz  # PyMuPDF : fabrique le DCE de fixture et relit le PDF exporté
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes.agents import pythia
from hermes.agents.argos import registry
from hermes.agents.argos.base import AOCollecte, Scraper
from hermes.agents.krinos import downloader
from hermes.config import settings
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    Document,
    LogAgent,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)
from hermes.db.session import get_engine, init_db

_URL_DCE = "https://portail-test.example/dce/cctp.pdf"
_MARQUEUR_DCE = "CCTP maintenance applicative SIRH trois ans"


def _pdf_fixture() -> bytes:
    """Petit DCE PDF généré en mémoire (aucun fichier binaire versionné)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), _MARQUEUR_DCE)
    contenu = doc.tobytes()
    doc.close()
    return contenu


class ScraperPortailTest(Scraper):
    """Portail simulé : un avis, avec un lien vers un DCE servi par fixture."""

    nom = "portail-test"
    url_base = "https://portail-test.example"

    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        return [
            AOCollecte(
                titre="Maintenance applicative du SIRH",
                url_source="https://portail-test.example/avis/26-001",
                reference_externe="PT-26-001",
                emetteur="Mairie de Test",
                objet="Maintenance corrective et évolutive du SIRH",
                type_marche="services",
                date_limite=datetime.now(UTC) + timedelta(days=30),
                liens_documents=[_URL_DCE],
            )
        ]


@pytest.fixture
def faux_environnement(monkeypatch):
    """Isole le flux : un seul portail simulé, DCE local, faux PYTHIA."""
    # ARGOS : seul le portail simulé est enregistré (ni BOAMP ni TED).
    monkeypatch.setattr(registry, "_REGISTRE", {ScraperPortailTest.nom: ScraperPortailTest})

    # KRINOS : le « téléchargement » renvoie le PDF de fixture, sans socket.
    telechargements: list[str] = []

    async def faux_telechargement(url, *, transport=None):
        telechargements.append(url)
        return downloader.ReponseDocument(
            contenu=_pdf_fixture(), content_type="application/pdf", nom_fichier="cctp.pdf"
        )

    monkeypatch.setattr(downloader, "_telecharger_url", faux_telechargement)

    # PYTHIA : faux moteur selon l'appelant (analyse KRINOS / plan / sections HERMION).
    appels = {"analyse": 0, "plan": 0, "section": 0}
    prompts_analyse: list[str] = []

    async def faux_generer(prompt, *, system=None, format_schema=None, format_json=False, **_):
        if format_schema is not None:
            appels["analyse"] += 1
            prompts_analyse.append(prompt)
            charge = {
                "resume": "Maintenance applicative du SIRH d'une mairie sur trois ans.",
                "score": 85,
                "scores_dimensions": {
                    "affinite_metier": 85,
                    "references": 80,
                    "adequation_budget": 80,
                    "capacite_equipe": 80,
                    "calendrier": 80,
                },
                "justification": "Périmètre clair, cœur de métier.",
                "tags": ["maintenance", "sirh", "applicatif"],
                "criteres": "Prix 40 %, valeur technique 60 %",
            }
        elif format_json:
            appels["plan"] += 1
            charge = {
                "sections": [
                    {"titre": "Compréhension du besoin", "brief": "Reformuler le besoin."},
                    {"titre": "Méthodologie", "brief": "Approche proposée."},
                    {"titre": "Moyens", "brief": "Équipe et outils."},
                ]
            }
        else:
            appels["section"] += 1
            return pythia.ReponsePythia(
                texte="## Section\n\nContenu rédigé en français professionnel.\n",
                modele="faux-pythia",
                duree_ms=1,
            )
        return pythia.ReponsePythia(
            texte=json.dumps(charge, ensure_ascii=False), modele="faux-pythia", duree_ms=1
        )

    async def interdit(*_a, **_k):
        raise AssertionError("appel réseau PYTHIA réel interdit en test")

    monkeypatch.setattr(pythia, "generer", faux_generer)
    monkeypatch.setattr(pythia, "_post_json", interdit)

    return {"telechargements": telechargements, "appels": appels, "prompts": prompts_analyse}


def _etat() -> tuple[AppelOffre, list[ReponseHermion]]:
    with Session(get_engine()) as s:
        aos = s.exec(select(AppelOffre)).all()
        assert len(aos) == 1
        ao = aos[0]
        reponses = s.exec(
            select(ReponseHermion).where(ReponseHermion.appel_offre_id == ao.id)
        ).all()
        return ao, list(reponses)


def _agents_journalises() -> set[str]:
    with Session(get_engine()) as s:
        return {log.agent for log in s.exec(select(LogAgent)).all()}


def _aucun_pdf_exporte() -> bool:
    dossier = settings.storage_path / "exports"
    return not dossier.exists() or not list(dossier.glob("*.pdf"))


def test_flux_complet_collecte_reponse_export_pdf(faux_environnement):
    from hermes.main import app

    init_db()
    env = faux_environnement

    with TestClient(app) as client:
        # --- 1. ARGOS : collecte du portail simulé → AO brut ---------------------
        r = client.post("/argos/collecter")
        assert r.status_code == 200
        collecte = r.json()
        assert collecte["succes"] is True
        assert collecte["ao_nouveaux"] == 1
        assert [res["portail"] for res in collecte["resultats"]] == ["portail-test"]

        ao, reponses = _etat()
        assert ao.statut == StatutAO.BRUT
        assert ao.reference_externe == "PT-26-001"
        assert reponses == []
        assert env["telechargements"] == []  # rien avant le passage du pipeline

        # Une seconde collecte ne duplique pas l'avis.
        r = client.post("/argos/collecter")
        assert r.json()["ao_nouveaux"] == 0 and r.json()["ao_dedoublonnes"] == 1

        # --- 2. KRINOS : extraction + analyse (rédaction coupée) → AO analysé ----
        cfg = {"actif": True, "seuil_score": 70, "auto_rediger": False, "max_par_cycle": 5}
        assert client.put("/orchestration/config", json=cfg).status_code == 200

        r = client.post("/orchestration/traiter")
        assert r.status_code == 200
        assert r.json()["ao_analyses"] == 1 and r.json()["ao_rediges"] == 0

        ao, reponses = _etat()
        assert ao.statut == StatutAO.ANALYSE
        assert reponses == []
        assert env["telechargements"] == [_URL_DCE]
        assert env["appels"] == {"analyse": 1, "plan": 0, "section": 0}
        with Session(get_engine()) as s:
            documents = s.exec(select(Document).where(Document.appel_offre_id == ao.id)).all()
            assert len(documents) == 1
            # Extraction : le texte du PDF est remonté jusqu'au prompt d'analyse.
            assert _MARQUEUR_DCE in (documents[0].contenu_extrait or "")
            assert _MARQUEUR_DCE in env["prompts"][0]
            analyse = s.exec(
                select(AnalyseKrinos).where(AnalyseKrinos.appel_offre_id == ao.id)
            ).one()
            assert 70 <= analyse.score <= 100
            assert set(json.loads(analyse.tags)) >= {"maintenance", "sirh"}
        assert _aucun_pdf_exporte()

        # --- 3. HERMION : rédaction → réponse v1 en attente de validation --------
        cfg["auto_rediger"] = True
        assert client.put("/orchestration/config", json=cfg).status_code == 200
        r = client.post("/orchestration/traiter")
        assert r.status_code == 200
        assert r.json()["ao_rediges"] == 1 and r.json()["ao_echecs"] == 0

        ao, reponses = _etat()
        assert ao.statut == StatutAO.EN_REDACTION
        assert len(reponses) == 1
        reponse = reponses[0]
        assert reponse.version == 1
        assert reponse.statut == StatutReponse.EN_ATTENTE
        assert reponse.chemin_export is None
        assert env["appels"]["plan"] == 1 and env["appels"]["section"] == 3

        # --- 4. Invariant : relancer le pipeline ne valide ni n'exporte rien -----
        for _ in range(2):
            assert client.post("/argos/collecter").status_code == 200
            r = client.post("/orchestration/traiter")
            assert r.status_code == 200
            assert r.json()["ao_analyses"] == 0 and r.json()["ao_rediges"] == 0
        ao, reponses = _etat()
        assert ao.statut == StatutAO.EN_REDACTION
        assert [(x.id, x.statut, x.chemin_export) for x in reponses] == [
            (reponse.id, StatutReponse.EN_ATTENTE, None)
        ]
        assert env["appels"] == {"analyse": 1, "plan": 1, "section": 3}  # pas de ré-appel
        assert _aucun_pdf_exporte()
        # L'export d'une réponse non validée est refusé.
        assert client.post(f"/hermion/reponses/{reponse.id}/exporter").status_code == 409
        assert client.get(f"/hermion/reponses/{reponse.id}/export").status_code == 404

        # --- 5. Validation humaine explicite, puis export PDF --------------------
        r = client.patch(
            f"/hermion/reponses/{reponse.id}/statut", json={"statut": "validee"}
        )
        assert r.status_code == 200 and r.json()["statut"] == "validee"
        ao, reponses = _etat()
        assert ao.statut == StatutAO.REPONDU
        assert reponses[0].statut == StatutReponse.VALIDEE
        assert _aucun_pdf_exporte()  # validée ≠ exportée

        r = client.post(f"/hermion/reponses/{reponse.id}/exporter")
        assert r.status_code == 200 and r.json()["statut"] == "exportee"

        dl = client.get(f"/hermion/reponses/{reponse.id}/export")
        assert dl.status_code == 200
        assert dl.headers["content-type"] == "application/pdf"
        pdf = fitz.open(stream=dl.content, filetype="pdf")
        texte = "".join(page.get_text() for page in pdf)
        pdf.close()
        assert "Maintenance applicative du SIRH" in texte
        assert "Méthodologie" in texte

        ao, reponses = _etat()
        assert ao.statut == StatutAO.REPONDU
        assert reponses[0].statut == StatutReponse.EXPORTEE

    # --- 6. Journal MNEMOSYNE alimenté par chaque agent -------------------------
    assert {"ARGOS", "KRINOS", "HERMION"} <= _agents_journalises()

"""Tests workflow HERMION — onboarding étendu + dérivation IA (tâche V1 #3)."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.agents import pythia
from hermes.agents.hermion import workflow as wf
from hermes.db.models import AnalyseKrinos, AppelOffre, StatutAO
from hermes.db.session import get_engine, init_db


def _faux_reponse(texte: str) -> pythia.ReponsePythia:
    return pythia.ReponsePythia(texte=texte, modele="mistral:7b", duree_ms=5)


def _ao_avec_analyse(session: Session) -> int:
    ao = AppelOffre(
        titre="Maintenance applicative SI metier",
        emetteur="Mairie de Test",
        objet="Maintenance corrective et evolutive",
        url_source="https://example.test/ao-wf",
        statut=StatutAO.A_REPONDRE,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    session.add(
        AnalyseKrinos(
            appel_offre_id=ao.id,  # type: ignore[arg-type]
            resume="AO maintenance 3 ans.",
            score=72.0,
            justification_score="Perimetre clair.",
            tags=json.dumps(["maintenance"], ensure_ascii=False),
        )
    )
    session.commit()
    return ao.id  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Persistance
# --------------------------------------------------------------------------- #


def test_charger_workflow_absent_retourne_none():
    init_db()
    with Session(get_engine()) as session:
        assert wf.charger_workflow(session) is None


def test_enregistrer_puis_charger_normalise():
    init_db()
    with Session(get_engine()) as session:
        enregistre = wf.enregistrer_workflow(
            session,
            wf.WorkflowReponse(
                sections=(
                    wf.SectionWorkflow(titre="  Contexte  ", brief=" Reformuler. "),
                    wf.SectionWorkflow(titre="", brief="section vide ignoree"),
                    wf.SectionWorkflow(titre="Methodo", longueur_cible=999999),
                ),
                consignes_globales="  Ton sobre.  ",
                source="manuel",
            ),
        )
    # Section sans titre supprimée, trims appliqués, longueur clampée.
    assert [s.titre for s in enregistre.sections] == ["Contexte", "Methodo"]
    assert enregistre.sections[0].brief == "Reformuler."
    assert enregistre.sections[1].longueur_cible == wf.MAX_LONGUEUR_CIBLE
    assert enregistre.consignes_globales == "Ton sobre."

    with Session(get_engine()) as session:
        recharge = wf.charger_workflow(session)
    assert recharge is not None
    assert recharge.configure
    assert [s.titre for s in recharge.sections] == ["Contexte", "Methodo"]


def test_charger_workflow_sans_section_retourne_none():
    init_db()
    with Session(get_engine()) as session:
        wf.enregistrer_workflow(
            session, wf.WorkflowReponse(sections=(), consignes_globales="x")
        )
    with Session(get_engine()) as session:
        # Pas de section exploitable → None (HERMION retombe sur plan dynamique).
        assert wf.charger_workflow(session) is None


# --------------------------------------------------------------------------- #
# Dérivation IA
# --------------------------------------------------------------------------- #


def test_deriver_workflow_via_pythia(monkeypatch):
    payload = {
        "sections": [
            {"titre": "Comprehension du besoin", "brief": "Reformuler.", "longueur_cible": 250},
            {"titre": "Methodologie", "brief": "Approche.", "longueur_cible": None},
            {"titre": "References", "brief": "Cas similaires."},
        ],
        "consignes_globales": "Ton factuel, vouvoiement.",
    }

    async def fake_generer(prompt, *, system=None, format_json=False, **_):
        assert format_json is True
        return _faux_reponse(json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(wf.pythia, "generer", fake_generer)

    resultat = asyncio.run(
        wf.deriver_workflow(mode="exemples", contenu="Voici une reponse passee...")
    )
    assert resultat.source == "ia_exemples"
    assert [s.titre for s in resultat.sections] == [
        "Comprehension du besoin",
        "Methodologie",
        "References",
    ]
    assert resultat.sections[0].longueur_cible == 250
    assert resultat.consignes_globales == "Ton factuel, vouvoiement."


def test_deriver_workflow_contenu_vide_leve_erreur():
    with pytest.raises(pythia.ErreurPythia):
        asyncio.run(wf.deriver_workflow(mode="workflow", contenu="   "))


def test_deriver_workflow_sans_section_leve_erreur(monkeypatch):
    async def fake_generer(*a, **k):
        return _faux_reponse(json.dumps({"sections": []}))

    monkeypatch.setattr(wf.pythia, "generer", fake_generer)
    with pytest.raises(pythia.ErreurPythia):
        asyncio.run(wf.deriver_workflow(mode="workflow", contenu="bla"))


# --------------------------------------------------------------------------- #
# Intégration writer : le workflow utilisateur remplace le plan dynamique
# --------------------------------------------------------------------------- #


def test_writer_utilise_workflow_configure(monkeypatch):
    from hermes.agents.hermion import writer

    appels: list[bool] = []

    async def fake_generer(prompt, *, system=None, format_json=False, **_):
        appels.append(format_json)
        if format_json:
            raise AssertionError("Aucun appel plan attendu quand workflow configuré")
        return _faux_reponse("## Section\n\nContenu professionnel en francais.\n")

    monkeypatch.setattr(writer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao_id = _ao_avec_analyse(session)
        wf.enregistrer_workflow(
            session,
            wf.WorkflowReponse(
                sections=(
                    wf.SectionWorkflow(titre="Contexte", brief="Le besoin."),
                    wf.SectionWorkflow(titre="Offre", brief="Notre proposition."),
                ),
                consignes_globales="Vouvoiement.",
                source="manuel",
            ),
        )

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        resultat = asyncio.run(writer.rediger_reponse(session, ao))

    # Aucun appel JSON (plan) — uniquement 2 rédactions de section.
    assert appels == [False, False]
    assert [s["titre"] for s in resultat.plan] == ["Contexte", "Offre"]
    meta = json.loads(resultat.reponse.workflow_utilise or "{}")
    assert "workflow_utilisateur" in meta["origine"]


def test_endpoints_workflow_crud_et_deriver(monkeypatch):
    from hermes.agents.hermion import workflow as wfmod
    from hermes.main import app

    async def fake_generer(prompt, *, system=None, format_json=False, **_):
        return _faux_reponse(
            json.dumps(
                {
                    "sections": [
                        {"titre": "Intro", "brief": "Ouvrir."},
                        {"titre": "Coeur", "brief": "Repondre."},
                        {"titre": "Conclusion", "brief": "Clore."},
                    ],
                    "consignes_globales": "Sobre.",
                }
            )
        )

    monkeypatch.setattr(wfmod.pythia, "generer", fake_generer)
    init_db()

    with TestClient(app) as client:
        # Au départ : non configuré.
        r = client.get("/hermion/workflow")
        assert r.status_code == 200 and r.json()["configure"] is False

        # Dérivation IA (non persistée).
        r = client.post(
            "/hermion/workflow/deriver",
            json={"mode": "exemples", "contenu": "reponse passee"},
        )
        assert r.status_code == 200
        derive = r.json()
        assert derive["source"] == "ia_exemples"
        assert len(derive["sections"]) == 3

        # Toujours non configuré tant que pas de PUT.
        assert client.get("/hermion/workflow").json()["configure"] is False

        # Correction manuelle + persistance.
        derive["sections"] = derive["sections"][:2]
        r = client.put(
            "/hermion/workflow",
            json={
                "consignes_globales": "Vouvoiement.",
                "sections": derive["sections"],
                "source": "manuel",
            },
        )
        assert r.status_code == 200

        r = client.get("/hermion/workflow")
        data = r.json()
        assert data["configure"] is True
        assert len(data["sections"]) == 2
        assert data["consignes_globales"] == "Vouvoiement."


def test_endpoint_deriver_502_si_pythia_down(monkeypatch):
    from hermes.agents.hermion import workflow as wfmod
    from hermes.main import app

    async def fake_generer(*a, **k):
        raise pythia.ErreurPythia("ollama injoignable")

    monkeypatch.setattr(wfmod.pythia, "generer", fake_generer)
    init_db()
    with TestClient(app) as client:
        r = client.post(
            "/hermion/workflow/deriver",
            json={"mode": "workflow", "contenu": "blabla"},
        )
    assert r.status_code == 502

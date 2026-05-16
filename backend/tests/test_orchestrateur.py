"""Tests orchestrateur — pipeline autonome ARGOS→KRINOS→HERMION (tâche V1 #2)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes.agents import orchestrateur as orch
from hermes.agents.krinos import ErreurAnalyseKrinos
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)
from hermes.db.session import get_engine, init_db


def _ao_brut(session: Session, titre: str = "AO test") -> int:
    ao = AppelOffre(
        titre=titre,
        url_source=f"https://example.test/{titre.replace(' ', '-')}",
        statut=StatutAO.BRUT,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    return ao.id  # type: ignore[return-value]


async def _noop_docs(session, ao):
    return []


def _fake_analyser(score: float):
    async def analyser(session, ao, *, forcer=False):
        analyse = AnalyseKrinos(
            appel_offre_id=ao.id,
            resume="Résumé.",
            score=score,
            justification_score="—",
            tags=json.dumps(["test"]),
        )
        session.add(analyse)
        if ao.statut == StatutAO.BRUT:
            ao.statut = StatutAO.ANALYSE
            session.add(ao)
        session.commit()
        session.refresh(analyse)
        return SimpleNamespace(analyse=analyse, nouveau=True)

    return analyser


async def _fake_rediger(session, ao, *, profil=None, consignes_supplementaires=None):
    reponse = ReponseHermion(
        appel_offre_id=ao.id,
        version=1,
        contenu="# Réponse\n\nContenu.",
        statut=StatutReponse.EN_ATTENTE,
    )
    session.add(reponse)
    ao.statut = StatutAO.EN_REDACTION
    session.add(ao)
    session.commit()
    session.refresh(reponse)
    return SimpleNamespace(reponse=reponse, plan=[])


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_config_defaut_si_absente():
    init_db()
    with Session(get_engine()) as s:
        cfg = orch.charger_config(s)
    assert cfg.actif is True
    assert cfg.seuil_score == 70.0
    assert cfg.auto_rediger is True


def test_config_round_trip_et_normalisation():
    init_db()
    with Session(get_engine()) as s:
        orch.enregistrer_config(
            s,
            orch.ConfigOrchestration(
                actif=False, seuil_score=250.0, auto_rediger=False, max_par_cycle=999
            ),
        )
    with Session(get_engine()) as s:
        cfg = orch.charger_config(s)
    assert cfg.actif is False
    assert cfg.seuil_score == 100.0  # clampé
    assert cfg.max_par_cycle == orch.MAX_PAR_CYCLE_PLAFOND  # clampé
    assert cfg.auto_rediger is False


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


def test_pipeline_inactif_ne_fait_rien(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)
        orch.enregistrer_config(s, orch.ConfigOrchestration(actif=False))

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))
    assert rapport.actif is False
    assert rapport.ao_analyses == 0
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).statut == StatutAO.BRUT


def test_pipeline_complet_analyse_puis_redige(monkeypatch):
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(85.0))
    monkeypatch.setattr(orch, "rediger_reponse", _fake_rediger)

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)
        orch.enregistrer_config(s, orch.ConfigOrchestration(seuil_score=70.0))

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))

    assert rapport.ao_analyses == 1
    assert rapport.ao_rediges == 1
    assert rapport.ao_echecs == 0
    with Session(get_engine()) as s:
        ao = s.get(AppelOffre, ao_id)
        assert ao.statut == StatutAO.EN_REDACTION
        reponse = s.exec(
            select(ReponseHermion).where(ReponseHermion.appel_offre_id == ao_id)
        ).first()
        assert reponse is not None
        assert reponse.statut == StatutReponse.EN_ATTENTE


def test_pipeline_sous_seuil_reste_en_analyse(monkeypatch):
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(40.0))
    monkeypatch.setattr(orch, "rediger_reponse", _fake_rediger)

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)
        orch.enregistrer_config(s, orch.ConfigOrchestration(seuil_score=70.0))

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))

    assert rapport.ao_analyses == 1
    assert rapport.ao_rediges == 0
    assert rapport.ao_sous_seuil == 1
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).statut == StatutAO.ANALYSE


def test_pipeline_auto_rediger_desactive(monkeypatch):
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(95.0))
    monkeypatch.setattr(orch, "rediger_reponse", _fake_rediger)

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)
        orch.enregistrer_config(
            s, orch.ConfigOrchestration(seuil_score=70.0, auto_rediger=False)
        )

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))

    assert rapport.ao_analyses == 1
    assert rapport.ao_rediges == 0
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).statut == StatutAO.ANALYSE


def test_pipeline_idempotent_pas_de_double_reponse(monkeypatch):
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(85.0))
    monkeypatch.setattr(orch, "rediger_reponse", _fake_rediger)

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)

    with Session(get_engine()) as s:
        asyncio.run(orch.traiter_pipeline(s))
    with Session(get_engine()) as s:
        rapport2 = asyncio.run(orch.traiter_pipeline(s))

    assert rapport2.ao_rediges == 0  # déjà une réponse
    with Session(get_engine()) as s:
        reponses = s.exec(
            select(ReponseHermion).where(ReponseHermion.appel_offre_id == ao_id)
        ).all()
        assert len(reponses) == 1


def test_pipeline_resiste_a_echec_analyse(monkeypatch):
    async def analyser_ko(session, ao, *, forcer=False):
        raise ErreurAnalyseKrinos("PYTHIA injoignable")

    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", analyser_ko)

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))  # ne lève pas

    assert rapport.ao_echecs == 1
    assert rapport.ao_analyses == 0
    with Session(get_engine()) as s:
        # AO laissé en BRUT → reprenable au prochain cycle.
        assert s.get(AppelOffre, ao_id).statut == StatutAO.BRUT


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


def test_endpoints_config_et_traiter(monkeypatch):
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(88.0))
    monkeypatch.setattr(orch, "rediger_reponse", _fake_rediger)

    from hermes.main import app

    init_db()
    with Session(get_engine()) as s:
        _ao_brut(s, "AO via API")

    with TestClient(app) as client:
        r = client.get("/orchestration/config")
        assert r.status_code == 200 and r.json()["seuil_score"] == 70.0

        r = client.put(
            "/orchestration/config",
            json={
                "actif": True,
                "seuil_score": 60,
                "auto_rediger": True,
                "max_par_cycle": 3,
            },
        )
        assert r.status_code == 200 and r.json()["seuil_score"] == 60.0

        r = client.post("/orchestration/traiter")
        assert r.status_code == 200
        data = r.json()
        assert data["ao_analyses"] == 1
        assert data["ao_rediges"] == 1

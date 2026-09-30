"""Tests orchestrateur — pipeline autonome ARGOS→KRINOS→HERMION (tâche V1 #2)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes.agents import orchestrateur as orch
from hermes.agents.hermion import ErreurRedactionHermion
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


def test_pipeline_analyse_leve_le_marquage_hors_profil_laya(monkeypatch):
    """Pré-tri coupé après marquage : l'AO est analysé et perd son badge « Hors profil »."""
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(40.0))

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)
        ao = s.get(AppelOffre, ao_id)
        ao.hors_profil_laya = True
        s.add(ao)
        s.commit()
        orch.enregistrer_config(s, orch.ConfigOrchestration(seuil_score=70.0))

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))

    assert rapport.ao_analyses == 1
    with Session(get_engine()) as s:
        ao = s.get(AppelOffre, ao_id)
        assert ao.statut == StatutAO.ANALYSE
        assert ao.hors_profil_laya is False


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


def test_pipeline_reessaie_redaction_apres_echec(monkeypatch):
    async def rediger_ko(session, ao, *, profil=None, consignes_supplementaires=None):
        raise ErreurRedactionHermion("PYTHIA indisponible")

    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(90.0))
    monkeypatch.setattr(orch, "rediger_reponse", rediger_ko)

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))

    assert rapport.ao_echecs == 1
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).statut == StatutAO.ANALYSE

    monkeypatch.setattr(orch, "rediger_reponse", _fake_rediger)
    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))

    assert rapport.ao_rediges == 1
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).statut == StatutAO.EN_REDACTION


# --------------------------------------------------------------------------- #
# Expiration automatique
# --------------------------------------------------------------------------- #

_REF = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)  # « maintenant » de référence


def _ao(session: Session, statut: StatutAO, date_limite: datetime | None) -> int:
    ao = AppelOffre(
        titre=f"AO {statut.value}",
        url_source=f"https://example.test/{statut.value}-{date_limite}",
        statut=statut,
        date_limite=date_limite,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    return ao.id  # type: ignore[return-value]


def test_expire_les_ao_perimables_depasses():
    init_db()
    hier = _REF - timedelta(days=1)
    with Session(get_engine()) as s:
        ids = {
            st: _ao(s, st, hier)
            for st in (StatutAO.BRUT, StatutAO.ANALYSE, StatutAO.A_REPONDRE)
        }

    with Session(get_engine()) as s:
        n = orch.expirer_ao_depasses(s, maintenant=_REF)
    assert n == 3

    with Session(get_engine()) as s:
        for ao_id in ids.values():
            assert s.get(AppelOffre, ao_id).statut == StatutAO.EXPIRE


def test_preserve_les_statuts_engages_et_finaux():
    init_db()
    hier = _REF - timedelta(days=1)
    with Session(get_engine()) as s:
        ids = {
            st: _ao(s, st, hier)
            for st in (StatutAO.EN_REDACTION, StatutAO.REPONDU, StatutAO.REJETE)
        }

    with Session(get_engine()) as s:
        assert orch.expirer_ao_depasses(s, maintenant=_REF) == 0

    with Session(get_engine()) as s:
        for st, ao_id in ids.items():
            assert s.get(AppelOffre, ao_id).statut == st


def test_actif_le_jour_meme_et_sans_date_limite():
    init_db()
    with Session(get_engine()) as s:
        aujourdhui = _ao(s, StatutAO.BRUT, _REF.replace(hour=0, minute=0))
        futur = _ao(s, StatutAO.BRUT, _REF + timedelta(days=3))
        sans_date = _ao(s, StatutAO.BRUT, None)

    with Session(get_engine()) as s:
        assert orch.expirer_ao_depasses(s, maintenant=_REF) == 0

    with Session(get_engine()) as s:
        for ao_id in (aujourdhui, futur, sans_date):
            assert s.get(AppelOffre, ao_id).statut == StatutAO.BRUT


def test_pipeline_expire_meme_si_inactif():
    init_db()
    # `traiter_pipeline` utilise le vrai `now()` : date limite franchement
    # ancienne pour rester déterministe quelle que soit l'horloge.
    ancienne = datetime(2020, 1, 1, tzinfo=UTC)
    with Session(get_engine()) as s:
        ao_id = _ao(s, StatutAO.BRUT, ancienne)
        orch.enregistrer_config(s, orch.ConfigOrchestration(actif=False))

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))
    assert rapport.actif is False

    with Session(get_engine()) as s:
        # L'expiration tourne même autonomie coupée.
        assert s.get(AppelOffre, ao_id).statut == StatutAO.EXPIRE


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


def test_endpoint_traiter_refuse_limite_negative():
    from hermes.main import app

    init_db()
    with TestClient(app) as client:
        r = client.post("/orchestration/traiter?limite=-1")
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Verrou global, reprise A_REPONDRE, scheduler (issue #13)
# --------------------------------------------------------------------------- #


def test_deux_pipelines_simultanes_un_seul_traitement_par_ao(monkeypatch):
    appels: list[int] = []

    async def analyser_lent(session, ao, *, forcer=False):
        appels.append(ao.id)
        await asyncio.sleep(0.05)  # laisse l'autre pipeline s'intercaler
        return await _fake_analyser(50.0)(session, ao)

    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", analyser_lent)

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)

    async def deux():
        with Session(get_engine()) as s1, Session(get_engine()) as s2:
            return await asyncio.gather(
                orch.traiter_pipeline(s1), orch.traiter_pipeline(s2)
            )

    r1, r2 = asyncio.run(deux())
    assert appels == [ao_id]
    assert r1.ao_analyses + r2.ao_analyses == 1


def test_traiter_renvoie_409_si_pipeline_en_cours(monkeypatch):
    import hermes.api.orchestration as api_orch
    from hermes.main import app

    monkeypatch.setattr(api_orch, "pipeline_en_cours", lambda: True)
    init_db()
    with TestClient(app) as client:
        assert client.post("/orchestration/traiter").status_code == 409


def test_ao_a_repondre_orphelin_repris(monkeypatch):
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(85.0))
    monkeypatch.setattr(orch, "rediger_reponse", _fake_rediger)

    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao_brut(s)
        ao = s.get(AppelOffre, ao_id)
        ao.statut = StatutAO.A_REPONDRE  # process arrêté pendant la rédaction
        s.add(ao)
        s.add(
            AnalyseKrinos(
                appel_offre_id=ao_id,
                resume="r",
                score=90.0,
                justification_score="—",
                tags="[]",
            )
        )
        s.commit()

    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))
    assert rapport.ao_rediges == 1
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).statut == StatutAO.EN_REDACTION


def test_synchroniser_jobs_ne_relance_pas_les_jobs_existants():
    from hermes import onboarding
    from hermes.agents.argos.scheduler import ArgosScheduler

    init_db()
    with Session(get_engine()) as s:
        onboarding.marquer_termine(s)

    async def scenario():
        sched = ArgosScheduler()
        sched.demarrer()
        try:
            jobs = sched._sched.get_jobs()
            assert jobs, "au moins un job ARGOS attendu"
            job = jobs[0]
            futur = datetime.now(UTC) + timedelta(minutes=30)
            sched._sched.modify_job(job.id, next_run_time=futur)
            sched.synchroniser_jobs()
            assert sched._sched.get_job(job.id).next_run_time == futur
        finally:
            sched.arreter()

    asyncio.run(scenario())

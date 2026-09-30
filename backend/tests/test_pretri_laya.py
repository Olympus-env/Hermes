"""Tests du pré-tri de pertinence Laya avant KRINOS (issues #45 et #56).

Aucun modèle ni réseau : moteur simulé (`tests/laya_faux.py`).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.agents import orchestrateur as orch
from hermes.agents.krinos import laya
from hermes.config import settings
from hermes.db.models import AppelOffre, Portail, StatutAO, TypePortail
from hermes.db.session import get_engine, init_db
from tests.test_orchestrateur import _fake_analyser, _noop_docs

from .laya_faux import MoteurSimule


@pytest.fixture(autouse=True)
def _laya_actif(monkeypatch):
    monkeypatch.setattr(settings, "laya_actif", True)
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "_documents_best_effort", _noop_docs)


def _ao(s: Session, type_portail: TypePortail | None = TypePortail.PUBLIC) -> int:
    portail_id = None
    if type_portail is not None:
        p = Portail(nom=f"P-{type_portail}", url_base="https://p.example.test", type=type_portail)
        s.add(p)
        s.commit()
        s.refresh(p)
        portail_id = p.id
    ao = AppelOffre(
        titre="Travaux de voirie",
        url_source="https://p.example.test/1",
        statut=StatutAO.BRUT,
        portail_id=portail_id,
    )
    s.add(ao)
    s.commit()
    s.refresh(ao)
    return ao.id  # type: ignore[return-value]


def _lancer(monkeypatch, pertinence, moteur=None, **kw):
    moteur = moteur or MoteurSimule(pertinence=pertinence, **kw)
    monkeypatch.setattr(laya, "_moteur", moteur)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(50.0))
    with Session(get_engine()) as s:
        rapport = asyncio.run(orch.traiter_pipeline(s))
    return rapport, moteur


def _activer_pretri(seuil=0.3):
    with Session(get_engine()) as s:
        laya.enregistrer_pretri(s, True, seuil)


def test_desactive_par_defaut(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao(s)
    rapport, moteur = _lancer(monkeypatch, 0.0)
    assert moteur.appels == []
    assert rapport.ao_analyses == 1
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).hors_profil_laya is False


def test_hors_profil_non_analyse_mais_conserve(monkeypatch):
    init_db()
    _activer_pretri(0.3)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
    rapport, moteur = _lancer(monkeypatch, 0.1)
    assert len(moteur.appels) == 1
    assert list(moteur.appels[0][1]) == ["pertinence"]  # une seule question
    assert rapport.ao_analyses == 0
    with Session(get_engine()) as s:
        ao = s.get(AppelOffre, ao_id)
        assert ao.hors_profil_laya is True
        assert ao.pertinence_laya == pytest.approx(0.1)
        assert ao.statut == StatutAO.BRUT  # ni supprimé ni rejeté
    # Cycle suivant : pas de nouvelle inférence, toujours pas analysé.
    rapport, _ = _lancer(monkeypatch, 0.1, moteur)
    assert len(moteur.appels) == 1
    assert rapport.ao_analyses == 0


def test_pertinent_est_analyse(monkeypatch):
    init_db()
    _activer_pretri(0.3)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
    rapport, _ = _lancer(monkeypatch, 0.8)
    assert rapport.ao_analyses == 1
    with Session(get_engine()) as s:
        ao = s.get(AppelOffre, ao_id)
        assert ao.hors_profil_laya is False
        assert ao.pertinence_laya == pytest.approx(0.8)


@pytest.mark.parametrize("type_portail", [TypePortail.PUBLIC, TypePortail.PRIVE, None])
def test_tous_les_portails_sont_tries(monkeypatch, type_portail):
    """Laya est local : les portails privés et les AO sans portail sont triés aussi (#56)."""
    init_db()
    _activer_pretri(0.9)
    with Session(get_engine()) as s:
        ao_id = _ao(s, type_portail)
    rapport, moteur = _lancer(monkeypatch, 0.1)
    assert len(moteur.appels) == 1
    assert rapport.ao_analyses == 0
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).hors_profil_laya is True


def test_panne_laya_analyse_normale(monkeypatch):
    init_db()
    _activer_pretri(0.9)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
    rapport, _ = _lancer(monkeypatch, 0.0, MoteurSimule(erreur=RuntimeError("boum")))
    assert rapport.ao_analyses == 1
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).hors_profil_laya is False


def test_modele_absent_analyse_normale(monkeypatch):
    """Pré-tri voulu mais poids non installés : pas de pré-tri, analyse normale."""
    init_db()
    _activer_pretri(0.9)
    with Session(get_engine()) as s:
        _ao(s)
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(50.0))
    with Session(get_engine()) as s:  # `laya._moteur` est None : aucun modèle sur disque
        rapport = asyncio.run(orch.traiter_pipeline(s))
    assert rapport.ao_analyses == 1


def test_forcer_analyse_leve_le_marquage_et_reglage_api(monkeypatch):
    from hermes.api import krinos as api_krinos
    from hermes.main import app

    init_db()
    client = TestClient(app)
    assert client.get("/krinos/laya").json()["pretri_actif"] is False
    r = client.put("/krinos/laya/pretri", json={"pretri_actif": True, "pretri_seuil": 0.4})
    assert r.json()["pretri_actif"] is True
    assert r.json()["pretri_seuil"] == 0.4
    r = client.put("/krinos/laya/pretri", json={"pretri_actif": True, "pretri_seuil": 2})
    assert r.status_code == 422

    with Session(get_engine()) as s:
        ao_id = _ao(s)
        ao = s.get(AppelOffre, ao_id)
        ao.hors_profil_laya = True
        s.add(ao)
        s.commit()
    assert client.get(f"/appels-offre/{ao_id}").json()["hors_profil_laya"] is True

    async def faux_analyser(session, ao, forcer=False):
        raise api_krinos.ErreurAnalyseKrinos("PYTHIA absent")

    async def faux_extraire(*a, **k):
        return SimpleNamespace(
            documents_traites=0, erreurs=[], avertissements=[], caracteres_extraits=0
        )

    monkeypatch.setattr(api_krinos, "analyser_ao", faux_analyser)
    monkeypatch.setattr(api_krinos, "extraire_documents_appel_offre_async", faux_extraire)
    client.post(f"/krinos/appels-offre/{ao_id}/analyser", json={"forcer": True})
    assert client.get(f"/appels-offre/{ao_id}").json()["hors_profil_laya"] is False


def test_marquage_non_bloquant_si_pretri_desactive(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao(s)
        ao = s.get(AppelOffre, ao_id)
        ao.hors_profil_laya = True
        ao.pertinence_laya = 0.05
        s.add(ao)
        s.commit()
    rapport, moteur = _lancer(monkeypatch, 0.0)  # pré-tri désactivé
    assert moteur.appels == []
    assert rapport.ao_analyses == 1


def test_ao_deja_evalue_pas_reevalue(monkeypatch):
    init_db()
    _activer_pretri(0.3)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
        ao = s.get(AppelOffre, ao_id)
        ao.pertinence_laya = 0.05  # p. ex. analyse forcée puis échec
        s.add(ao)
        s.commit()
    rapport, moteur = _lancer(monkeypatch, 0.0)
    assert moteur.appels == []
    assert rapport.ao_analyses == 1


def test_state_pretri_contient_budget_et_date_limite(monkeypatch):
    from datetime import UTC, datetime

    init_db()
    _activer_pretri(0.3)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
        ao = s.get(AppelOffre, ao_id)
        ao.budget_estime = 120000.0
        ao.date_limite = datetime(2026, 12, 1, tzinfo=UTC)
        s.add(ao)
        s.commit()
    _, moteur = _lancer(monkeypatch, 0.8)
    etat = moteur.appels[0][0]
    assert "120000" in etat and "Date limite : 2026-12-01" in etat

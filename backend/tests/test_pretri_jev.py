"""Tests du pré-tri de pertinence Jev avant KRINOS (issue #45).

Aucun appel réseau : transport httpx simulé (`jev._transport`).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlmodel import Session

from hermes.agents import orchestrateur as orch
from hermes.agents.krinos import jev
from hermes.config import settings
from hermes.db.models import AppelOffre, Portail, StatutAO, TypePortail
from hermes.db.session import get_engine, init_db
from tests.test_orchestrateur import _fake_analyser, _noop_docs


@pytest.fixture(autouse=True)
def _jev_isole(monkeypatch):
    monkeypatch.setattr(settings, "jev_actif", True)
    monkeypatch.setattr(settings, "jev_api_key", SecretStr("cle-de-test"))
    monkeypatch.setattr(settings, "jev_budget_tokens_mois", 2_000_000)
    monkeypatch.setattr(jev, "_transport", None)
    monkeypatch.setattr(orch, "telecharger_documents_ao", _noop_docs)
    monkeypatch.setattr(orch, "_documents_best_effort", _noop_docs)

    async def pas_de_sommeil(_):
        return None

    monkeypatch.setattr(jev, "_dormir", pas_de_sommeil)


def _transport(pertinence: float, appels: list, statut: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        appels.append(json.loads(request.content))
        if statut != 200:
            return httpx.Response(statut)
        return httpx.Response(
            200,
            json={
                "answers": {"pertinence": {"type": "noul", "noul": pertinence}},
                "usage": {"input_tokens": 300, "output_tokens": 20},
            },
        )

    return httpx.MockTransport(handler)


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


def _lancer(monkeypatch, pertinence, appels, **kw):
    monkeypatch.setattr(jev, "_transport", _transport(pertinence, appels, **kw))
    monkeypatch.setattr(orch, "analyser_ao", _fake_analyser(50.0))
    with Session(get_engine()) as s:
        return asyncio.run(orch.traiter_pipeline(s))


def _activer_pretri(seuil=0.3):
    with Session(get_engine()) as s:
        jev.enregistrer_pretri(s, True, seuil)


def test_desactive_par_defaut(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao(s)
    appels: list = []
    rapport = _lancer(monkeypatch, 0.0, appels)
    assert appels == []
    assert rapport.ao_analyses == 1
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).hors_profil_jev is False


def test_hors_profil_non_analyse_mais_conserve(monkeypatch):
    init_db()
    _activer_pretri(0.3)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
    appels: list = []
    rapport = _lancer(monkeypatch, 0.1, appels)
    assert len(appels) == 1
    assert list(appels[0]["questions"]) == ["pertinence"]  # une seule question
    assert rapport.ao_analyses == 0
    with Session(get_engine()) as s:
        ao = s.get(AppelOffre, ao_id)
        assert ao.hors_profil_jev is True
        assert ao.pertinence_jev == pytest.approx(0.1)
        assert ao.statut == StatutAO.BRUT  # ni supprimé ni rejeté
        assert jev.tokens_consommes(s) > 0  # budget partagé
    # Cycle suivant : pas de nouvel appel Jev, toujours pas analysé.
    rapport = _lancer(monkeypatch, 0.1, appels)
    assert len(appels) == 1
    assert rapport.ao_analyses == 0


def test_pertinent_est_analyse(monkeypatch):
    init_db()
    _activer_pretri(0.3)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
    appels: list = []
    rapport = _lancer(monkeypatch, 0.8, appels)
    assert rapport.ao_analyses == 1
    with Session(get_engine()) as s:
        ao = s.get(AppelOffre, ao_id)
        assert ao.hors_profil_jev is False
        assert ao.pertinence_jev == pytest.approx(0.8)


@pytest.mark.parametrize("type_portail", [TypePortail.PRIVE, None])
def test_portail_prive_ou_absent_jamais_envoye(monkeypatch, type_portail):
    init_db()
    _activer_pretri(0.9)
    with Session(get_engine()) as s:
        _ao(s, type_portail)
    appels: list = []
    rapport = _lancer(monkeypatch, 0.0, appels)
    assert appels == []
    assert rapport.ao_analyses == 1


def test_panne_jev_analyse_normale(monkeypatch):
    init_db()
    _activer_pretri(0.9)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
    appels: list = []
    rapport = _lancer(monkeypatch, 0.0, appels, statut=401)
    assert rapport.ao_analyses == 1
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).hors_profil_jev is False


def test_budget_epuise_analyse_normale(monkeypatch):
    init_db()
    _activer_pretri(0.9)
    monkeypatch.setattr(settings, "jev_budget_tokens_mois", 10)
    with Session(get_engine()) as s:
        _ao(s)
    appels: list = []
    rapport = _lancer(monkeypatch, 0.0, appels)
    assert appels == []
    assert rapport.ao_analyses == 1


def test_forcer_analyse_leve_le_marquage_et_reglage_api(monkeypatch):
    from hermes.api import krinos as api_krinos
    from hermes.main import app

    init_db()
    client = TestClient(app)
    assert client.get("/krinos/jev").json()["pretri_actif"] is False
    r = client.put("/krinos/jev/pretri", json={"pretri_actif": True, "pretri_seuil": 0.4})
    assert r.json()["pretri_actif"] is True
    assert r.json()["pretri_seuil"] == 0.4
    r = client.put("/krinos/jev/pretri", json={"pretri_actif": True, "pretri_seuil": 2})
    assert r.status_code == 422

    with Session(get_engine()) as s:
        ao_id = _ao(s)
        ao = s.get(AppelOffre, ao_id)
        ao.hors_profil_jev = True
        s.add(ao)
        s.commit()
    assert client.get(f"/appels-offre/{ao_id}").json()["hors_profil_jev"] is True

    async def faux_analyser(session, ao, forcer=False):
        raise api_krinos.ErreurAnalyseKrinos("PYTHIA absent")

    async def faux_extraire(*a, **k):
        return SimpleNamespace(
            documents_traites=0, erreurs=[], avertissements=[], caracteres_extraits=0
        )

    monkeypatch.setattr(api_krinos, "analyser_ao", faux_analyser)
    monkeypatch.setattr(api_krinos, "extraire_documents_appel_offre_async", faux_extraire)
    client.post(f"/krinos/appels-offre/{ao_id}/analyser", json={"forcer": True})
    assert client.get(f"/appels-offre/{ao_id}").json()["hors_profil_jev"] is False


def test_marquage_non_bloquant_si_pretri_desactive(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        ao_id = _ao(s)
        ao = s.get(AppelOffre, ao_id)
        ao.hors_profil_jev = True
        ao.pertinence_jev = 0.05
        s.add(ao)
        s.commit()
    appels: list = []
    rapport = _lancer(monkeypatch, 0.0, appels)  # pré-tri désactivé
    assert appels == []
    assert rapport.ao_analyses == 1


def test_ao_deja_evalue_pas_reevalue(monkeypatch):
    init_db()
    _activer_pretri(0.3)
    with Session(get_engine()) as s:
        ao_id = _ao(s)
        ao = s.get(AppelOffre, ao_id)
        ao.pertinence_jev = 0.05  # p. ex. analyse forcée puis échec
        s.add(ao)
        s.commit()
    appels: list = []
    rapport = _lancer(monkeypatch, 0.0, appels)
    assert appels == []
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
    appels: list = []
    _lancer(monkeypatch, 0.8, appels)
    avis = appels[0]["state"]["avis"]
    assert "120000" in avis["budget_estime"]
    assert avis["date_limite"].startswith("2026-12-01")

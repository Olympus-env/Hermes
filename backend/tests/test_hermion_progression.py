"""Tests du suivi d'avancement HERMION (issue #7)."""

from __future__ import annotations

import asyncio
import json

from sqlmodel import Session

from hermes.agents import pythia
from hermes.agents.hermion import progression
from hermes.db.models import AnalyseKrinos, AppelOffre, StatutAO
from hermes.db.session import get_engine, init_db


def _faux_reponse(texte: str) -> pythia.ReponsePythia:
    return pythia.ReponsePythia(texte=texte, modele="m", duree_ms=10)


async def _generer_ok(prompt, *, system=None, format_json=False, **_):
    if format_json:
        return _faux_reponse(
            json.dumps(
                {
                    "sections": [
                        {"titre": "Comprehension", "brief": "b"},
                        {"titre": "Methodologie", "brief": "b"},
                        {"titre": "Moyens", "brief": "b"},
                    ]
                }
            )
        )
    return _faux_reponse("## Titre\n\nContenu de section.\n")


async def _generer_ko(prompt, *, system=None, format_json=False, **_):
    raise pythia.ErreurPythia("Ollama indisponible")


def _ao_avec_analyse(session: Session) -> int:
    ao = AppelOffre(
        titre="Maintenance SI",
        url_source="https://example.test/ao-progress",
        statut=StatutAO.A_REPONDRE,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    session.add(
        AnalyseKrinos(
            appel_offre_id=ao.id,
            resume="r",
            score=70.0,
            justification_score="j",
        )
    )
    session.commit()
    return ao.id


def test_progression_termine_apres_redaction(monkeypatch):
    from hermes.agents.hermion import writer

    monkeypatch.setattr(writer.pythia, "generer", _generer_ok)
    init_db()
    with Session(get_engine()) as session:
        ao_id = _ao_avec_analyse(session)
        ao = session.get(AppelOffre, ao_id)
        resultat = asyncio.run(writer.rediger_reponse(session, ao))

    etat = progression.lire(ao_id)
    assert etat is not None
    assert etat.etape == progression.ETAPE_TERMINE
    assert etat.termine is True
    assert etat.reponse_id == resultat.reponse.id


def test_progression_echec_si_pythia_down(monkeypatch):
    from hermes.agents.hermion import writer

    monkeypatch.setattr(writer.pythia, "generer", _generer_ko)
    init_db()
    with Session(get_engine()) as session:
        ao_id = _ao_avec_analyse(session)
        ao = session.get(AppelOffre, ao_id)
        try:
            asyncio.run(writer.rediger_reponse(session, ao))
        except writer.ErreurRedactionHermion:
            pass

    etat = progression.lire(ao_id)
    assert etat is not None
    assert etat.etape == progression.ETAPE_ECHEC
    assert etat.erreur is not None


def test_endpoint_progression_inconnue():
    from fastapi.testclient import TestClient

    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/hermion/appels-offre/99999/progression")
        assert r.status_code == 200
        body = r.json()
        assert body["connue"] is False
        assert body["termine"] is False

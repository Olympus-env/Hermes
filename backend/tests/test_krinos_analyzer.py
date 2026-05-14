"""Tests KRINOS — analyseur IA (PYTHIA) Phase 5."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes.agents import pythia
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    Document,
    LogAgent,
    StatutAO,
    TypeDocument,
)
from hermes.db.session import get_engine, init_db


def _faux_pythia_reponse(payload: dict) -> pythia.ReponsePythia:
    return pythia.ReponsePythia(
        texte=json.dumps(payload, ensure_ascii=False),
        modele="mistral:7b-instruct-q4_K_M",
        duree_ms=42,
    )


def _ao_avec_document(session: Session, contenu_extrait: str | None) -> AppelOffre:
    ao = AppelOffre(
        titre="Rénovation thermique bâtiment communal",
        emetteur="Ville de Test",
        objet="Travaux d'isolation et chauffage",
        url_source="https://example.test/ao/krinos-analyse",
        statut=StatutAO.BRUT,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)

    if contenu_extrait is not None:
        document = Document(
            appel_offre_id=ao.id,  # type: ignore[arg-type]
            nom_fichier="cctp.txt",
            chemin_local="docs/cctp.txt",
            type=TypeDocument.AUTRE,
            taille_octets=len(contenu_extrait),
            checksum_sha256="abc123",
            contenu_extrait=contenu_extrait,
        )
        session.add(document)
        session.commit()
    return ao


def test_parser_json_sortie_avec_fence():
    texte = "```json\n{\"resume\": \"OK\", \"score\": 80}\n```"
    payload = pythia.parser_json_sortie(texte)
    assert payload == {"resume": "OK", "score": 80}


def test_parser_json_sortie_avec_preambule():
    texte = "Voici l'analyse :\n{\"resume\": \"OK\", \"score\": 42}\nMerci."
    payload = pythia.parser_json_sortie(texte)
    assert payload == {"resume": "OK", "score": 42}


def test_parser_json_sortie_echoue_sur_texte_libre():
    with pytest.raises(pythia.ErreurPythia):
        pythia.parser_json_sortie("aucun JSON ici")


def test_analyser_ao_persiste_resultat_et_passe_en_analyse(monkeypatch):
    from hermes.agents.krinos import analyzer

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_document(session, "CCTP isolation thermique extérieure")
        ao_id = ao.id

    async def fake_generer(prompt, *, system=None, format_json=False, **_):
        assert format_json is True
        assert "Rénovation thermique" in prompt
        assert "CCTP isolation thermique" in prompt
        return _faux_pythia_reponse(
            {
                "resume": "AO de rénovation thermique pour un bâtiment communal.",
                "score": 78,
                "justification": "Dossier clair, délais corrects, budget non précisé.",
                "tags": ["bâtiment", "isolation", "chauffage", "rénovation"],
                "criteres": "Prix 40%, valeur technique 60%",
            }
        )

    monkeypatch.setattr(analyzer.pythia, "generer", fake_generer)

    import asyncio

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        assert ao is not None
        resultat = asyncio.run(analyzer.analyser_ao(session, ao))
        assert resultat.nouveau is True
        analyse = resultat.analyse
        assert analyse.score == 78
        assert "rénovation thermique" in analyse.resume.lower()
        assert analyse.modele_llm == "mistral:7b-instruct-q4_K_M"
        assert analyse.duree_analyse_ms is not None and analyse.duree_analyse_ms >= 0
        tags = json.loads(analyse.tags) if analyse.tags else []
        assert "bâtiment" in tags

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        assert ao is not None
        assert ao.statut == StatutAO.ANALYSE
        logs = session.exec(select(LogAgent).where(LogAgent.agent == "KRINOS")).all()
        assert any("Analyse KRINOS terminée" in log.message for log in logs)


def test_analyser_ao_idempotent_sans_forcer(monkeypatch):
    from hermes.agents.krinos import analyzer

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_document(session, "Texte court.")
        ao_id = ao.id

    appels = {"n": 0}

    async def fake_generer(*args, **kwargs):
        appels["n"] += 1
        return _faux_pythia_reponse(
            {
                "resume": "Analyse initiale.",
                "score": 50,
                "justification": "Manque d'info.",
                "tags": ["test"],
                "criteres": "",
            }
        )

    monkeypatch.setattr(analyzer.pythia, "generer", fake_generer)
    import asyncio

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        r1 = asyncio.run(analyzer.analyser_ao(session, ao))
        id_initial = r1.analyse.id
        assert r1.nouveau is True

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        r2 = asyncio.run(analyzer.analyser_ao(session, ao))
        assert r2.nouveau is False
        assert r2.analyse.id == id_initial

    assert appels["n"] == 1


def test_analyser_ao_force_recalcul(monkeypatch):
    from hermes.agents.krinos import analyzer

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_document(session, "Texte.")
        ao_id = ao.id

    scores = iter([40, 90])

    async def fake_generer(*args, **kwargs):
        return _faux_pythia_reponse(
            {
                "resume": "Résumé.",
                "score": next(scores),
                "justification": "OK.",
                "tags": [],
                "criteres": "",
            }
        )

    monkeypatch.setattr(analyzer.pythia, "generer", fake_generer)
    import asyncio

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        asyncio.run(analyzer.analyser_ao(session, ao))
    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        r2 = asyncio.run(analyzer.analyser_ao(session, ao, forcer=True))
        assert r2.nouveau is True
        assert r2.analyse.score == 90

    with Session(get_engine()) as session:
        analyses = session.exec(
            select(AnalyseKrinos).where(AnalyseKrinos.appel_offre_id == ao_id)
        ).all()
        assert len(analyses) == 2


def test_endpoint_analyser_renvoie_resultat(monkeypatch):
    from hermes.agents.krinos import analyzer
    from hermes.main import app

    async def fake_generer(*args, **kwargs):
        return _faux_pythia_reponse(
            {
                "resume": "AO simple.",
                "score": 65,
                "justification": "Documents partiels.",
                "tags": ["maintenance"],
                "criteres": "Prix 50% qualité 50%",
            }
        )

    monkeypatch.setattr(analyzer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_document(session, "Maintenance applicative")
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.post(f"/krinos/appels-offre/{ao_id}/analyser")

    assert r.status_code == 200
    data = r.json()
    assert data["nouveau"] is True
    assert data["analyse"]["score"] == 65
    assert data["analyse"]["tags"] == ["maintenance"]

    with TestClient(app) as client:
        r2 = client.get(f"/krinos/appels-offre/{ao_id}/analyse")
    assert r2.status_code == 200
    assert r2.json()["score"] == 65


def test_endpoint_analyse_404_si_absente():
    from hermes.main import app

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(titre="vide", url_source="https://example.test/none")
        session.add(ao)
        session.commit()
        session.refresh(ao)
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.get(f"/krinos/appels-offre/{ao_id}/analyse")
    assert r.status_code == 404


def test_endpoint_analyser_502_si_pythia_indisponible(monkeypatch):
    from hermes.agents.krinos import analyzer
    from hermes.main import app

    async def fake_generer(*args, **kwargs):
        raise pythia.ErreurPythia("connexion refusée")

    monkeypatch.setattr(analyzer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_document(session, "x")
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.post(f"/krinos/appels-offre/{ao_id}/analyser")
    assert r.status_code == 502
    assert "connexion refusée" in r.json()["detail"]


def test_analyser_ao_rejette_sortie_sans_resume(monkeypatch):
    from hermes.agents.krinos import analyzer

    async def fake_generer(*args, **kwargs):
        return _faux_pythia_reponse({"score": 50, "tags": []})

    monkeypatch.setattr(analyzer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_document(session, "x")
        ao_id = ao.id

    import asyncio

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        with pytest.raises(analyzer.ErreurAnalyseKrinos):
            asyncio.run(analyzer.analyser_ao(session, ao))

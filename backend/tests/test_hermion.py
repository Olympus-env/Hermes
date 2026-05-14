"""Tests HERMION — rédaction Phase 7."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes.agents import pythia
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    LogAgent,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)
from hermes.db.session import get_engine, init_db


def _faux_reponse(texte: str) -> pythia.ReponsePythia:
    return pythia.ReponsePythia(texte=texte, modele="mistral:7b-instruct-q4_K_M", duree_ms=10)


def _faux_generateur_complet(plan_payload: dict | None = None):
    """Simule PYTHIA : 1er appel = plan JSON, suivants = sections markdown."""
    plan = plan_payload or {
        "sections": [
            {"titre": "Comprehension du besoin", "brief": "Reformuler le besoin."},
            {"titre": "Methodologie", "brief": "Approche proposee."},
            {"titre": "Moyens", "brief": "Equipe et outils."},
        ]
    }
    etat = {"appel": 0, "plan": plan}

    async def fake_generer(prompt, *, system=None, format_json=False, **_):
        etat["appel"] += 1
        if format_json:
            return _faux_reponse(json.dumps(etat["plan"], ensure_ascii=False))
        # Section : on renvoie un markdown plausible.
        return _faux_reponse(
            "## Titre genere\n\n"
            "Contenu de la section, redige en francais professionnel.\n"
        )

    return fake_generer, etat


def _ao_avec_analyse(session: Session, statut: StatutAO = StatutAO.A_REPONDRE) -> AppelOffre:
    ao = AppelOffre(
        titre="Maintenance applicative SI metier",
        emetteur="Mairie de Test",
        objet="Maintenance corrective et evolutive",
        type_marche="services",
        url_source="https://example.test/ao-hermion",
        statut=statut,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)

    session.add(
        AnalyseKrinos(
            appel_offre_id=ao.id,  # type: ignore[arg-type]
            resume="AO de maintenance applicative sur 3 ans.",
            score=72.0,
            justification_score="Dossier clair, perimetre raisonnable.",
            tags=json.dumps(["maintenance", "applicatif"], ensure_ascii=False),
            criteres_extraits="Prix 40%, qualite technique 60%",
            modele_llm="mistral:7b-instruct-q4_K_M",
        )
    )
    session.commit()
    return ao


def test_rediger_genere_v1_et_passe_en_redaction(monkeypatch):
    from hermes.agents.hermion import writer

    fake_generer, etat = _faux_generateur_complet()
    monkeypatch.setattr(writer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        resultat = asyncio.run(writer.rediger_reponse(session, ao))
        reponse = resultat.reponse
        assert reponse.version == 1
        assert reponse.statut == StatutReponse.EN_ATTENTE
        assert reponse.longueur_mots and reponse.longueur_mots > 10
        assert "# Réponse — Maintenance" in reponse.contenu
        assert "## Sommaire" in reponse.contenu
        assert len(resultat.plan) == 3
        workflow = json.loads(reponse.workflow_utilise or "{}")
        assert workflow["nom"] == "plan_puis_sections"

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        assert ao.statut == StatutAO.EN_REDACTION
        logs = session.exec(select(LogAgent).where(LogAgent.agent == "HERMION")).all()
        assert any("réponse v1 générée" in log.message for log in logs)

    assert etat["appel"] == 1 + 3  # plan + 3 sections


def test_rediger_incremente_la_version(monkeypatch):
    from hermes.agents.hermion import writer

    fake_generer, _ = _faux_generateur_complet()
    monkeypatch.setattr(writer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        asyncio.run(writer.rediger_reponse(session, ao))
    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        r2 = asyncio.run(writer.rediger_reponse(session, ao))
        assert r2.reponse.version == 2


def test_rediger_echoue_sans_analyse_krinos(monkeypatch):
    from hermes.agents.hermion import writer

    monkeypatch.setattr(writer.pythia, "generer", _faux_generateur_complet()[0])

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(
            titre="AO sans analyse",
            url_source="https://example.test/no-analyse",
            statut=StatutAO.A_REPONDRE,
        )
        session.add(ao)
        session.commit()
        session.refresh(ao)
        ao_id = ao.id

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        with pytest.raises(writer.ErreurRedactionHermion):
            asyncio.run(writer.rediger_reponse(session, ao))


def test_rediger_rejette_plan_trop_court(monkeypatch):
    from hermes.agents.hermion import writer

    fake_generer, _ = _faux_generateur_complet(plan_payload={"sections": [{"titre": "Seule"}]})
    monkeypatch.setattr(writer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        with pytest.raises(writer.ErreurRedactionHermion):
            asyncio.run(writer.rediger_reponse(session, ao))


def test_endpoint_rediger_renvoie_v1(monkeypatch):
    from hermes.agents.hermion import writer
    from hermes.main import app

    fake_generer, _ = _faux_generateur_complet()
    monkeypatch.setattr(writer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.post(
            f"/hermion/appels-offre/{ao_id}/rediger",
            json={
                "profil": {
                    "prenom": "Joshua",
                    "nom": "Test",
                    "email": "j@example.test",
                    "entreprise": "ACME",
                    "activite": "ESN",
                },
                "consignes": "Insiste sur l'experience metier.",
            },
        )

    assert r.status_code == 200
    data = r.json()
    assert data["reponse"]["version"] == 1
    assert data["reponse"]["statut"] == "en_attente"
    assert len(data["plan"]) == 3


def test_endpoint_rediger_refuse_statut_brut(monkeypatch):
    from hermes.agents.hermion import writer
    from hermes.main import app

    monkeypatch.setattr(writer.pythia, "generer", _faux_generateur_complet()[0])

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session, statut=StatutAO.BRUT)
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.post(f"/hermion/appels-offre/{ao_id}/rediger")
    assert r.status_code == 409


def test_endpoint_liste_reponses(monkeypatch):
    from hermes.agents.hermion import writer
    from hermes.main import app

    monkeypatch.setattr(writer.pythia, "generer", _faux_generateur_complet()[0])

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with TestClient(app) as client:
        client.post(f"/hermion/appels-offre/{ao_id}/rediger")
        client.post(f"/hermion/appels-offre/{ao_id}/rediger")
        r = client.get(f"/hermion/appels-offre/{ao_id}/reponses")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["version"] == 2  # tri desc
    assert data[1]["version"] == 1


def test_endpoint_modifier_statut_valide_propage_ao(monkeypatch):
    from hermes.agents.hermion import writer
    from hermes.main import app

    monkeypatch.setattr(writer.pythia, "generer", _faux_generateur_complet()[0])

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with TestClient(app) as client:
        client.post(f"/hermion/appels-offre/{ao_id}/rediger")
        with Session(get_engine()) as s:
            reponse_id = s.exec(
                select(ReponseHermion.id).where(ReponseHermion.appel_offre_id == ao_id)
            ).first()
        r = client.patch(
            f"/hermion/reponses/{reponse_id}/statut",
            json={"statut": "validee", "commentaire_humain": "OK"},
        )

    assert r.status_code == 200
    assert r.json()["statut"] == "validee"

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        assert ao.statut == StatutAO.REPONDU
        reponse = session.get(ReponseHermion, reponse_id)
        assert reponse.commentaire_humain == "OK"


def test_endpoint_modifier_statut_refuse_transition_invalide(monkeypatch):
    from hermes.agents.hermion import writer
    from hermes.main import app

    monkeypatch.setattr(writer.pythia, "generer", _faux_generateur_complet()[0])

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with TestClient(app) as client:
        client.post(f"/hermion/appels-offre/{ao_id}/rediger")
        with Session(get_engine()) as s:
            reponse_id = s.exec(
                select(ReponseHermion.id).where(ReponseHermion.appel_offre_id == ao_id)
            ).first()
        # en_attente → exportee : interdit (doit passer par validee)
        r = client.patch(
            f"/hermion/reponses/{reponse_id}/statut",
            json={"statut": "exportee"},
        )
    assert r.status_code == 409


def test_endpoint_modifier_contenu_passe_en_a_modifier(monkeypatch):
    from hermes.agents.hermion import writer
    from hermes.main import app

    monkeypatch.setattr(writer.pythia, "generer", _faux_generateur_complet()[0])

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with TestClient(app) as client:
        client.post(f"/hermion/appels-offre/{ao_id}/rediger")
        with Session(get_engine()) as s:
            reponse_id = s.exec(
                select(ReponseHermion.id).where(ReponseHermion.appel_offre_id == ao_id)
            ).first()
        r = client.patch(
            f"/hermion/reponses/{reponse_id}/contenu",
            json={
                "contenu": "# Contenu edite\nNouvelle version texte.",
                "commentaire_humain": "edit",
            },
        )

    assert r.status_code == 200
    data = r.json()
    assert data["statut"] == "a_modifier"
    assert "Contenu edite" in data["contenu"]
    assert data["commentaire_humain"] == "edit"


def test_endpoint_liste_toutes_reponses_joint_ao(monkeypatch):
    from hermes.agents.hermion import writer
    from hermes.main import app

    monkeypatch.setattr(writer.pythia, "generer", _faux_generateur_complet()[0])

    init_db()
    with Session(get_engine()) as session:
        _ao_avec_analyse(session)
        _ao_avec_analyse(session)

    with TestClient(app) as client:
        # Une reponse pour chaque AO
        with Session(get_engine()) as s:
            ao_ids = sorted([r for r in s.exec(select(AppelOffre.id)).all()])
        for ao_id in ao_ids:
            client.post(f"/hermion/appels-offre/{ao_id}/rediger")

        r = client.get("/hermion/reponses")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        # Chaque item a bien le titre + emetteur AO joints
        assert all(item["appel_offre_titre"] for item in data)
        assert all(item["appel_offre_emetteur"] for item in data)

        # Filtre par statut
        r2 = client.get("/hermion/reponses?statut=en_attente")
        assert r2.status_code == 200
        assert len(r2.json()) == 2

        r3 = client.get("/hermion/reponses?statut=validee")
        assert r3.status_code == 200
        assert len(r3.json()) == 0


def test_endpoint_rediger_502_si_pythia_erreur(monkeypatch):
    from hermes.agents.hermion import writer
    from hermes.main import app

    async def fake_generer(*args, **kwargs):
        raise pythia.ErreurPythia("connexion refusee")

    monkeypatch.setattr(writer.pythia, "generer", fake_generer)

    init_db()
    with Session(get_engine()) as session:
        ao = _ao_avec_analyse(session)
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.post(f"/hermion/appels-offre/{ao_id}/rediger")
    assert r.status_code == 502

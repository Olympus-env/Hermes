"""Tests pondération scoring KRINOS — modèle, calcul et routes API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.agents.krinos.ponderation import (
    Ponderation,
    calculer_score_final,
    charger_ponderation,
    enregistrer_ponderation,
)
from hermes.db.models import Parametre
from hermes.db.session import get_engine, init_db


def test_ponderation_defaut_somme_100():
    p = Ponderation()
    assert p.total == 100
    assert p.affinite_metier == 30


def test_ponderation_normalise():
    p = Ponderation(40, 40, 40, 40, 40)  # total 200
    n = p.normalise()
    assert n.total == 100  # à un epsilon d'arrondi près
    assert n.affinite_metier == 20


def test_calcul_score_final_pondere():
    p = Ponderation()  # 30/20/20/15/15
    scores = {
        "affinite_metier": 80,
        "references": 60,
        "adequation_budget": 70,
        "capacite_equipe": 50,
        "calendrier": 90,
    }
    score = calculer_score_final(scores, p)
    # 30*80 + 20*60 + 20*70 + 15*50 + 15*90 = 2400+1200+1400+750+1350 = 7100
    # / 100 = 71.0
    assert score == 71.0


def test_calcul_score_final_dimension_manquante():
    """Si une dimension manque, le calcul ignore cette dimension et son poids."""
    p = Ponderation()
    scores = {"affinite_metier": 100}  # seule dimension présente
    # Doit retourner 100 (la seule dim disponible) et non un score divisé.
    assert calculer_score_final(scores, p) == 100.0


def test_calcul_score_final_aucune_dimension():
    p = Ponderation()
    assert calculer_score_final({}, p) == 0.0


def test_enregistrer_et_charger_ponderation():
    init_db()
    with Session(get_engine()) as session:
        valeurs = Ponderation(
            affinite_metier=50,
            references=10,
            adequation_budget=10,
            capacite_equipe=15,
            calendrier=15,
        )
        enregistrer_ponderation(session, valeurs)

    with Session(get_engine()) as session:
        relu = charger_ponderation(session)
        assert relu.affinite_metier == 50
        assert relu.references == 10


def test_charger_ponderation_defaut_si_absente():
    init_db()
    with Session(get_engine()) as session:
        p = charger_ponderation(session)
    assert p == Ponderation()


def test_charger_ponderation_tolere_json_corrompu():
    init_db()
    with Session(get_engine()) as session:
        session.add(
            Parametre(
                cle="krinos.ponderation_scoring",
                valeur="pas du JSON",
            )
        )
        session.commit()
        p = charger_ponderation(session)
    assert p == Ponderation()


def test_endpoint_get_put_ponderation():
    from hermes.main import app

    init_db()
    with TestClient(app) as client:
        r = client.get("/krinos/ponderation")
        assert r.status_code == 200
        data = r.json()
        assert data["affinite_metier"] == 30
        assert data["total"] == 100

        r = client.put(
            "/krinos/ponderation",
            json={
                "affinite_metier": 50,
                "references": 25,
                "adequation_budget": 10,
                "capacite_equipe": 10,
                "calendrier": 5,
            },
        )
        assert r.status_code == 200
        nouveau = r.json()
        assert nouveau["affinite_metier"] == 50
        assert nouveau["total"] == 100

        r = client.get("/krinos/ponderation")
        assert r.json()["affinite_metier"] == 50


def test_endpoint_analyse_expose_scores_dimensions():
    from hermes.db.models import AnalyseKrinos, AppelOffre
    from hermes.main import app

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(titre="AO scores", url_source="https://example.test/scores")
        session.add(ao)
        session.commit()
        session.refresh(ao)
        session.add(
            AnalyseKrinos(
                appel_offre_id=ao.id,
                resume="Analyse",
                score=75,
                justification_score="OK",
                scores_dimensions=json.dumps({"affinite_metier": 90, "references": 60}),
            )
        )
        session.commit()
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.get(f"/krinos/appels-offre/{ao_id}/analyse")
        assert r.status_code == 200
        data = r.json()
        assert data["scores_dimensions"]["affinite_metier"] == 90.0
        assert data["scores_dimensions"]["references"] == 60.0


def test_endpoint_recalcule_score_depuis_scores_dimensions():
    from hermes.db.models import AnalyseKrinos, AppelOffre
    from hermes.main import app

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(titre="AO recalcul", url_source="https://example.test/recalc")
        session.add(ao)
        session.commit()
        session.refresh(ao)
        session.add(
            AnalyseKrinos(
                appel_offre_id=ao.id,
                resume="Analyse",
                score=10,
                justification_score="Ancien score",
                scores_dimensions=json.dumps(
                    {
                        "affinite_metier": 80,
                        "references": 20,
                        "adequation_budget": 20,
                        "capacite_equipe": 20,
                        "calendrier": 20,
                    }
                ),
            )
        )
        enregistrer_ponderation(
            session,
            Ponderation(
                affinite_metier=100,
                references=0,
                adequation_budget=0,
                capacite_equipe=0,
                calendrier=0,
            ),
        )
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.post(f"/krinos/appels-offre/{ao_id}/recalculer-score")
        assert r.status_code == 200
        assert r.json()["score"] == 80.0


def test_analyseur_utilise_scores_dimensions(monkeypatch):
    """Si le LLM renvoie scores_dimensions, l'analyseur calcule score pondéré."""
    from hermes.agents import pythia
    from hermes.agents.krinos import analyzer
    from hermes.db.models import AnalyseKrinos, AppelOffre, StatutAO

    init_db()
    with Session(get_engine()) as session:
        ao = AppelOffre(
            titre="Test pondération",
            url_source="https://example.test/p",
            statut=StatutAO.BRUT,
        )
        session.add(ao)
        session.commit()
        session.refresh(ao)
        ao_id = ao.id

        # Pondération personnalisée : on met tout sur affinité métier
        enregistrer_ponderation(
            session,
            Ponderation(
                affinite_metier=100,
                references=0,
                adequation_budget=0,
                capacite_equipe=0,
                calendrier=0,
            ),
        )

    async def fake_generer(*args, **kwargs):
        return pythia.ReponsePythia(
            texte=json.dumps(
                {
                    "resume": "Test analyse",
                    "scores_dimensions": {
                        "affinite_metier": 80,
                        "references": 20,
                        "adequation_budget": 20,
                        "capacite_equipe": 20,
                        "calendrier": 20,
                    },
                    "justification": "test",
                    "tags": ["a", "b"],
                    "criteres": "",
                }
            ),
            modele="mistral",
            duree_ms=1,
        )

    monkeypatch.setattr(analyzer.pythia, "generer", fake_generer)

    import asyncio

    with Session(get_engine()) as session:
        ao = session.get(AppelOffre, ao_id)
        result = asyncio.run(analyzer.analyser_ao(session, ao))
        # 100% sur affinite_metier (=80), autres dims poids 0
        # → score final = 80
        assert result.analyse.score == 80.0
        # scores_dimensions doit être stocké
        dims = json.loads(result.analyse.scores_dimensions or "{}")
        assert dims["affinite_metier"] == 80

    # Vérif persistance
    with Session(get_engine()) as session:
        analyses = session.exec(
            __import__("sqlmodel").select(AnalyseKrinos).where(
                AnalyseKrinos.appel_offre_id == ao_id
            )
        ).all()
        assert len(analyses) == 1
        assert analyses[0].scores_dimensions is not None

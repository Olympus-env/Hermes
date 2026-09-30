"""Tests KRINOS — routage par confiance, composite go/no-go, calibration (issue #44).

Aucun appel réseau : transport httpx simulé, comme dans `test_krinos_jev.py`.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.agents.krinos import jev
from hermes.agents.krinos.ponderation import (
    ConfigComposite,
    calculer_composite,
    verdict_composite,
)
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)
from hermes.db.session import get_engine, init_db
from hermes.main import app

from .test_krinos_jev import (  # noqa: F401 — _jev_isole est une fixture autouse
    _activer,
    _ao,
    _jev_isole,
    _pythia_dims,
    _reponse_jev,
    _transport,
    analyzer,
)


def _analyser_via_jev(monkeypatch, pythia: int = 70, **reponse):
    _activer(monkeypatch)
    monkeypatch.setattr(analyzer.pythia, "generer", _pythia_dims(pythia))
    appels: list[httpx.Request] = []
    monkeypatch.setattr(
        jev, "_transport", _transport([httpx.Response(200, json=_reponse_jev(**reponse))], appels)
    )
    init_db()
    from .test_krinos_jev import _analyser

    analyse = _analyser(_ao())
    return analyse, appels


def test_seuils_par_defaut_egaux_aux_constantes():
    init_db()
    with Session(get_engine()) as s:
        seuils = jev.charger_seuils(s)
    assert seuils == jev.SeuilsJev(25.0, 0.5, 0.2, 0.5)


def test_seuils_invalides_retombent_sur_les_defauts():
    init_db()
    with Session(get_engine()) as s:
        brut = {"divergence": -3, "confiance": "x", "pertinence": 0.4}
        jev._ecrire_json(s, jev.CLE_SEUILS, brut, "t")
        seuils = jev.charger_seuils(s)
    assert seuils.divergence == 25.0 and seuils.confiance == 0.5 and seuils.pertinence == 0.4


def test_confiance_faible_route_vers_a_verifier(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        jev.enregistrer_seuils(s, jev.SeuilsJev(confiance=0.9))  # Jev répond à 0.8
    analyse, _ = _analyser_via_jev(monkeypatch)
    assert analyse.a_verifier is True
    assert "jev:confiance_faible" in json.loads(analyse.drapeaux)
    assert analyse.suspect_injection is False


def test_confiance_suffisante_pas_de_drapeau(monkeypatch):
    analyse, _ = _analyser_via_jev(monkeypatch)
    assert analyse.a_verifier is False and analyse.drapeaux is None


def test_seuil_divergence_configurable(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        jev.enregistrer_seuils(s, jev.SeuilsJev(divergence=60))
    analyse, _ = _analyser_via_jev(monkeypatch, pythia=30)  # écart 45 < 60
    assert analyse.a_verifier is False


def test_pertinence_faible_route_vers_a_verifier(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        jev.enregistrer_seuils(s, jev.SeuilsJev(pertinence=0.95))  # Jev répond 0.9
    analyse, _ = _analyser_via_jev(monkeypatch)
    assert "jev:pertinence_faible" in json.loads(analyse.drapeaux)


def test_composite_pur():
    cfg = ConfigComposite(poids_pythia=50, poids_jev=30, poids_pertinence=20, seuil_go=60)
    assert calculer_composite(
        score_pythia=80, score_jev=60, pertinence_jev=0.5, config=cfg
    ) == pytest.approx(68.0)
    # Sans Jev : poids re-normalisés, on retrouve le score PYTHIA.
    assert calculer_composite(
        score_pythia=80, score_jev=None, pertinence_jev=None, config=cfg
    ) == 80.0
    assert calculer_composite(
        score_pythia=None, score_jev=None, pertinence_jev=None, config=cfg
    ) is None
    # a_verifier prime toujours : jamais de « go » sans humain.
    assert verdict_composite(99.0, cfg, a_verifier=True) == "a_verifier"
    assert verdict_composite(99.0, cfg, a_verifier=False) == "go"
    assert verdict_composite(10.0, cfg, a_verifier=False) == "no_go"


def test_composite_recalcule_sans_reinference(monkeypatch):
    analyse, appels = _analyser_via_jev(monkeypatch, pythia=70)  # pythia 70.5, jev 75, pert 0.9
    n_appels = len(appels)
    with TestClient(app) as client:
        r = client.get(f"/krinos/appels-offre/{analyse.appel_offre_id}/analyse")
        base = r.json()
        # 50*70.5 + 35*75 + 15*90 = 7500 -> /100
        assert base["composite"] == pytest.approx(75.0)
        assert base["verdict_composite"] == "go"

        r = client.put(
            "/krinos/composite",
            json={"poids_pythia": 0, "poids_jev": 0, "poids_pertinence": 100, "seuil_go": 95},
        )
        assert r.status_code == 200
        apres = client.get(f"/krinos/appels-offre/{analyse.appel_offre_id}/analyse").json()
        assert apres["composite"] == 90.0
        assert apres["verdict_composite"] == "no_go"
        assert client.put("/krinos/composite", json={"poids_pythia": 0, "poids_jev": 0,
                                                     "poids_pertinence": 0}).status_code == 422
    assert len(appels) == n_appels  # aucune ré-inférence


def test_verdict_a_verifier_si_drapeau(monkeypatch):
    analyse, _ = _analyser_via_jev(monkeypatch, pythia=70, manipulation=0.93)
    with TestClient(app) as client:
        r = client.get(f"/krinos/appels-offre/{analyse.appel_offre_id}/analyse").json()
    assert r["a_verifier"] is True and r["verdict_composite"] == "a_verifier"


def test_recalcul_ne_leve_jamais_a_verifier_et_garde_l_ordre(monkeypatch):
    analyse, appels = _analyser_via_jev(monkeypatch, pythia=30)  # divergence 45
    assert "divergence_jev_pythia" in json.loads(analyse.drapeaux)
    with Session(get_engine()) as s:  # drapeau du juge local préexistant : à conserver
        a = s.get(AnalyseKrinos, analyse.id)
        a.drapeaux = json.dumps(["pythia:manipulation", *json.loads(a.drapeaux)])
        s.add(a)
        s.commit()
    with TestClient(app) as client:
        avant = client.get(f"/krinos/appels-offre/{analyse.appel_offre_id}/analyse").json()
        # Assouplir les seuils ne doit JAMAIS lever a_verifier (ni donner « go »).
        client.put(
            "/krinos/jev/seuils",
            json={"divergence": 80, "manipulation": 0.5, "pertinence": 0.2, "confiance": 0.5},
        )
        r = client.post(f"/krinos/appels-offre/{analyse.appel_offre_id}/recalculer-score")
        assert r.status_code == 200
        assert r.json()["a_verifier"] is True
        assert r.json()["verdict_composite"] == "a_verifier"
        assert r.json()["drapeaux"] == avant["drapeaux"]  # conservés, même ordre
        assert r.json()["drapeaux"][0] == "pythia:manipulation"
        # Resserrer les seuils ajoute des drapeaux sans retirer les anciens.
        client.put(
            "/krinos/jev/seuils",
            json={"divergence": 10, "manipulation": 0.5, "pertinence": 0.2, "confiance": 0.99},
        )
        r = client.post(f"/krinos/appels-offre/{analyse.appel_offre_id}/recalculer-score")
        assert r.json()["drapeaux"][: len(avant["drapeaux"])] == avant["drapeaux"]
        assert "jev:confiance_faible" in r.json()["drapeaux"]
    assert len(appels) == 1


def test_recalcul_ne_change_pas_un_ao_sans_drapeau(monkeypatch):
    analyse, _ = _analyser_via_jev(monkeypatch, pythia=70)
    assert analyse.a_verifier is False
    with TestClient(app) as client:
        r = client.post(f"/krinos/appels-offre/{analyse.appel_offre_id}/recalculer-score")
        assert r.json()["a_verifier"] is False and r.json()["drapeaux"] == []


def test_put_nan_renvoie_422_pas_500():
    init_db()
    entetes = {"Content-Type": "application/json"}
    with TestClient(app) as client:
        brut = '{"divergence": NaN, "manipulation": 0.5, "pertinence": 0.2, "confiance": 0.5}'
        r = client.put("/krinos/jev/seuils", content=brut, headers=entetes)
        assert r.status_code == 422
        brut = '{"poids_pythia": NaN, "poids_jev": 1, "poids_pertinence": 1, "seuil_go": 1}'
        r = client.put("/krinos/composite", content=brut, headers=entetes)
        assert r.status_code == 422


def test_api_seuils_defauts_et_validation():
    init_db()
    with TestClient(app) as client:
        assert client.get("/krinos/jev/seuils").json() == {
            "divergence": 25.0, "manipulation": 0.5, "pertinence": 0.2, "confiance": 0.5,
        }
        r = client.put(
            "/krinos/jev/seuils",
            json={"divergence": 30, "manipulation": 0.7, "pertinence": 0.1, "confiance": 0.6},
        )
        assert r.status_code == 200
        assert client.get("/krinos/jev/seuils").json()["divergence"] == 30
        assert client.put("/krinos/jev/seuils", json={"manipulation": 1.5}).status_code == 422


def _semer(
    statut: StatutAO,
    score: float,
    score_jev: float | None,
    pertinence: float = 0.9,
    reponse: StatutReponse | None = None,
):
    with Session(get_engine()) as s:
        ao = AppelOffre(
            titre="AO", emetteur="V", url_source=f"https://x.test/{statut.value}/{score}/{score_jev}",
            statut=statut,
        )
        s.add(ao)
        s.commit()
        s.refresh(ao)
        if reponse is not None:
            s.add(ReponseHermion(appel_offre_id=ao.id, version=1, contenu="c", statut=reponse))
        s.add(
            AnalyseKrinos(
                appel_offre_id=ao.id, resume="r", score=score, justification_score="j",
                score_jev=score_jev,
                details_jev=(
                    json.dumps({"pertinence": pertinence}) if score_jev is not None else None
                ),
            )
        )
        s.commit()


def test_calibration_compare_decision_humaine():
    init_db()
    _semer(StatutAO.REPONDU, 80, 90)
    _semer(StatutAO.EN_REDACTION, 70, 50, reponse=StatutReponse.VALIDEE)  # humain avéré
    _semer(StatutAO.A_REPONDRE, 95, 95)  # posable par l'orchestrateur : ignoré
    _semer(StatutAO.EN_REDACTION, 92, 92, reponse=StatutReponse.EN_ATTENTE)  # ignoré
    _semer(StatutAO.REJETE, 30, 20)
    _semer(StatutAO.REJETE, 65, None)  # sans avis Jev
    _semer(StatutAO.BRUT, 99, 99)  # pas de décision : ignoré
    with TestClient(app) as client:
        r = client.get("/krinos/calibration")
    assert r.status_code == 200
    data = r.json()
    assert data["echantillon"] == {"total": 4, "acceptes": 2, "rejetes": 2, "avec_jev": 3}
    assert data["ecart_moyen_jev_pythia"] == pytest.approx((10 + 20 + 10) / 3, abs=0.1)
    pythia = data["sources"]["pythia"]
    # seuil 60 : 80 go/70 go/30 no/65 go(faux positif) -> 3 accords sur 4
    assert pythia["taux_accord"] == 0.75
    ligne_60 = next(m for m in pythia["matrice"] if m["seuil"] == 60)
    assert (ligne_60["vrais_positifs"], ligne_60["faux_positifs"]) == (2, 1)
    assert (ligne_60["vrais_negatifs"], ligne_60["faux_negatifs"]) == (1, 0)
    assert data["sources"]["jev"]["n"] == 3
    assert data["sources"]["pythia"]["score_moyen_accepte"] == 75.0
    assert "heuristique" in data


def test_calibration_vide():
    init_db()
    with TestClient(app) as client:
        data = client.get("/krinos/calibration").json()
    assert data["echantillon"]["total"] == 0
    assert data["sources"]["pythia"]["taux_accord"] is None

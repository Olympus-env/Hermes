"""Migration Jev -> Laya (issue #56) : colonnes renommées, réglages migrés, idempotence.

Une base existante (colonnes `*_jev`, réglages `krinos.jev.*`) doit continuer de
démarrer, sans perte de données.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text

from hermes.db.session import (
    _migrer_colonnes,
    _migrer_reglages_jev_vers_laya,
    _renommer_colonnes_jev_vers_laya,
)


@pytest.fixture
def base_ancienne():
    """Base minimale au schéma d'avant #56 (colonnes `*_jev`)."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE analyses_krinos (id INTEGER PRIMARY KEY, appel_offre_id INTEGER, "
                "resume TEXT, score FLOAT, justification_score TEXT, drapeaux TEXT, "
                "score_jev FLOAT, confiance_jev FLOAT, details_jev TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE appels_offre (id INTEGER PRIMARY KEY, titre TEXT, "
                "hors_profil_jev BOOLEAN NOT NULL DEFAULT 0, pertinence_jev FLOAT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE parametres (cle TEXT PRIMARY KEY, valeur TEXT, "
                "description TEXT, maj_le DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO analyses_krinos (appel_offre_id, resume, score, justification_score,"
                " drapeaux, score_jev, confiance_jev, details_jev) VALUES "
                "(1, 'r', 70, 'j', :d, 75.5, 0.8, :det)"
            ),
            {
                "d": json.dumps(
                    ["jev:manipulation", "divergence_jev_pythia", "pythia:manipulation"]
                ),
                "det": json.dumps({"pertinence": 0.9}),
            },
        )
        conn.execute(
            text("INSERT INTO appels_offre (titre, hors_profil_jev, pertinence_jev) "
                 "VALUES ('AO', 1, 0.12)")
        )
        for cle, valeur in {
            "krinos.jev.config": {"actif": True},
            "krinos.jev.pretri": {"actif": True, "seuil": 0.4},
            "krinos.jev.seuils": {"divergence": 30, "confiance": 0.6},
            "krinos.jev.budget": {"mois": "2026-09", "tokens": 1234},
            "profil.metier": {"activite": "ESN"},
        }.items():
            conn.execute(
                text(
                    "INSERT INTO parametres (cle, valeur, description) "
                    "VALUES (:c, :v, 'Juge Jev')"
                ),
                {"c": cle, "v": json.dumps(valeur)},
            )
    return engine


def _migrer(conn) -> None:
    _renommer_colonnes_jev_vers_laya(conn)
    _migrer_colonnes(conn)
    _migrer_reglages_jev_vers_laya(conn)


def _colonnes(conn, table: str) -> set[str]:
    return {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info('{table}')").fetchall()}


def _params(conn) -> dict[str, dict]:
    return {
        cle: json.loads(valeur)
        for cle, valeur in conn.exec_driver_sql("SELECT cle, valeur FROM parametres").fetchall()
    }


def test_colonnes_renommees_sans_perte_de_donnees(base_ancienne):
    with base_ancienne.begin() as conn:
        _migrer(conn)
        cols = _colonnes(conn, "analyses_krinos")
        assert {"score_laya", "confiance_laya", "details_laya"} <= cols
        assert not {"score_jev", "confiance_jev", "details_jev"} & cols
        cols_ao = _colonnes(conn, "appels_offre")
        assert {"hors_profil_laya", "pertinence_laya"} <= cols_ao
        assert not {"hors_profil_jev", "pertinence_jev"} & cols_ao
        score, conf, det = conn.exec_driver_sql(
            "SELECT score_laya, confiance_laya, details_laya FROM analyses_krinos"
        ).one()
        assert (score, conf, json.loads(det)) == (75.5, 0.8, {"pertinence": 0.9})
        assert conn.exec_driver_sql(
            "SELECT hors_profil_laya, pertinence_laya FROM appels_offre"
        ).one() == (1, 0.12)


def test_drapeaux_stockes_sont_reecrits_cote_laya(base_ancienne):
    with base_ancienne.begin() as conn:
        _migrer(conn)
        drapeaux = json.loads(conn.exec_driver_sql("SELECT drapeaux FROM analyses_krinos").scalar())
    assert drapeaux == ["laya:manipulation", "divergence_laya_pythia", "pythia:manipulation"]


def test_reglages_migres_actif_remis_a_faux_budget_supprime(base_ancienne):
    with base_ancienne.begin() as conn:
        _migrer(conn)
        p = _params(conn)
    assert p["krinos.laya.seuils"] == {"divergence": 30, "confiance": 0.6}
    # Seuil gardé ; l'opt-in est à refaire (Laya est un autre juge).
    assert p["krinos.laya.pretri"] == {"actif": False, "seuil": 0.4}
    assert p["krinos.laya.config"] == {"actif": False}
    assert not [k for k in p if k.startswith("krinos.jev.")]  # anciennes clés + budget supprimés
    assert p["profil.metier"] == {"activite": "ESN"}  # le reste est intact


def test_migration_idempotente(base_ancienne):
    with base_ancienne.begin() as conn:
        _migrer(conn)
        avant = (_params(conn), _colonnes(conn, "analyses_krinos"))
    with base_ancienne.begin() as conn:
        _migrer(conn)
        _migrer(conn)
        assert (_params(conn), _colonnes(conn, "analyses_krinos")) == avant


def test_reglage_laya_deja_present_prime(base_ancienne):
    with base_ancienne.begin() as conn:
        conn.execute(
            text("INSERT INTO parametres (cle, valeur) VALUES ('krinos.laya.seuils', :v)"),
            {"v": json.dumps({"divergence": 10})},
        )
        _migrer(conn)
        p = _params(conn)
    assert p["krinos.laya.seuils"] == {"divergence": 10}
    assert "krinos.jev.seuils" not in p


def test_base_neuve_ou_sans_parametres_demarre():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE analyses_krinos (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE appels_offre (id INTEGER PRIMARY KEY)"))
        _migrer(conn)  # pas de table `parametres` ni d'ancienne colonne : sans effet
        assert {"score_laya", "details_laya"} <= _colonnes(conn, "analyses_krinos")


def test_composite_relit_l_ancienne_cle_poids_jev():
    from sqlmodel import Session

    from hermes.agents.krinos.ponderation import charger_composite
    from hermes.db.models import Parametre
    from hermes.db.session import get_engine, init_db

    init_db()
    with Session(get_engine()) as s:
        s.add(Parametre(
            cle="krinos.composite",
            valeur=json.dumps({"poids_pythia": 40, "poids_jev": 45, "poids_pertinence": 15}),
        ))
        s.commit()
        assert charger_composite(s).poids_laya == 45

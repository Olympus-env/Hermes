"""Issue #15 — statuts, versions uniques, pragmas, dates UTC (MNEMOSYNE / HERMION)."""

import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

from hermes.agents.hermion import writer
from hermes.db.models import AppelOffre, ReponseHermion, StatutAO, StatutReponse
from hermes.db.session import get_engine
from hermes.main import app


def _ao(statut=StatutAO.A_REPONDRE) -> int:
    with Session(get_engine()) as s:
        ao = AppelOffre(url_source="http://x", titre="AO", statut=statut)
        s.add(ao)
        s.commit()
        return ao.id


def _rep(ao_id, statut, version=1) -> int:
    with Session(get_engine()) as s:
        r = ReponseHermion(
            appel_offre_id=ao_id, version=version, contenu="texte", statut=statut
        )
        s.add(r)
        s.commit()
        return r.id


def test_pragmas_sur_chaque_connexion():
    with get_engine().connect() as c1:
        assert c1.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c1.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
    with get_engine().connect() as c2:
        assert c2.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_version_unique_par_ao():
    ao_id = _ao()
    _rep(ao_id, StatutReponse.EN_ATTENTE, version=1)
    with pytest.raises(IntegrityError):
        _rep(ao_id, StatutReponse.EN_ATTENTE, version=1)


def test_rediger_concurrent_renvoie_409():
    ao_id = _ao()
    writer._generations_en_cours.add(ao_id)
    try:
        with TestClient(app) as client:
            r = client.post(f"/hermion/appels-offre/{ao_id}/rediger")
        assert r.status_code == 409
    finally:
        writer._generations_en_cours.discard(ao_id)


def test_verrou_libere_apres_echec():
    ao_id = _ao()
    with Session(get_engine()) as s:
        ao = s.get(AppelOffre, ao_id)
        with pytest.raises(writer.ErreurRedactionHermion):
            asyncio.run(writer.rediger_reponse(s, ao))  # pas d'analyse KRINOS
    assert ao_id not in writer._generations_en_cours


def test_patch_statut_ne_mene_pas_a_exportee():
    ao_id = _ao(StatutAO.EN_REDACTION)
    rep_id = _rep(ao_id, StatutReponse.VALIDEE)
    with TestClient(app) as client:
        r = client.patch(f"/hermion/reponses/{rep_id}/statut", json={"statut": "exportee"})
    assert r.status_code == 409


def test_exportee_peut_repasser_a_modifier():
    ao_id = _ao(StatutAO.REPONDU)
    rep_id = _rep(ao_id, StatutReponse.EXPORTEE)
    with TestClient(app) as client:
        r = client.patch(f"/hermion/reponses/{rep_id}/statut", json={"statut": "a_modifier"})
    assert r.status_code == 200
    assert r.json()["statut"] == "a_modifier"
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).statut == StatutAO.EN_REDACTION


@pytest.mark.parametrize("statut_ao", [StatutAO.REJETE, StatutAO.EXPIRE])
def test_validation_ne_ressuscite_pas_un_ao_ecarte(statut_ao):
    ao_id = _ao(statut_ao)
    rep_id = _rep(ao_id, StatutReponse.EN_ATTENTE)
    with TestClient(app) as client:
        r = client.patch(f"/hermion/reponses/{rep_id}/statut", json={"statut": "validee"})
    assert r.status_code == 200
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).statut == statut_ao


def test_ao_repondu_exige_reponse_validee():
    ao_id = _ao(StatutAO.A_REPONDRE)
    with TestClient(app) as client:
        r = client.patch(f"/appels-offre/{ao_id}/statut", json={"statut": "repondu"})
        assert r.status_code == 409
        _rep(ao_id, StatutReponse.VALIDEE)
        r = client.patch(f"/appels-offre/{ao_id}/statut", json={"statut": "repondu"})
        assert r.status_code == 200


def test_ao_statut_systeme_non_posable():
    ao_id = _ao(StatutAO.A_REPONDRE)
    with TestClient(app) as client:
        for statut in ("brut", "analyse", "en_redaction", "expire", "hors_filtre"):
            r = client.patch(f"/appels-offre/{ao_id}/statut", json={"statut": statut})
            assert r.status_code == 409, statut


@pytest.mark.parametrize(
    "depart",
    [
        StatutAO.EXPIRE,
        StatutAO.HORS_FILTRE,
        StatutAO.REPONDU,
        StatutAO.EN_REDACTION,
        StatutAO.REJETE,
        StatutAO.BRUT,
    ],
)
@pytest.mark.parametrize("cible", ["a_repondre", "rejete"])
def test_ao_gestes_humains_depuis_tout_statut(depart, cible):
    ao_id = _ao(depart)
    with TestClient(app) as client:
        r = client.patch(f"/appels-offre/{ao_id}/statut", json={"statut": cible})
    assert r.status_code == 200
    assert r.json()["statut"] == cible


def test_ao_statut_maj_le_et_dates_utc():
    ao_id = _ao(StatutAO.BRUT)
    with Session(get_engine()) as s:
        avant = s.get(AppelOffre, ao_id).maj_le
    with TestClient(app) as client:
        r = client.patch(f"/appels-offre/{ao_id}/statut", json={"statut": "a_repondre"})
    assert r.status_code == 200
    assert r.json()["maj_le"].endswith("+00:00")
    assert r.json()["cree_le"].endswith("+00:00")
    with Session(get_engine()) as s:
        apres = s.get(AppelOffre, ao_id).maj_le
    assert apres > avant


def test_bornes_pagination():
    with TestClient(app) as client:
        assert client.get("/appels-offre?limit=0").status_code == 422
        assert client.get("/appels-offre?offset=-1").status_code == 422


def test_migration_base_existante_avec_doublons(tmp_path, monkeypatch):
    """Base créée sans contrainte unique, avec versions en double : init_db passe."""
    from hermes.db import session as sess

    eng = create_engine(f"sqlite:///{tmp_path / 'ancienne.db'}")
    SQLModel.metadata.create_all(eng)
    with eng.begin() as c:
        c.exec_driver_sql("DROP INDEX uq_reponses_hermion_ao_version")
        c.exec_driver_sql(
            "INSERT INTO appels_offre (id,url_source,titre,devise,statut,cree_le,maj_le)"
            " VALUES (1,'u','t','EUR','brut','2026-01-01','2026-01-01')"
        )
        for rep_id, version in ((1, 1), (2, 2), (3, 2)):
            c.exec_driver_sql(
                "INSERT INTO reponses_hermion (id,appel_offre_id,version,contenu,statut,"
                "cree_le,maj_le) VALUES (?,1,?,'x','en_attente','2026-01-01','2026-01-01')",
                (rep_id, version),
            )
    monkeypatch.setattr(sess, "_engine", eng)
    sess.init_db()
    sess.init_db()  # idempotent
    with eng.connect() as c:
        versions = sorted(
            r[0] for r in c.exec_driver_sql("SELECT version FROM reponses_hermion")
        )
    assert versions == [1, 2, 3]
    with pytest.raises((IntegrityError, sqlite3.IntegrityError)):
        with eng.begin() as c:
            c.exec_driver_sql(
                "INSERT INTO reponses_hermion (appel_offre_id,version,contenu,statut,"
                "cree_le,maj_le) VALUES (1,1,'x','en_attente','2026','2026')"
            )

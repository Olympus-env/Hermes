"""Tests API pour les appels d'offre."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.db.models import AppelOffre, Portail, StatutAO
from hermes.db.session import get_engine


def test_liste_renvoie_nom_portail():
    from hermes.main import app

    with Session(get_engine()) as session:
        portail = Portail(nom="boamp", url_base="https://www.boamp.fr")
        session.add(portail)
        session.commit()
        session.refresh(portail)

        session.add(
            AppelOffre(
                portail_id=portail.id,
                reference_externe="TEST-001",
                url_source="https://example.test/ao/1",
                titre="AO avec portail",
            )
        )
        session.commit()

    with TestClient(app) as client:
        r = client.get("/appels-offre")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["portail_nom"] == "boamp"


def test_modifie_statut_ao():
    from hermes.main import app

    with Session(get_engine()) as session:
        ao = AppelOffre(
            url_source="https://example.test/ao/2",
            titre="AO à qualifier",
            statut=StatutAO.BRUT,
        )
        session.add(ao)
        session.commit()
        session.refresh(ao)
        ao_id = ao.id

    with TestClient(app) as client:
        r = client.patch(f"/appels-offre/{ao_id}/statut", json={"statut": "a_repondre"})
        assert r.status_code == 200
        assert r.json()["statut"] == "a_repondre"

    with Session(get_engine()) as session:
        rec = session.get(AppelOffre, ao_id)
        assert rec is not None
        assert rec.statut == StatutAO.A_REPONDRE


def test_modifie_statut_ao_introuvable():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.patch("/appels-offre/404/statut", json={"statut": "rejete"})
        assert r.status_code == 404

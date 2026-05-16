"""Tests export PDF des réponses HERMION (tâche V1 #4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.agents.hermion import ErreurExportPdf, exporter_reponse_pdf
from hermes.config import settings
from hermes.db.models import AppelOffre, ReponseHermion, StatutReponse
from hermes.db.session import get_engine, init_db

_CONTENU = (
    "# Réponse — Marché de maintenance\n\n"
    "*Émetteur : Mairie de Test*\n\n"
    "## Compréhension du besoin\n\n"
    "Le présent marché porte sur la maintenance applicative — coût 50 000 €.\n\n"
    "## Méthodologie\n\n"
    "- Phase 1 : cadrage\n"
    "- Phase 2 : **réalisation**\n"
    "- Phase 3 : recette\n"
)


def _reponse(session: Session, statut: StatutReponse) -> int:
    ao = AppelOffre(
        titre="Marché de maintenance",
        emetteur="Mairie de Test",
        reference_externe="26-42",
        url_source="https://example.test/ao",
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    rep = ReponseHermion(
        appel_offre_id=ao.id,
        version=1,
        contenu=_CONTENU,
        statut=statut,
    )
    session.add(rep)
    session.commit()
    session.refresh(rep)
    return rep.id  # type: ignore[return-value]


def test_export_validee_cree_un_pdf():
    init_db()
    with Session(get_engine()) as s:
        rid = _reponse(s, StatutReponse.VALIDEE)

    with Session(get_engine()) as s:
        rep = s.get(ReponseHermion, rid)
        chemin = exporter_reponse_pdf(s, rep)

    assert chemin.is_file()
    assert chemin.read_bytes()[:5] == b"%PDF-"
    with Session(get_engine()) as s:
        rep = s.get(ReponseHermion, rid)
        assert rep.statut == StatutReponse.EXPORTEE
        assert rep.chemin_export == f"exports/reponse_{rid}_v1.pdf"
        # Chemin relatif résolu sous storage/.
        assert (settings.storage_path / rep.chemin_export).is_file()


def test_export_refuse_si_non_validee():
    init_db()
    with Session(get_engine()) as s:
        rid = _reponse(s, StatutReponse.EN_ATTENTE)
        rep = s.get(ReponseHermion, rid)
        with pytest.raises(ErreurExportPdf):
            exporter_reponse_pdf(s, rep)


def test_reexport_si_deja_exportee():
    init_db()
    with Session(get_engine()) as s:
        rid = _reponse(s, StatutReponse.VALIDEE)
        rep = s.get(ReponseHermion, rid)
        exporter_reponse_pdf(s, rep)
    with Session(get_engine()) as s:
        rep = s.get(ReponseHermion, rid)
        assert rep.statut == StatutReponse.EXPORTEE
        # Ré-export autorisé (idempotent).
        chemin = exporter_reponse_pdf(s, rep)
    assert chemin.is_file()


def test_endpoint_exporter_puis_telecharger():
    from hermes.main import app

    init_db()
    with Session(get_engine()) as s:
        rid = _reponse(s, StatutReponse.VALIDEE)

    with TestClient(app) as client:
        # Téléchargement avant export → 404.
        assert client.get(f"/hermion/reponses/{rid}/export").status_code == 404

        r = client.post(f"/hermion/reponses/{rid}/exporter")
        assert r.status_code == 200
        data = r.json()
        assert data["statut"] == "exportee"
        assert data["chemin_export"] == f"exports/reponse_{rid}_v1.pdf"

        dl = client.get(f"/hermion/reponses/{rid}/export")
        assert dl.status_code == 200
        assert dl.headers["content-type"] == "application/pdf"
        assert dl.content[:5] == b"%PDF-"


def test_endpoint_exporter_409_si_non_validee():
    from hermes.main import app

    init_db()
    with Session(get_engine()) as s:
        rid = _reponse(s, StatutReponse.EN_ATTENTE)

    with TestClient(app) as client:
        r = client.post(f"/hermion/reponses/{rid}/exporter")
    assert r.status_code == 409


def test_endpoint_exporter_404_si_inconnue():
    from hermes.main import app

    init_db()
    with TestClient(app) as client:
        assert client.post("/hermion/reponses/999/exporter").status_code == 404

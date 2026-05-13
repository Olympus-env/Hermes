"""Endpoints de santé et d'information système."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from hermes import __version__
from hermes.db.models import Portail
from hermes.db.session import get_session

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """Sonde de vivacité pour le frontend Tauri."""
    return {
        "status": "ok",
        "app": "HERMES",
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/info")
def info(session: Session = Depends(get_session)) -> dict:
    """Info applicative : version, comptes BDD, état général."""
    nb_portails = session.exec(select(Portail)).all()
    return {
        "app": "HERMES",
        "version": __version__,
        "agents": ["ARGOS", "KRINOS", "HERMION"],
        "portails_configures": len(nb_portails),
    }

"""Endpoints REST pour le journal des agents (logs_agents) — consultation UI.

Indispensable pour diagnostiquer le pipeline autonome : ARGOS / KRINOS /
HERMION / HERMES y tracent collectes, analyses, rédactions et erreurs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from hermes.db.models import LogAgent, NiveauLog
from hermes.db.session import get_session

router = APIRouter(prefix="/logs", tags=["logs"])
SessionDep = Annotated[Session, Depends(get_session)]


class LogRead(BaseModel):
    id: int
    agent: str
    niveau: NiveauLog
    message: str
    contexte: str | None
    appel_offre_id: int | None
    portail_id: int | None
    cree_le: datetime


class LogsPage(BaseModel):
    total: int
    items: list[LogRead]
    limit: int
    offset: int


@router.get("", response_model=LogsPage)
def lister_logs(
    session: SessionDep,
    agent: str | None = None,
    niveau: NiveauLog | None = None,
    appel_offre_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LogsPage:
    """Journal filtrable, le plus récent d'abord."""
    base = select(LogAgent)
    if agent:
        base = base.where(LogAgent.agent == agent)
    if niveau is not None:
        base = base.where(LogAgent.niveau == niveau)
    if appel_offre_id is not None:
        base = base.where(LogAgent.appel_offre_id == appel_offre_id)

    total = session.exec(
        select(func.count()).select_from(base.subquery())
    ).one()

    rows = session.exec(
        base.order_by(LogAgent.cree_le.desc()).offset(offset).limit(limit)
    ).all()

    return LogsPage(
        total=int(total),
        items=[
            LogRead(
                id=row.id,  # type: ignore[arg-type]
                agent=row.agent,
                niveau=row.niveau,
                message=row.message,
                contexte=row.contexte,
                appel_offre_id=row.appel_offre_id,
                portail_id=row.portail_id,
                cree_le=row.cree_le,
            )
            for row in rows
        ],
        limit=limit,
        offset=offset,
    )

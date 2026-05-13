"""Routes CRUD basiques pour les appels d'offre (Phase 1 — squelette)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from hermes.db.models import AppelOffre, StatutAO
from hermes.db.session import get_session

router = APIRouter(prefix="/appels-offre", tags=["appels-offre"])


@router.get("")
def lister(
    statut: Optional[StatutAO] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(AppelOffre)
    if statut is not None:
        stmt = stmt.where(AppelOffre.statut == statut)

    total = session.exec(
        select(func.count()).select_from(stmt.subquery())
    ).one()

    stmt = stmt.order_by(AppelOffre.cree_le.desc()).offset(offset).limit(limit)
    items = session.exec(stmt).all()
    return {"total": total, "items": items, "limit": limit, "offset": offset}


@router.get("/{ao_id}")
def detail(ao_id: int, session: Session = Depends(get_session)) -> AppelOffre:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")
    return ao

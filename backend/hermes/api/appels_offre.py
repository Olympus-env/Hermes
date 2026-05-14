"""Routes CRUD basiques pour les appels d'offre."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from hermes.db.models import AppelOffre, Portail, StatutAO
from hermes.db.session import get_session

router = APIRouter(prefix="/appels-offre", tags=["appels-offre"])


class AppelOffreRead(BaseModel):
    id: int
    portail_id: int | None
    portail_nom: str | None
    reference_externe: str | None
    url_source: str
    titre: str
    emetteur: str | None
    objet: str | None
    budget_estime: float | None
    devise: str
    date_publication: datetime | None
    date_limite: datetime | None
    type_marche: str | None
    zone_geographique: str | None
    code_naf: str | None
    statut: StatutAO
    cree_le: datetime
    maj_le: datetime


class AppelsOffrePage(BaseModel):
    total: int
    items: list[AppelOffreRead]
    limit: int
    offset: int


class StatutUpdate(BaseModel):
    statut: StatutAO


@router.get("")
def lister(
    statut: Optional[StatutAO] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
) -> AppelsOffrePage:
    stmt = select(AppelOffre, Portail.nom).join(Portail, isouter=True)
    if statut is not None:
        stmt = stmt.where(AppelOffre.statut == statut)

    total = session.exec(
        select(func.count()).select_from(stmt.subquery())
    ).one()

    stmt = stmt.order_by(AppelOffre.cree_le.desc()).offset(offset).limit(limit)
    rows = session.exec(stmt).all()
    return AppelsOffrePage(
        total=total,
        items=[_ao_read(ao, portail_nom) for ao, portail_nom in rows],
        limit=limit,
        offset=offset,
    )


@router.get("/{ao_id}")
def detail(ao_id: int, session: Session = Depends(get_session)) -> AppelOffreRead:
    row = session.exec(
        select(AppelOffre, Portail.nom)
        .join(Portail, isouter=True)
        .where(AppelOffre.id == ao_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")
    ao, portail_nom = row
    return _ao_read(ao, portail_nom)


@router.patch("/{ao_id}/statut", response_model=AppelOffreRead)
def modifier_statut(
    ao_id: int,
    payload: StatutUpdate,
    session: Session = Depends(get_session),
) -> AppelOffreRead:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")

    ao.statut = payload.statut
    session.add(ao)
    session.commit()
    session.refresh(ao)

    portail_nom = None
    if ao.portail_id is not None:
        portail = session.get(Portail, ao.portail_id)
        portail_nom = portail.nom if portail else None
    return _ao_read(ao, portail_nom)


def _ao_read(ao: AppelOffre, portail_nom: str | None) -> AppelOffreRead:
    return AppelOffreRead(
        id=ao.id,  # type: ignore[arg-type]
        portail_id=ao.portail_id,
        portail_nom=portail_nom,
        reference_externe=ao.reference_externe,
        url_source=ao.url_source,
        titre=ao.titre,
        emetteur=ao.emetteur,
        objet=ao.objet,
        budget_estime=ao.budget_estime,
        devise=ao.devise,
        date_publication=ao.date_publication,
        date_limite=ao.date_limite,
        type_marche=ao.type_marche,
        zone_geographique=ao.zone_geographique,
        code_naf=ao.code_naf,
        statut=ao.statut,
        cree_le=ao.cree_le,
        maj_le=ao.maj_le,
    )

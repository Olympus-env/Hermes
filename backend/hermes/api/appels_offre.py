"""Routes CRUD basiques pour les appels d'offre."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from hermes.agents.krinos.downloader import liens_documents_ao
from hermes.db.models import AnalyseKrinos, AppelOffre, Document, Portail, StatutAO
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
    # Score KRINOS pondéré le plus récent ; None si l'AO n'a jamais été analysé
    # (distinct d'un score réel de 0 — issue #2).
    score: float | None = None
    analyse_disponible: bool = False
    # État documents (Boucle 3) : liens détectés par ARGOS vs fichiers
    # effectivement téléchargés en local. `documents_manquants` = détectés non
    # encore récupérés (best-effort).
    documents_detectes: int = 0
    documents_telecharges: int = 0
    documents_manquants: int = 0


class AppelsOffrePage(BaseModel):
    total: int
    items: list[AppelOffreRead]
    limit: int
    offset: int


class StatutUpdate(BaseModel):
    statut: StatutAO


@router.get("")
def lister(
    statut: StatutAO | None = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
) -> AppelsOffrePage:
    stmt = select(AppelOffre, Portail.nom).join(Portail, isouter=True)
    if statut is not None:
        stmt = stmt.where(AppelOffre.statut == statut)
    else:
        # Par défaut, on masque les AO écartés par les filtres métier (issue #6).
        stmt = stmt.where(AppelOffre.statut != StatutAO.HORS_FILTRE)

    total = session.exec(
        select(func.count()).select_from(stmt.subquery())
    ).one()

    stmt = stmt.order_by(AppelOffre.cree_le.desc()).offset(offset).limit(limit)
    rows = session.exec(stmt).all()
    ao_ids = [ao.id for ao, _ in rows]
    scores = _scores_recents(session, ao_ids)
    docs = _docs_telecharges(session, ao_ids)
    return AppelsOffrePage(
        total=total,
        items=[
            _ao_read(ao, portail_nom, scores.get(ao.id), docs.get(ao.id, 0))
            for ao, portail_nom in rows
        ],
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
    scores = _scores_recents(session, [ao.id])
    docs = _docs_telecharges(session, [ao.id])
    return _ao_read(ao, portail_nom, scores.get(ao.id), docs.get(ao.id, 0))


def _scores_recents(
    session: Session, ao_ids: list[int | None]
) -> dict[int, float]:
    """Score KRINOS le plus récent par AO, pour la liste des ids fournis."""
    ids = [i for i in ao_ids if i is not None]
    if not ids:
        return {}
    lignes = session.exec(
        select(AnalyseKrinos.appel_offre_id, AnalyseKrinos.score)
        .where(AnalyseKrinos.appel_offre_id.in_(ids))
        .order_by(AnalyseKrinos.cree_le.desc())
    ).all()
    scores: dict[int, float] = {}
    for ao_id, score in lignes:
        scores.setdefault(ao_id, score)  # premier = le plus récent (tri desc)
    return scores


def _docs_telecharges(session: Session, ao_ids: list[int | None]) -> dict[int, int]:
    """Nombre de documents téléchargés en local par AO, pour les ids fournis."""
    ids = [i for i in ao_ids if i is not None]
    if not ids:
        return {}
    lignes = session.exec(
        select(Document.appel_offre_id, func.count())
        .where(Document.appel_offre_id.in_(ids))
        .group_by(Document.appel_offre_id)
    ).all()
    return {ao_id: nb for ao_id, nb in lignes}


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
    scores = _scores_recents(session, [ao.id])
    return _ao_read(ao, portail_nom, scores.get(ao.id))


def _ao_read(
    ao: AppelOffre,
    portail_nom: str | None,
    score: float | None = None,
    docs_telecharges: int = 0,
) -> AppelOffreRead:
    detectes = len(liens_documents_ao(ao))
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
        score=score,
        analyse_disponible=score is not None,
        documents_detectes=detectes,
        documents_telecharges=docs_telecharges,
        documents_manquants=max(detectes - docs_telecharges, 0),
    )

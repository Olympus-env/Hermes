"""Endpoints REST pour ARGOS : collecte manuelle, état du scheduler, gestion portails."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from hermes.agents.argos.registry import creer_scraper, scrapers_disponibles
from hermes.agents.argos.runner import executer_collecte
from hermes.agents.argos.scheduler import scheduler_global
from hermes.db.models import Portail, TypePortail
from hermes.db.session import get_session

router = APIRouter(prefix="/argos", tags=["argos"])


class CollecteResponse(BaseModel):
    portail: str
    ao_trouves: int
    ao_nouveaux: int
    ao_dedoublonnes: int
    duree_ms: int
    succes: bool
    erreurs: list[str]


class PortailRead(BaseModel):
    id: int
    nom: str
    url_base: str
    type: TypePortail
    actif: bool
    frequence_minutes: int
    derniere_collecte: str | None


@router.get("/scrapers")
def lister_scrapers() -> dict:
    return {"disponibles": scrapers_disponibles()}


@router.post("/collecter/{portail}", response_model=CollecteResponse)
async def collecter(
    portail: str,
    limite: int = 20,
    session: Session = Depends(get_session),
) -> CollecteResponse:
    """Déclenche une collecte manuelle pour un portail donné."""
    try:
        scraper = creer_scraper(portail)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resultat = await executer_collecte(scraper, session, limite=limite)
    return CollecteResponse(
        portail=resultat.portail,
        ao_trouves=resultat.ao_trouves,
        ao_nouveaux=resultat.ao_nouveaux,
        ao_dedoublonnes=resultat.ao_dedoublonnes,
        duree_ms=resultat.duree_ms,
        succes=resultat.succes,
        erreurs=resultat.erreurs,
    )


@router.get("/scheduler")
def etat_scheduler() -> dict:
    return scheduler_global.etat()


@router.post("/scheduler/sync")
def synchroniser_scheduler() -> dict:
    scheduler_global.synchroniser_jobs()
    return scheduler_global.etat()


@router.get("/portails", response_model=list[PortailRead])
def lister_portails(session: Session = Depends(get_session)) -> list[PortailRead]:
    portails = session.exec(select(Portail).order_by(Portail.nom)).all()
    return [
        PortailRead(
            id=p.id,  # type: ignore[arg-type]
            nom=p.nom,
            url_base=p.url_base,
            type=p.type,
            actif=p.actif,
            frequence_minutes=p.frequence_minutes,
            derniere_collecte=p.derniere_collecte.isoformat() if p.derniere_collecte else None,
        )
        for p in portails
    ]

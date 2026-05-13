"""Endpoints REST pour ARGOS : collecte manuelle, état du scheduler, gestion portails."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from hermes.agents.argos.registry import creer_scraper, scrapers_disponibles
from hermes.agents.argos.runner import executer_collecte
from hermes.agents.argos.scheduler import scheduler_global
from hermes.db.models import Portail, TypePortail
from hermes.db.session import get_session
from hermes.securite.credentials import chiffrer_credentials

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
    credentials_configures: bool


class PortailUpsert(BaseModel):
    url_base: str
    type: TypePortail = TypePortail.PUBLIC
    actif: bool = True
    frequence_minutes: int = Field(default=360, ge=5)
    config_scraping: str | None = None


class CredentialsWrite(BaseModel):
    credentials: dict[str, str] = Field(min_length=1)


class MessageResponse(BaseModel):
    message: str


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
            credentials_configures=p.credentials_chiffres is not None,
        )
        for p in portails
    ]


@router.put("/portails/{nom}", response_model=PortailRead)
def enregistrer_portail(
    nom: str,
    payload: PortailUpsert,
    session: Session = Depends(get_session),
) -> PortailRead:
    """Crée ou met à jour la configuration d'un portail ARGOS."""
    portail = session.exec(select(Portail).where(Portail.nom == nom)).first()
    if portail is None:
        portail = Portail(nom=nom, url_base=payload.url_base)

    portail.url_base = payload.url_base
    portail.type = payload.type
    portail.actif = payload.actif
    portail.frequence_minutes = payload.frequence_minutes
    portail.config_scraping = payload.config_scraping

    session.add(portail)
    session.commit()
    session.refresh(portail)
    scheduler_global.synchroniser_jobs()

    return _portail_read(portail)


@router.put("/portails/{nom}/credentials", response_model=MessageResponse)
def enregistrer_credentials(
    nom: str,
    payload: CredentialsWrite,
    session: Session = Depends(get_session),
) -> MessageResponse:
    """Enregistre les credentials chiffrés d'un portail privé.

    Les valeurs en clair ne sont jamais renvoyées par l'API.
    """
    portail = session.exec(select(Portail).where(Portail.nom == nom)).first()
    if portail is None:
        raise HTTPException(status_code=404, detail="Portail introuvable")

    portail.credentials_chiffres = chiffrer_credentials(payload.credentials)
    portail.type = TypePortail.PRIVE
    session.add(portail)
    session.commit()
    return MessageResponse(message="Credentials enregistrés")


@router.delete("/portails/{nom}/credentials", response_model=MessageResponse)
def supprimer_credentials(
    nom: str,
    session: Session = Depends(get_session),
) -> MessageResponse:
    """Supprime les credentials chiffrés d'un portail."""
    portail = session.exec(select(Portail).where(Portail.nom == nom)).first()
    if portail is None:
        raise HTTPException(status_code=404, detail="Portail introuvable")

    portail.credentials_chiffres = None
    session.add(portail)
    session.commit()
    return MessageResponse(message="Credentials supprimés")


def _portail_read(portail: Portail) -> PortailRead:
    return PortailRead(
        id=portail.id,  # type: ignore[arg-type]
        nom=portail.nom,
        url_base=portail.url_base,
        type=portail.type,
        actif=portail.actif,
        frequence_minutes=portail.frequence_minutes,
        derniere_collecte=portail.derniere_collecte.isoformat()
        if portail.derniere_collecte
        else None,
        credentials_configures=portail.credentials_chiffres is not None,
    )

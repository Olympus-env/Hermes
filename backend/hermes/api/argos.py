"""Endpoints REST pour ARGOS : collecte manuelle, état du scheduler, gestion portails."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from hermes.agents import pythia
from hermes.agents.argos.filtre import (
    FiltreVeille,
    charger_filtre,
    enregistrer_filtre,
    suggerer_mots_cles,
)
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
    ao_filtres: int = 0
    duree_ms: int
    succes: bool
    erreurs: list[str]


class CycleCollecteResponse(BaseModel):
    resultats: list[CollecteResponse]
    ao_trouves: int
    ao_nouveaux: int
    ao_dedoublonnes: int
    ao_filtres: int = 0
    succes: bool


class FiltreVeilleIO(BaseModel):
    inclus: list[str] = Field(default_factory=list)
    exclus: list[str] = Field(default_factory=list)
    actif: bool = False


class SuggestionRequest(BaseModel):
    entreprise: str = ""
    activite: str = ""
    infos: str = ""


class SuggestionResponse(BaseModel):
    inclus: list[str]
    exclus: list[str]
    raisonnement: str


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


@router.post("/collecter", response_model=CycleCollecteResponse)
async def collecter_tous(
    limite: int = 20,
    session: Session = Depends(get_session),
) -> CycleCollecteResponse:
    """Déclenche un cycle ARGOS sur tous les scrapers enregistrés."""
    resultats: list[CollecteResponse] = []
    for nom in scrapers_disponibles():
        scraper = creer_scraper(nom)
        resultat = await executer_collecte(scraper, session, limite=limite)
        resultats.append(
            CollecteResponse(
                portail=resultat.portail,
                ao_trouves=resultat.ao_trouves,
                ao_nouveaux=resultat.ao_nouveaux,
                ao_dedoublonnes=resultat.ao_dedoublonnes,
                ao_filtres=resultat.ao_filtres,
                duree_ms=resultat.duree_ms,
                succes=resultat.succes,
                erreurs=resultat.erreurs,
            )
        )

    return CycleCollecteResponse(
        resultats=resultats,
        ao_trouves=sum(r.ao_trouves for r in resultats),
        ao_nouveaux=sum(r.ao_nouveaux for r in resultats),
        ao_dedoublonnes=sum(r.ao_dedoublonnes for r in resultats),
        ao_filtres=sum(r.ao_filtres for r in resultats),
        succes=all(r.succes for r in resultats),
    )


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
        ao_filtres=resultat.ao_filtres,
        duree_ms=resultat.duree_ms,
        succes=resultat.succes,
        erreurs=resultat.erreurs,
    )


@router.get("/filtre", response_model=FiltreVeilleIO)
def lire_filtre(session: Session = Depends(get_session)) -> FiltreVeilleIO:
    """Retourne le filtre mots-clés appliqué aux collectes ARGOS."""
    filtre = charger_filtre(session)
    return FiltreVeilleIO(
        inclus=list(filtre.inclus),
        exclus=list(filtre.exclus),
        actif=filtre.actif,
    )


@router.put("/filtre", response_model=FiltreVeilleIO)
def ecrire_filtre(
    payload: FiltreVeilleIO,
    session: Session = Depends(get_session),
) -> FiltreVeilleIO:
    """Met à jour le filtre mots-clés. Les listes sont normalisées et dédupliquées."""
    nettoye = enregistrer_filtre(
        session,
        FiltreVeille(inclus=tuple(payload.inclus), exclus=tuple(payload.exclus)),
    )
    return FiltreVeilleIO(
        inclus=list(nettoye.inclus),
        exclus=list(nettoye.exclus),
        actif=nettoye.actif,
    )


@router.post("/filtre/suggerer", response_model=SuggestionResponse)
async def suggerer_filtre(payload: SuggestionRequest) -> SuggestionResponse:
    """Suggère des mots-clés inclus/exclus via PYTHIA à partir du profil entreprise.

    N'enregistre rien — l'utilisateur valide et soumet via PUT /argos/filtre.
    """
    try:
        suggestion = await suggerer_mots_cles(
            entreprise=payload.entreprise,
            activite=payload.activite,
            infos=payload.infos,
        )
    except pythia.ErreurPythia as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SuggestionResponse(
        inclus=list(suggestion.inclus),
        exclus=list(suggestion.exclus),
        raisonnement=suggestion.raisonnement,
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

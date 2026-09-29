"""Analyse concurrentielle d'un AO à partir des DECP (open data)."""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sqlmodel import Session

from hermes.agents.argos import decp
from hermes.agents.argos.boamp import recuperer_identifiants
from hermes.api._dates import DatetimeUTC
from hermes.db.models import AppelOffre, Portail
from hermes.db.session import get_session

router = APIRouter(prefix="/appels-offre", tags=["concurrence"])

# Cache négatif du rattrapage BOAMP : un AO dont l'avis n'expose ni SIRET ni CPV
# n'est pas relu à chaque consultation (24 h, mémoire du process).
_RATTRAPAGE_TTL_S = 24 * 3600
_rattrapages_vides: dict[int, float] = {}


class TitulaireRecurrent(BaseModel):
    nom: str
    siret: str | None
    nb_marches: int
    montant_total: float
    part: float


class TendanceMarches(BaseModel):
    sens: str  # hausse | baisse | stable | indeterminee
    # False : échantillon plafonné ne couvrant pas la période précédente.
    precedent_couvert: bool = True
    nb_recent: int
    nb_precedent: int
    montant_median_recent: float | None
    montant_median_precedent: float | None


class MarcheRecent(BaseModel):
    date: str | None
    titulaire: str | None
    montant: float | None
    objet: str | None
    offres: int | None


class AnalyseConcurrence(BaseModel):
    nb_marches: int
    montant_median: float | None
    montant_total: float | None
    offres_moyennes: float | None
    titulaires: list[TitulaireRecurrent]
    tendance: TendanceMarches
    marches_recents: list[MarcheRecent]
    periode_annees: int
    echantillon_plafonne: bool
    # Total réel annoncé par l'API (peut dépasser l'échantillon) et période
    # effectivement couverte quand l'échantillon est plafonné.
    total_reel: int | None = None
    periode_debut: str | None = None
    periode_fin: str | None = None


class ConcurrenceRead(BaseModel):
    siret: str | None
    cpv: str | None
    # Historique du même acheteur (SIRET) et du même secteur (groupe CPV).
    acheteur: AnalyseConcurrence | None
    secteur: AnalyseConcurrence | None
    maj_le: DatetimeUTC | None
    depuis_cache: bool
    # Motif lisible quand un bloc manque (identifiant absent, source en panne).
    message: str | None = None


@router.get("/{ao_id}/concurrence", response_model=ConcurrenceRead)
async def concurrence(
    ao_id: int,
    actualiser: bool = Query(default=False, description="Ignore le cache (TTL 24 h)"),
    session: Session = Depends(get_session),
) -> ConcurrenceRead:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")

    await _rattraper_identifiants(session, ao)
    cpv = ao.code_cpv or decp._cpv_valide(ao.code_naf)  # TED stocke le CPV dans code_naf

    if not ao.emetteur_siret and not cpv:
        return ConcurrenceRead(
            siret=None, cpv=None, acheteur=None, secteur=None, maj_le=None,
            depuis_cache=False,
            message="SIRET acheteur et CPV inconnus pour cet appel d'offre : "
            "historique DECP non calculable.",
        )

    try:
        res = await decp.concurrence(
            session, siret=ao.emetteur_siret, cpv=cpv, forcer=actualiser
        )
    except decp.DecpIndisponible as exc:
        logger.warning("DECP indisponible pour AO {} : {}", ao_id, exc)
        return ConcurrenceRead(
            siret=ao.emetteur_siret, cpv=cpv, acheteur=None, secteur=None, maj_le=None,
            depuis_cache=False,
            message="Source DECP (data.gouv.fr) indisponible, réessayez plus tard.",
        )

    message = res["erreur"]
    if not ao.emetteur_siret:
        message = message or (
            "SIRET acheteur inconnu : seul l'historique du secteur (CPV) est affiché."
        )
    return ConcurrenceRead(
        siret=ao.emetteur_siret, cpv=cpv,
        acheteur=res["acheteur"], secteur=res["secteur"],
        maj_le=res["maj_le"], depuis_cache=res["depuis_cache"], message=message,
    )


async def _rattraper_identifiants(session: Session, ao: AppelOffre) -> None:
    """AO BOAMP collecté avant l'ajout du SIRET/CPV : relit l'avis (lecture seule)."""
    if ao.emetteur_siret or ao.code_cpv or not ao.reference_externe or not ao.portail_id:
        return
    tente = _rattrapages_vides.get(ao.id or 0)
    if tente is not None and time.monotonic() - tente < _RATTRAPAGE_TTL_S:
        return
    portail = session.get(Portail, ao.portail_id)
    if portail is None or portail.nom.lower() != "boamp":
        return
    try:
        siret, cpv = await recuperer_identifiants(ao.reference_externe)
    except httpx.HTTPError as exc:
        logger.warning("Rattrapage SIRET BOAMP impossible pour AO {} : {}", ao.id, exc)
        return
    if not (siret or cpv):
        _rattrapages_vides[ao.id or 0] = time.monotonic()
    if siret or cpv:
        ao.emetteur_siret = siret
        ao.code_cpv = cpv
        session.add(ao)
        session.commit()

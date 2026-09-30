"""Endpoints REST pour le juge Laya de KRINOS : réglages, seuils, modèle local.

Laya tourne dans le process backend (ONNX Runtime) : aucune clé, aucun budget.
Ses poids (~644 Mo en fp16) ne sont téléchargés qu'après consentement explicite
(`confirme: true`), avec un état de progression partagé en mémoire suivi par
polling, comme PYTHIA. Rien n'est lancé au démarrage.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from hermes.agents.krinos import laya, laya_modele
from hermes.agents.krinos.laya_moteur import TEMPERATURE_MAX, TEMPERATURE_MIN
from hermes.config import settings
from hermes.db.session import get_session

router = APIRouter(prefix="/krinos/laya", tags=["krinos", "laya"])

SessionDep = Annotated[Session, Depends(get_session)]
EtatDep = Annotated[laya_modele.EtatTelechargement, Depends(laya_modele.etat_global)]


class ProgressionLayaIO(BaseModel):
    precision: str
    en_cours: bool
    statut: str
    fichier: str
    octets_telecharges: int
    octets_total: int
    pourcent: float
    erreur: str | None
    termine_le: float | None


class ModeleLayaIO(BaseModel):
    precision: str
    installe: bool
    manquants: list[str]
    taille_octets: int  # à télécharger pour cette précision
    dossier: str
    espace_disque_libre_octets: int
    progression: ProgressionLayaIO


class ConfigLayaIO(BaseModel):
    actif: bool  # voulu par l'utilisateur
    operationnel: bool  # voulu ET poids installés
    precision: str
    temperature: float
    max_tokens: int
    pretri_actif: bool = False
    pretri_seuil: float = laya.SEUIL_PRETRI_DEFAUT
    modele: ModeleLayaIO


class ConfigLayaUpdate(BaseModel):
    actif: bool | None = None
    temperature: float | None = Field(
        default=None, ge=TEMPERATURE_MIN, le=TEMPERATURE_MAX, allow_inf_nan=False
    )
    precision: str | None = None


class PretriLayaUpdate(BaseModel):
    pretri_actif: bool
    pretri_seuil: float = Field(default=laya.SEUIL_PRETRI_DEFAUT, ge=0, le=1)


class SeuilsLayaIO(BaseModel):
    divergence: float = Field(default=laya.SEUIL_DIVERGENCE, gt=0, le=100, allow_inf_nan=False)
    manipulation: float = Field(default=laya.SEUIL_MANIPULATION, ge=0, le=1, allow_inf_nan=False)
    pertinence: float = Field(default=laya.SEUIL_PERTINENCE, ge=0, le=1, allow_inf_nan=False)
    confiance: float = Field(default=laya.SEUIL_CONFIANCE, ge=0, le=1, allow_inf_nan=False)


class TelechargementLayaRequest(BaseModel):
    # Consentement explicite : aucun téléchargement sans `confirme: true`.
    precision: str = laya_modele.PRECISION_DEFAUT
    confirme: bool = False


def _progression(etat: laya_modele.EtatTelechargement) -> ProgressionLayaIO:
    pourcent = 0.0
    if etat.octets_total > 0:
        pourcent = min(100.0, 100.0 * etat.octets_telecharges / etat.octets_total)
    return ProgressionLayaIO(
        precision=etat.precision,
        en_cours=etat.en_cours,
        statut=etat.statut,
        fichier=etat.fichier,
        octets_telecharges=etat.octets_telecharges,
        octets_total=etat.octets_total,
        pourcent=round(pourcent, 1),
        erreur=etat.erreur,
        termine_le=etat.termine_le,
    )


def _modele_io(precision: str, etat: laya_modele.EtatTelechargement) -> ModeleLayaIO:
    statut = laya_modele.statut_modele(precision)
    dossier = laya_modele.dossier_modele()
    # Espace libre du plus proche dossier existant (le dossier du modèle peut ne pas
    # exister encore : on ne le crée pas juste pour lire l'état).
    parent = dossier
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return ModeleLayaIO(
        precision=statut.precision,
        installe=statut.installe or laya._moteur is not None,
        manquants=statut.manquants,
        taille_octets=statut.taille_octets,
        dossier=statut.dossier,
        espace_disque_libre_octets=shutil.disk_usage(parent).free,
        progression=_progression(etat),
    )


def _config_io(session: Session, etat: laya_modele.EtatTelechargement) -> ConfigLayaIO:
    precision = laya.precision(session)
    return ConfigLayaIO(
        actif=laya.reglage_actif(session),
        operationnel=laya.est_actif(session),
        precision=precision,
        temperature=laya.temperature(session),
        max_tokens=settings.laya_max_tokens,
        pretri_actif=laya.pretri_reglage(session),
        pretri_seuil=laya.pretri_seuil(session),
        modele=_modele_io(precision, etat),
    )


@router.get("", response_model=ConfigLayaIO)
def lire_config_laya(session: SessionDep, etat: EtatDep) -> ConfigLayaIO:
    return _config_io(session, etat)


@router.put("", response_model=ConfigLayaIO)
def ecrire_config_laya(
    payload: ConfigLayaUpdate, session: SessionDep, etat: EtatDep
) -> ConfigLayaIO:
    if payload.precision is not None and payload.precision not in laya_modele.PRECISIONS:
        raise HTTPException(status_code=422, detail="Précision inconnue (fp16 ou fp32).")
    laya.enregistrer_config(
        session,
        actif=payload.actif,
        temperature_calibration=payload.temperature,
        precision_poids=payload.precision,
    )
    return _config_io(session, etat)


@router.put("/pretri", response_model=ConfigLayaIO)
def ecrire_pretri_laya(
    payload: PretriLayaUpdate, session: SessionDep, etat: EtatDep
) -> ConfigLayaIO:
    laya.enregistrer_pretri(session, payload.pretri_actif, payload.pretri_seuil)
    return _config_io(session, etat)


@router.get("/seuils", response_model=SeuilsLayaIO)
def lire_seuils_laya(session: SessionDep) -> SeuilsLayaIO:
    return SeuilsLayaIO(**laya.charger_seuils(session).en_dict())


@router.put("/seuils", response_model=SeuilsLayaIO)
def ecrire_seuils_laya(payload: SeuilsLayaIO, session: SessionDep) -> SeuilsLayaIO:
    laya.enregistrer_seuils(session, laya.SeuilsLaya(**payload.model_dump()))
    return payload


# --------------------------------------------------------------------------- #
# Modèle local : état, téléchargement consenti, annulation
# --------------------------------------------------------------------------- #


@router.get("/modele", response_model=ModeleLayaIO)
def statut_modele_laya(session: SessionDep, etat: EtatDep) -> ModeleLayaIO:
    return _modele_io(laya.precision(session), etat)


@router.post("/modele/telecharger", response_model=ProgressionLayaIO)
async def lancer_telechargement_laya(
    payload: TelechargementLayaRequest, etat: EtatDep
) -> ProgressionLayaIO:
    """Démarre le téléchargement en tâche de fond. Exige `confirme: true`.

    Idempotent : si un téléchargement est déjà en cours, renvoie son état."""
    if not payload.confirme:
        raise HTTPException(
            status_code=400,
            detail="Téléchargement non confirmé : `confirme` doit valoir true.",
        )
    if payload.precision not in laya_modele.PRECISIONS:
        raise HTTPException(status_code=422, detail="Précision inconnue (fp16 ou fp32).")
    async with etat._lock:
        if etat.en_cours:
            return _progression(etat)
        etat.precision = payload.precision
        etat.en_cours = True
        etat.statut = "demarrage"
        etat.fichier = ""
        etat.octets_telecharges = 0
        etat.octets_total = laya_modele.taille_totale(payload.precision)
        etat.erreur = None
        etat.termine_le = None
    etat._tache = asyncio.create_task(
        laya_modele.executer_telechargement(etat, payload.precision)
    )
    return _progression(etat)


@router.post("/modele/annuler", response_model=ProgressionLayaIO)
async def annuler_telechargement_laya(etat: EtatDep) -> ProgressionLayaIO:
    """Annule le téléchargement en cours (le fichier partiel est repris au prochain essai)."""
    tache = etat._tache
    if etat.en_cours and tache is not None and not tache.done():
        tache.cancel()
        try:
            await tache
        except asyncio.CancelledError:
            pass
    return _progression(etat)

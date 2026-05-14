"""Endpoints REST pour PYTHIA — gestion des modèles Ollama.

Ces routes permettent au frontend de vérifier qu'un modèle est installé
localement et de lancer son téléchargement (Mistral 7B ~4,4 Go) avec un
état partagé en mémoire pour suivre la progression via polling.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hermes.agents import pythia
from hermes.config import settings

router = APIRouter(prefix="/pythia", tags=["pythia"])


# --------------------------------------------------------------------------- #
# État partagé (singleton in-memory)
# --------------------------------------------------------------------------- #


@dataclass
class EtatTelechargement:
    modele: str = ""
    en_cours: bool = False
    statut: str = ""
    octets_telecharges: int = 0
    octets_total: int = 0
    erreur: str | None = None
    termine_le: float | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_etat = EtatTelechargement()


def etat_global() -> EtatTelechargement:
    return _etat


EtatDep = Annotated[EtatTelechargement, Depends(etat_global)]


# --------------------------------------------------------------------------- #
# Schémas API
# --------------------------------------------------------------------------- #


class ProgressionRead(BaseModel):
    modele: str
    en_cours: bool
    statut: str
    octets_telecharges: int
    octets_total: int
    pourcent: float
    erreur: str | None
    termine_le: float | None


class StatutModeleResponse(BaseModel):
    modele: str
    installe: bool
    ollama_disponible: bool
    progression: ProgressionRead


class TelechargementRequest(BaseModel):
    modele: str | None = None


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/modele/status", response_model=StatutModeleResponse)
async def statut_modele(etat: EtatDep) -> StatutModeleResponse:
    modele_demande = etat.modele or settings.pythia_modele
    ollama_ok = await pythia.est_disponible(timeout=2.0)
    installe = False
    if ollama_ok:
        try:
            installe = await pythia.modele_installe(modele_demande)
        except pythia.ErreurPythia:
            installe = False

    return StatutModeleResponse(
        modele=modele_demande,
        installe=installe,
        ollama_disponible=ollama_ok,
        progression=_progression_read(etat),
    )


@router.post("/modele/telecharger", response_model=ProgressionRead)
async def lancer_telechargement(
    etat: EtatDep,
    payload: TelechargementRequest | None = None,
) -> ProgressionRead:
    """Démarre le téléchargement du modèle en tâche de fond.

    Idempotent : si un téléchargement est déjà en cours, renvoie son état
    actuel sans en lancer un nouveau.
    """
    modele = (payload.modele if payload else None) or settings.pythia_modele

    async with etat._lock:
        if etat.en_cours:
            return _progression_read(etat)

        if not await pythia.est_disponible(timeout=2.0):
            raise HTTPException(
                status_code=502,
                detail="Ollama/PYTHIA n'est pas joignable sur 127.0.0.1:11434.",
            )

        # Réinitialise l'état pour ce nouveau téléchargement
        etat.modele = modele
        etat.en_cours = True
        etat.statut = "demarrage"
        etat.octets_telecharges = 0
        etat.octets_total = 0
        etat.erreur = None
        etat.termine_le = None

    # Lance la tâche en arrière-plan, ne pas await ici.
    asyncio.create_task(_executer_telechargement(etat, modele))
    return _progression_read(etat)


async def _executer_telechargement(etat: EtatTelechargement, modele: str) -> None:
    try:
        async for evt in pythia.telecharger_modele(modele):
            statut = str(evt.get("status") or "").lower()
            etat.statut = statut[:120]
            completed = evt.get("completed")
            total = evt.get("total")
            if isinstance(total, int) and total > 0:
                etat.octets_total = total
            if isinstance(completed, int) and completed >= 0:
                etat.octets_telecharges = completed
        # Fin du stream sans erreur → succès
        etat.statut = "success"
        if etat.octets_total > 0:
            etat.octets_telecharges = etat.octets_total
        etat.termine_le = time.time()
    except pythia.ErreurPythia as exc:
        etat.erreur = str(exc)
        etat.statut = "erreur"
    except Exception as exc:  # noqa: BLE001 — on capture tout pour ne pas geler l'état
        etat.erreur = f"Erreur inattendue : {exc}"
        etat.statut = "erreur"
    finally:
        etat.en_cours = False


def _progression_read(etat: EtatTelechargement) -> ProgressionRead:
    pourcent = 0.0
    if etat.octets_total > 0:
        pourcent = min(100.0, 100.0 * etat.octets_telecharges / etat.octets_total)
    return ProgressionRead(
        modele=etat.modele or settings.pythia_modele,
        en_cours=etat.en_cours,
        statut=etat.statut,
        octets_telecharges=etat.octets_telecharges,
        octets_total=etat.octets_total,
        pourcent=round(pourcent, 1),
        erreur=etat.erreur,
        termine_le=etat.termine_le,
    )

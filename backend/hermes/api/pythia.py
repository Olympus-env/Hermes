"""Endpoints REST pour PYTHIA — gestion des modèles Ollama.

Ces routes permettent au frontend de vérifier qu'un modèle est installé
localement et de lancer son téléchargement (Qwen3 8B ~5,2 Go) avec un
état partagé en mémoire pour suivre la progression via polling.
"""

from __future__ import annotations

import asyncio
import shutil
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
    _tache: asyncio.Task | None = None


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
    # Consentement explicite : aucun téléchargement sans `confirme: true`.
    modele: str
    confirme: bool = False


class ChoixModeleRequest(BaseModel):
    modele: str


class ModelePropose(BaseModel):
    nom: str
    taille_octets: int  # indicative (pas de consultation du registre Ollama)
    installe: bool


class OptionsModelesResponse(BaseModel):
    modele_actuel: str
    proposes: list[ModelePropose]
    installes: list[str]
    espace_disque_libre_octets: int
    modele_libre: bool


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


@router.get("/modele/options", response_model=OptionsModelesResponse)
async def options_modeles() -> OptionsModelesResponse:
    """Modèles proposés (liste blanche) et modèles déjà installés dans Ollama."""
    installes: list[str] = []
    if await pythia.est_disponible(timeout=2.0):
        try:
            installes = await pythia.lister_modeles()
        except pythia.ErreurPythia:
            installes = []
    proposes = [
        ModelePropose(
            nom=nom,
            taille_octets=taille,
            installe=any(_meme_modele(nom, i) for i in installes),
        )
        for nom, taille in settings.pythia_modeles_proposes.items()
    ]
    dossier = settings.db_path.parent
    dossier.mkdir(parents=True, exist_ok=True)
    return OptionsModelesResponse(
        modele_actuel=settings.pythia_modele,
        proposes=proposes,
        installes=installes,
        espace_disque_libre_octets=shutil.disk_usage(dossier).free,
        modele_libre=settings.pythia_modele_libre,
    )


@router.post("/modele/choisir", response_model=StatutModeleResponse)
async def choisir_modele(payload: ChoixModeleRequest, etat: EtatDep) -> StatutModeleResponse:
    """Utilise un modèle DÉJÀ installé, sans rien télécharger (effet jusqu'au redémarrage)."""
    if not await pythia.est_disponible(timeout=2.0):
        raise HTTPException(status_code=502, detail="Ollama/PYTHIA n'est pas joignable.")
    if not await pythia.modele_installe(payload.modele):
        raise HTTPException(status_code=404, detail="Ce modèle n'est pas installé dans Ollama.")
    settings.pythia_modele = payload.modele
    etat.modele = payload.modele
    return await statut_modele(etat)


@router.post("/modele/telecharger", response_model=ProgressionRead)
async def lancer_telechargement(
    payload: TelechargementRequest,
    etat: EtatDep,
) -> ProgressionRead:
    """Démarre le téléchargement du modèle en tâche de fond.

    Exige `confirme: true` et un modèle de la liste blanche (sauf option
    avancée `pythia_modele_libre`). Idempotent : si un téléchargement est déjà
    en cours, renvoie son état actuel sans en lancer un nouveau.
    """
    if not payload.confirme:
        raise HTTPException(
            status_code=400,
            detail="Téléchargement non confirmé : `confirme` doit valoir true.",
        )
    modele = payload.modele.strip()
    if not modele:
        raise HTTPException(status_code=422, detail="Nom de modèle vide.")
    if modele not in settings.pythia_modeles_proposes and not settings.pythia_modele_libre:
        raise HTTPException(
            status_code=403,
            detail="Modèle hors de la liste proposée (option avancée désactivée).",
        )

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
    etat._tache = asyncio.create_task(_executer_telechargement(etat, modele))
    return _progression_read(etat)


@router.post("/modele/annuler", response_model=ProgressionRead)
async def annuler_telechargement(etat: EtatDep) -> ProgressionRead:
    """Annule le téléchargement en cours (Ollama reprendra les blobs déjà reçus)."""
    tache = etat._tache
    if etat.en_cours and tache is not None and not tache.done():
        tache.cancel()
        try:
            await tache
        except asyncio.CancelledError:
            pass
    return _progression_read(etat)


def _meme_modele(a: str, b: str) -> bool:
    def norm(n: str) -> str:
        return n if ":" in n else f"{n}:latest"

    return norm(a) == norm(b)


async def _executer_telechargement(etat: EtatTelechargement, modele: str) -> None:
    try:
        async for evt in pythia.telecharger_modele(modele):
            erreur = evt.get("error")
            if erreur:
                raise pythia.ErreurPythia(str(erreur))
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
    except asyncio.CancelledError:
        etat.statut = "annule"
        etat.erreur = None
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

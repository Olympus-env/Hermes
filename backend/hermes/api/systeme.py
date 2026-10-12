"""Endpoints système MNEMOSYNE : sauvegarde immédiate de la BDD (CDC §8.2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from hermes.db.retention import sauvegarder_maintenant
from hermes.db.session import get_session

router = APIRouter(prefix="/systeme", tags=["systeme"])
SessionDep = Annotated[Session, Depends(get_session)]


class SauvegardeRead(BaseModel):
    chemin: str
    taille_octets: int
    supprimees: list[str]
    avertissements: list[str]


@router.post("/sauvegarder", response_model=SauvegardeRead)
def sauvegarder(session: SessionDep) -> SauvegardeRead:
    try:
        res = sauvegarder_maintenant(session)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Sauvegarde impossible : {exc}") from exc
    return SauvegardeRead(
        chemin=str(res.chemin),
        taille_octets=res.taille_octets,
        supprimees=res.supprimees,
        avertissements=res.avertissements,
    )

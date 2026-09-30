"""Routes du profil métier structuré (MNEMOSYNE `parametres`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from hermes.agents.profil_metier import (
    ProfilMetier,
    charger_profil,
    enregistrer_profil,
)
from hermes.db.session import get_session

router = APIRouter(prefix="/profil", tags=["profil"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/metier", response_model=ProfilMetier)
def lire_profil_metier(session: SessionDep) -> ProfilMetier:
    return charger_profil(session)


@router.put("/metier", response_model=ProfilMetier)
def ecrire_profil_metier(profil: ProfilMetier, session: SessionDep) -> ProfilMetier:
    return enregistrer_profil(session, profil)

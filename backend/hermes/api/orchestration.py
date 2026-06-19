"""Endpoints REST pour l'orchestrateur — pipeline autonome ARGOS→KRINOS→HERMION."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from hermes.agents.orchestrateur import (
    ConfigOrchestration,
    charger_config,
    enregistrer_config,
    traiter_pipeline,
)
from hermes.db.session import get_session

router = APIRouter(prefix="/orchestration", tags=["orchestration"])
SessionDep = Annotated[Session, Depends(get_session)]


class ConfigIO(BaseModel):
    actif: bool = True
    seuil_score: float = Field(default=70.0, ge=0, le=100)
    auto_rediger: bool = True
    max_par_cycle: int = Field(default=5, ge=1, le=50)


class RapportIO(BaseModel):
    actif: bool
    ao_analyses: int
    ao_rediges: int
    ao_sous_seuil: int
    ao_echecs: int
    details: list[dict]


@router.get("/config", response_model=ConfigIO)
def lire_config(session: SessionDep) -> ConfigIO:
    return _config_io(charger_config(session))


@router.put("/config", response_model=ConfigIO)
def ecrire_config(payload: ConfigIO, session: SessionDep) -> ConfigIO:
    nettoye = enregistrer_config(
        session,
        ConfigOrchestration(
            actif=payload.actif,
            seuil_score=payload.seuil_score,
            auto_rediger=payload.auto_rediger,
            max_par_cycle=payload.max_par_cycle,
        ),
    )
    return _config_io(nettoye)


@router.post("/traiter", response_model=RapportIO)
async def traiter(
    session: SessionDep,
    limite: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> RapportIO:
    """Déclenche un passage du pipeline à la demande (sinon : scheduler ARGOS)."""
    rapport = await traiter_pipeline(session, limite=limite)
    return RapportIO(
        actif=rapport.actif,
        ao_analyses=rapport.ao_analyses,
        ao_rediges=rapport.ao_rediges,
        ao_sous_seuil=rapport.ao_sous_seuil,
        ao_echecs=rapport.ao_echecs,
        details=rapport.details,
    )


def _config_io(cfg: ConfigOrchestration) -> ConfigIO:
    return ConfigIO(
        actif=cfg.actif,
        seuil_score=cfg.seuil_score,
        auto_rediger=cfg.auto_rediger,
        max_par_cycle=cfg.max_par_cycle,
    )

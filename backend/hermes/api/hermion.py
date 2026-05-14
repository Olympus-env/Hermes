"""Endpoints REST pour HERMION : rédaction et gestion des versions de réponse."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from hermes.agents.hermion import (
    ErreurRedactionHermion,
    ProfilUtilisateur,
    rediger_reponse,
)
from hermes.db.models import AppelOffre, ReponseHermion, StatutAO, StatutReponse
from hermes.db.session import get_session

router = APIRouter(prefix="/hermion", tags=["hermion"])
SessionDep = Annotated[Session, Depends(get_session)]


class ProfilRequest(BaseModel):
    prenom: str = ""
    nom: str = ""
    email: str = ""
    entreprise: str = ""
    activite: str = ""


class RedactionRequest(BaseModel):
    profil: ProfilRequest | None = None
    consignes: str | None = None


class ReponseRead(BaseModel):
    id: int
    appel_offre_id: int
    version: int
    statut: StatutReponse
    contenu: str
    longueur_mots: int | None
    duree_generation_ms: int | None
    workflow_utilise: str | None
    commentaire_humain: str | None
    chemin_export: str | None
    cree_le: datetime
    maj_le: datetime


class ReponseSummary(BaseModel):
    id: int
    appel_offre_id: int
    version: int
    statut: StatutReponse
    longueur_mots: int | None
    duree_generation_ms: int | None
    cree_le: datetime


class RedactionResponse(BaseModel):
    reponse: ReponseRead
    plan: list[dict[str, str]]


class StatutReponseUpdate(BaseModel):
    statut: StatutReponse
    commentaire_humain: str | None = None


class ContenuUpdate(BaseModel):
    contenu: str
    commentaire_humain: str | None = None


_TRANSITIONS_AUTORISEES: dict[StatutReponse, set[StatutReponse]] = {
    StatutReponse.EN_GENERATION: {StatutReponse.EN_ATTENTE, StatutReponse.REJETEE},
    StatutReponse.EN_ATTENTE: {
        StatutReponse.A_MODIFIER,
        StatutReponse.VALIDEE,
        StatutReponse.REJETEE,
    },
    StatutReponse.A_MODIFIER: {
        StatutReponse.EN_ATTENTE,
        StatutReponse.VALIDEE,
        StatutReponse.REJETEE,
    },
    StatutReponse.VALIDEE: {StatutReponse.EXPORTEE, StatutReponse.A_MODIFIER},
    StatutReponse.REJETEE: set(),
    StatutReponse.EXPORTEE: set(),
}


@router.post(
    "/appels-offre/{ao_id}/rediger",
    response_model=RedactionResponse,
)
async def rediger(
    ao_id: int,
    session: SessionDep,
    payload: RedactionRequest | None = None,
) -> RedactionResponse:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")

    statuts_autorises = {StatutAO.A_REPONDRE, StatutAO.EN_REDACTION, StatutAO.ANALYSE}
    if ao.statut not in statuts_autorises:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Statut AO incompatible ({ao.statut.value}) — passer en "
                f"'a_repondre' avant de demander une rédaction"
            ),
        )

    profil = None
    if payload and payload.profil:
        profil = ProfilUtilisateur(
            prenom=payload.profil.prenom,
            nom=payload.profil.nom,
            email=payload.profil.email,
            entreprise=payload.profil.entreprise,
            activite=payload.profil.activite,
        )

    try:
        resultat = await rediger_reponse(
            session,
            ao,
            profil=profil,
            consignes_supplementaires=payload.consignes if payload else None,
        )
    except ErreurRedactionHermion as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return RedactionResponse(
        reponse=_reponse_read(resultat.reponse),
        plan=resultat.plan,
    )


@router.get("/appels-offre/{ao_id}/reponses", response_model=list[ReponseSummary])
def lister_reponses(
    ao_id: int,
    session: SessionDep,
) -> list[ReponseSummary]:
    if session.get(AppelOffre, ao_id) is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")
    rows = session.exec(
        select(ReponseHermion)
        .where(ReponseHermion.appel_offre_id == ao_id)
        .order_by(ReponseHermion.version.desc())
    ).all()
    return [_reponse_summary(r) for r in rows]


@router.get("/reponses/{reponse_id}", response_model=ReponseRead)
def lire_reponse(reponse_id: int, session: SessionDep) -> ReponseRead:
    reponse = session.get(ReponseHermion, reponse_id)
    if reponse is None:
        raise HTTPException(status_code=404, detail="Réponse introuvable")
    return _reponse_read(reponse)


@router.patch("/reponses/{reponse_id}/statut", response_model=ReponseRead)
def modifier_statut(
    reponse_id: int,
    payload: StatutReponseUpdate,
    session: SessionDep,
) -> ReponseRead:
    reponse = session.get(ReponseHermion, reponse_id)
    if reponse is None:
        raise HTTPException(status_code=404, detail="Réponse introuvable")

    autorises = _TRANSITIONS_AUTORISEES.get(reponse.statut, set())
    if payload.statut not in autorises and payload.statut != reponse.statut:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transition '{reponse.statut.value}' → '{payload.statut.value}' "
                "non autorisée"
            ),
        )

    ancien = reponse.statut
    reponse.statut = payload.statut
    if payload.commentaire_humain is not None:
        reponse.commentaire_humain = payload.commentaire_humain
    session.add(reponse)

    # Propage aux statuts de l'AO selon les transitions importantes.
    if payload.statut == StatutReponse.VALIDEE:
        ao = session.get(AppelOffre, reponse.appel_offre_id)
        if ao is not None and ao.statut != StatutAO.REPONDU:
            ao.statut = StatutAO.REPONDU
            session.add(ao)

    session.commit()
    session.refresh(reponse)

    if ancien != payload.statut:
        from hermes.db.models import LogAgent, NiveauLog

        session.add(
            LogAgent(
                agent="HERMION",
                niveau=NiveauLog.INFO,
                message=(
                    f"Réponse {reponse_id} : statut {ancien.value} → "
                    f"{payload.statut.value}"
                ),
                appel_offre_id=reponse.appel_offre_id,
            )
        )
        session.commit()
        session.refresh(reponse)

    return _reponse_read(reponse)


@router.patch("/reponses/{reponse_id}/contenu", response_model=ReponseRead)
def modifier_contenu(
    reponse_id: int,
    payload: ContenuUpdate,
    session: SessionDep,
) -> ReponseRead:
    reponse = session.get(ReponseHermion, reponse_id)
    if reponse is None:
        raise HTTPException(status_code=404, detail="Réponse introuvable")

    if reponse.statut in {StatutReponse.EXPORTEE, StatutReponse.REJETEE}:
        raise HTTPException(
            status_code=409,
            detail=f"Réponse en statut '{reponse.statut.value}' non modifiable",
        )

    reponse.contenu = payload.contenu
    reponse.longueur_mots = len([m for m in payload.contenu.split() if m.strip()])
    if payload.commentaire_humain is not None:
        reponse.commentaire_humain = payload.commentaire_humain
    if reponse.statut == StatutReponse.EN_ATTENTE:
        reponse.statut = StatutReponse.A_MODIFIER
    session.add(reponse)
    session.commit()
    session.refresh(reponse)
    return _reponse_read(reponse)


def _reponse_read(reponse: ReponseHermion) -> ReponseRead:
    return ReponseRead(
        id=reponse.id,  # type: ignore[arg-type]
        appel_offre_id=reponse.appel_offre_id,
        version=reponse.version,
        statut=reponse.statut,
        contenu=reponse.contenu,
        longueur_mots=reponse.longueur_mots,
        duree_generation_ms=reponse.duree_generation_ms,
        workflow_utilise=reponse.workflow_utilise,
        commentaire_humain=reponse.commentaire_humain,
        chemin_export=reponse.chemin_export,
        cree_le=reponse.cree_le,
        maj_le=reponse.maj_le,
    )


def _reponse_summary(reponse: ReponseHermion) -> ReponseSummary:
    return ReponseSummary(
        id=reponse.id,  # type: ignore[arg-type]
        appel_offre_id=reponse.appel_offre_id,
        version=reponse.version,
        statut=reponse.statut,
        longueur_mots=reponse.longueur_mots,
        duree_generation_ms=reponse.duree_generation_ms,
        cree_le=reponse.cree_le,
    )

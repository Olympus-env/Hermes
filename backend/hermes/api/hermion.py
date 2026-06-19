"""Endpoints REST pour HERMION : rédaction et gestion des versions de réponse."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from hermes.agents import pythia
from hermes.agents.hermion import (
    ErreurExportPdf,
    ErreurRedactionHermion,
    ProfilUtilisateur,
    SectionWorkflow,
    WorkflowReponse,
    charger_workflow,
    deriver_workflow,
    enregistrer_workflow,
    exporter_reponse_pdf,
    progression,
    rediger_reponse,
)
from hermes.config import settings
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


class ReponseAvecAO(BaseModel):
    """Synthèse réponse + métadonnées AO joints — pour la liste globale."""

    id: int
    appel_offre_id: int
    appel_offre_titre: str
    appel_offre_emetteur: str | None
    version: int
    statut: StatutReponse
    longueur_mots: int | None
    duree_generation_ms: int | None
    cree_le: datetime
    maj_le: datetime


class RedactionResponse(BaseModel):
    reponse: ReponseRead
    plan: list[dict[str, str]]


class ProgressionRead(BaseModel):
    appel_offre_id: int
    etape: str
    libelle: str
    index: int
    total: int
    message: str
    erreur: str | None
    termine: bool
    reponse_id: int | None
    secondes_ecoulees: float
    # False quand aucune rédaction n'a (encore) été lancée pour cet AO.
    connue: bool = True


class StatutReponseUpdate(BaseModel):
    statut: StatutReponse
    commentaire_humain: str | None = None


class ContenuUpdate(BaseModel):
    contenu: str
    commentaire_humain: str | None = None


class SectionWorkflowModel(BaseModel):
    titre: str
    brief: str = ""
    longueur_cible: int | None = None


class WorkflowRead(BaseModel):
    configure: bool
    source: str
    consignes_globales: str
    sections: list[SectionWorkflowModel]


class WorkflowUpdate(BaseModel):
    consignes_globales: str = ""
    sections: list[SectionWorkflowModel] = []
    source: str = "manuel"


class WorkflowDeriverRequest(BaseModel):
    mode: Literal["workflow", "exemples"]
    contenu: str


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


@router.get("/appels-offre/{ao_id}/progression", response_model=ProgressionRead)
def lire_progression(ao_id: int) -> ProgressionRead:
    """Avancement de la rédaction HERMION en cours pour cet AO (issue #7).

    Le frontend interroge cet endpoint pendant la génération pour afficher
    l'étape courante, la section en cours et le temps écoulé. Aucun appel
    PYTHIA : sert même quand une rédaction sature le LLM.
    """
    etat = progression.lire(ao_id)
    if etat is None:
        return ProgressionRead(
            appel_offre_id=ao_id,
            etape="inconnu",
            libelle="Aucune rédaction en cours",
            index=0,
            total=0,
            message="",
            erreur=None,
            termine=False,
            reponse_id=None,
            secondes_ecoulees=0.0,
            connue=False,
        )
    return ProgressionRead(connue=True, **etat.en_dict())


# --------------------------------------------------------------------------- #
# Workflow de rédaction (configuré à l'onboarding, corrigeable dans Paramètres)
# --------------------------------------------------------------------------- #


@router.get("/workflow", response_model=WorkflowRead)
def lire_workflow(session: SessionDep) -> WorkflowRead:
    """Workflow HERMION courant. `configure=false` → plan dynamique par défaut."""
    workflow = charger_workflow(session)
    if workflow is None:
        return WorkflowRead(
            configure=False, source="", consignes_globales="", sections=[]
        )
    return _workflow_read(workflow)


@router.put("/workflow", response_model=WorkflowRead)
def ecrire_workflow(payload: WorkflowUpdate, session: SessionDep) -> WorkflowRead:
    """Enregistre / corrige manuellement le workflow (persisté en MNEMOSYNE)."""
    workflow = enregistrer_workflow(session, _workflow_depuis_payload(payload))
    return _workflow_read(workflow)


@router.post("/workflow/deriver", response_model=WorkflowRead)
async def deriver(payload: WorkflowDeriverRequest) -> WorkflowRead:
    """Dérive un workflow via PYTHIA (non persisté — à éditer puis PUT)."""
    try:
        workflow = await deriver_workflow(
            mode=payload.mode, contenu=payload.contenu
        )
    except pythia.ErreurPythia as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _workflow_read(workflow)


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


@router.get("/reponses", response_model=list[ReponseAvecAO])
def lister_toutes_reponses(
    session: SessionDep,
    statut: StatutReponse | None = None,
) -> list[ReponseAvecAO]:
    """Liste globale des réponses HERMION (toutes AO confondues).

    Joint avec AppelOffre pour fournir titre + émetteur directement
    consommables côté frontend. Filtrable par statut.
    """
    stmt = (
        select(ReponseHermion, AppelOffre)
        .join(AppelOffre, AppelOffre.id == ReponseHermion.appel_offre_id)
        .order_by(ReponseHermion.cree_le.desc())
    )
    if statut is not None:
        stmt = stmt.where(ReponseHermion.statut == statut)

    rows = session.exec(stmt).all()
    return [
        ReponseAvecAO(
            id=r.id,  # type: ignore[arg-type]
            appel_offre_id=r.appel_offre_id,
            appel_offre_titre=ao.titre,
            appel_offre_emetteur=ao.emetteur,
            version=r.version,
            statut=r.statut,
            longueur_mots=r.longueur_mots,
            duree_generation_ms=r.duree_generation_ms,
            cree_le=r.cree_le,
            maj_le=r.maj_le,
        )
        for r, ao in rows
    ]


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

    _synchroniser_statut_ao(session, reponse)

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

    ancien = reponse.statut
    reponse.contenu = payload.contenu
    reponse.longueur_mots = len([m for m in payload.contenu.split() if m.strip()])
    if payload.commentaire_humain is not None:
        reponse.commentaire_humain = payload.commentaire_humain
    if reponse.statut in {StatutReponse.EN_ATTENTE, StatutReponse.VALIDEE}:
        reponse.statut = StatutReponse.A_MODIFIER
        reponse.chemin_export = None
    session.add(reponse)
    if ancien != reponse.statut:
        _synchroniser_statut_ao(session, reponse)
    session.commit()
    session.refresh(reponse)
    return _reponse_read(reponse)


@router.post("/reponses/{reponse_id}/exporter", response_model=ReponseRead)
def exporter_reponse(reponse_id: int, session: SessionDep) -> ReponseRead:
    """Génère le PDF d'une réponse validée (statut → exportée)."""
    reponse = session.get(ReponseHermion, reponse_id)
    if reponse is None:
        raise HTTPException(status_code=404, detail="Réponse introuvable")
    try:
        exporter_reponse_pdf(session, reponse)
    except ErreurExportPdf as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _reponse_read(reponse)


@router.get("/reponses/{reponse_id}/export")
def telecharger_export(reponse_id: int, session: SessionDep) -> FileResponse:
    """Télécharge le PDF déjà généré pour une réponse."""
    reponse = session.get(ReponseHermion, reponse_id)
    if reponse is None:
        raise HTTPException(status_code=404, detail="Réponse introuvable")
    if not reponse.chemin_export:
        raise HTTPException(
            status_code=404, detail="Réponse non encore exportée en PDF"
        )

    chemin = (settings.storage_path / reponse.chemin_export).resolve()
    racine = settings.storage_path.resolve()
    # Garde-fou anti-traversée : le fichier doit rester sous storage/.
    if racine not in chemin.parents or not chemin.is_file():
        raise HTTPException(status_code=404, detail="Fichier d'export introuvable")

    return FileResponse(
        path=str(chemin),
        media_type="application/pdf",
        filename=f"reponse_{reponse.id}_v{reponse.version}.pdf",
    )


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


def _synchroniser_statut_ao(session: Session, reponse: ReponseHermion) -> None:
    """Aligne le statut AO sur la dernière décision humaine HERMION."""
    ao = session.get(AppelOffre, reponse.appel_offre_id)
    if ao is None:
        return

    if reponse.statut == StatutReponse.VALIDEE:
        if ao.statut != StatutAO.REPONDU:
            ao.statut = StatutAO.REPONDU
            session.add(ao)
        return

    if reponse.statut in {StatutReponse.EN_ATTENTE, StatutReponse.A_MODIFIER}:
        if ao.statut == StatutAO.REPONDU and not _autre_reponse_finalisee(
            session, reponse
        ):
            ao.statut = StatutAO.EN_REDACTION
            session.add(ao)


def _autre_reponse_finalisee(session: Session, reponse: ReponseHermion) -> bool:
    stmt = select(ReponseHermion.id).where(
        ReponseHermion.appel_offre_id == reponse.appel_offre_id,
        ReponseHermion.statut.in_({StatutReponse.VALIDEE, StatutReponse.EXPORTEE}),
    )
    if reponse.id is not None:
        stmt = stmt.where(ReponseHermion.id != reponse.id)
    return session.exec(stmt).first() is not None


def _workflow_read(workflow: WorkflowReponse) -> WorkflowRead:
    return WorkflowRead(
        configure=workflow.configure,
        source=workflow.source,
        consignes_globales=workflow.consignes_globales,
        sections=[
            SectionWorkflowModel(
                titre=s.titre, brief=s.brief, longueur_cible=s.longueur_cible
            )
            for s in workflow.sections
        ],
    )


def _workflow_depuis_payload(payload: WorkflowUpdate) -> WorkflowReponse:
    return WorkflowReponse(
        sections=tuple(
            SectionWorkflow(
                titre=s.titre,
                brief=s.brief,
                longueur_cible=s.longueur_cible,
            )
            for s in payload.sections
        ),
        consignes_globales=payload.consignes_globales,
        source=payload.source or "manuel",
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

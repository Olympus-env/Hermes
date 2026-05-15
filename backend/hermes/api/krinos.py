"""Endpoints REST pour KRINOS : extraction documentaire."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from hermes.agents.krinos.analyzer import ErreurAnalyseKrinos, analyser_ao
from hermes.agents.krinos.downloader import (
    ErreurTelechargementDocument,
    telecharger_documents_ao,
)
from hermes.agents.krinos.extractor import ErreurExtractionDocument, extraire_document
from hermes.agents.krinos.ponderation import (
    Ponderation,
    calculer_score_final,
    charger_ponderation,
    enregistrer_ponderation,
)
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    Document,
    LogAgent,
    NiveauLog,
    StatutAO,
)
from hermes.db.session import get_session

router = APIRouter(prefix="/krinos", tags=["krinos"])
SessionDep = Annotated[Session, Depends(get_session)]


class ExtractionDocumentResponse(BaseModel):
    document_id: int
    appel_offre_id: int
    caracteres_extraits: int
    checksum_sha256: str
    taille_octets: int


class ExtractionAOResponse(BaseModel):
    appel_offre_id: int
    documents_traites: int
    caracteres_extraits: int


class TelechargementDocumentsRequest(BaseModel):
    urls: list[str] | None = None


class DocumentRead(BaseModel):
    id: int
    nom_fichier: str
    chemin_local: str
    type: str
    taille_octets: int
    checksum_sha256: str
    contenu_extrait: bool


class TelechargementDocumentsResponse(BaseModel):
    appel_offre_id: int
    documents: list[DocumentRead]
    nouveaux: int


class AnalyseRequest(BaseModel):
    forcer: bool = False


class AnalyseRead(BaseModel):
    id: int
    appel_offre_id: int
    resume: str
    score: float
    justification_score: str
    scores_dimensions: dict[str, float] = Field(default_factory=dict)
    tags: list[str]
    criteres_extraits: str | None
    duree_analyse_ms: int | None
    modele_llm: str | None
    cree_le: str


class AnalyseResponse(BaseModel):
    analyse: AnalyseRead
    nouveau: bool


class PonderationIO(BaseModel):
    affinite_metier: int = 30
    references: int = 20
    adequation_budget: int = 20
    capacite_equipe: int = 15
    calendrier: int = 15
    total: int = 100


@router.post(
    "/appels-offre/{ao_id}/documents/telecharger",
    response_model=TelechargementDocumentsResponse,
)
async def telecharger_documents(
    ao_id: int,
    session: SessionDep,
    payload: TelechargementDocumentsRequest | None = None,
) -> TelechargementDocumentsResponse:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")

    try:
        resultats = await telecharger_documents_ao(
            session,
            ao,
            urls=payload.urls if payload else None,
        )
    except ErreurTelechargementDocument as exc:
        _journaliser(
            session,
            niveau=NiveauLog.ERROR,
            message=f"Téléchargement documents AO {ao_id} impossible : {exc}",
            appel_offre_id=ao_id,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for resultat in resultats:
        _journaliser(
            session,
            niveau=NiveauLog.INFO,
            message=(
                f"Document {'téléchargé' if resultat.nouveau else 'déjà présent'} : "
                f"{resultat.document.nom_fichier}"
            ),
            appel_offre_id=ao_id,
        )

    return TelechargementDocumentsResponse(
        appel_offre_id=ao_id,
        documents=[_document_read(r.document) for r in resultats],
        nouveaux=sum(1 for r in resultats if r.nouveau),
    )


@router.post("/documents/{document_id}/extraire", response_model=ExtractionDocumentResponse)
def extraire_un_document(
    document_id: int,
    session: SessionDep,
) -> ExtractionDocumentResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return _extraire_et_persister(session, document)


@router.post("/appels-offre/{ao_id}/extraire", response_model=ExtractionAOResponse)
def extraire_documents_ao(
    ao_id: int,
    session: SessionDep,
) -> ExtractionAOResponse:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")

    documents = session.exec(
        select(Document).where(Document.appel_offre_id == ao_id).order_by(Document.id)
    ).all()
    caracteres = 0
    for document in documents:
        reponse = _extraire_et_persister(session, document)
        caracteres += reponse.caracteres_extraits

    if documents and ao.statut == StatutAO.BRUT:
        ao.statut = StatutAO.ANALYSE
        session.add(ao)
        session.commit()

    return ExtractionAOResponse(
        appel_offre_id=ao_id,
        documents_traites=len(documents),
        caracteres_extraits=caracteres,
    )


def _extraire_et_persister(
    session: Session,
    document: Document,
) -> ExtractionDocumentResponse:
    try:
        extraction = extraire_document(document)
    except ErreurExtractionDocument as exc:
        _journaliser(
            session,
            niveau=NiveauLog.ERROR,
            message=f"Extraction document {document.id} impossible : {exc}",
            appel_offre_id=document.appel_offre_id,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document.contenu_extrait = extraction.texte
    document.checksum_sha256 = extraction.checksum_sha256
    document.taille_octets = extraction.taille_octets
    session.add(document)
    session.commit()
    session.refresh(document)

    _journaliser(
        session,
        niveau=NiveauLog.INFO,
        message=(
            f"Extraction document {document.id} : "
            f"{len(extraction.texte)} caractères extraits"
        ),
        appel_offre_id=document.appel_offre_id,
    )

    return ExtractionDocumentResponse(
        document_id=document.id,  # type: ignore[arg-type]
        appel_offre_id=document.appel_offre_id,
        caracteres_extraits=len(extraction.texte),
        checksum_sha256=extraction.checksum_sha256,
        taille_octets=extraction.taille_octets,
    )


@router.post("/appels-offre/{ao_id}/analyser", response_model=AnalyseResponse)
async def analyser_appel_offre(
    ao_id: int,
    session: SessionDep,
    payload: AnalyseRequest | None = None,
) -> AnalyseResponse:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")

    try:
        resultat = await analyser_ao(session, ao, forcer=bool(payload and payload.forcer))
    except ErreurAnalyseKrinos as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AnalyseResponse(
        analyse=_analyse_read(resultat.analyse),
        nouveau=resultat.nouveau,
    )


@router.get("/ponderation", response_model=PonderationIO)
def lire_ponderation(session: SessionDep) -> PonderationIO:
    p = charger_ponderation(session)
    return _ponderation_io(p)


@router.put("/ponderation", response_model=PonderationIO)
def ecrire_ponderation(payload: PonderationIO, session: SessionDep) -> PonderationIO:
    nouvelle = Ponderation(
        affinite_metier=max(0, min(100, payload.affinite_metier)),
        references=max(0, min(100, payload.references)),
        adequation_budget=max(0, min(100, payload.adequation_budget)),
        capacite_equipe=max(0, min(100, payload.capacite_equipe)),
        calendrier=max(0, min(100, payload.calendrier)),
    )
    enregistrer_ponderation(session, nouvelle)
    return _ponderation_io(nouvelle)


def _ponderation_io(p: Ponderation) -> PonderationIO:
    return PonderationIO(
        affinite_metier=p.affinite_metier,
        references=p.references,
        adequation_budget=p.adequation_budget,
        capacite_equipe=p.capacite_equipe,
        calendrier=p.calendrier,
        total=p.total,
    )


@router.get("/appels-offre/{ao_id}/analyse", response_model=AnalyseRead)
def lire_analyse_ao(
    ao_id: int,
    session: SessionDep,
) -> AnalyseRead:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")

    analyse = session.exec(
        select(AnalyseKrinos)
        .where(AnalyseKrinos.appel_offre_id == ao_id)
        .order_by(AnalyseKrinos.cree_le.desc())
    ).first()
    if analyse is None:
        raise HTTPException(status_code=404, detail="Aucune analyse pour cet appel d'offre")
    return _analyse_read(analyse)


@router.post("/appels-offre/{ao_id}/recalculer-score", response_model=AnalyseRead)
def recalculer_score_ao(
    ao_id: int,
    session: SessionDep,
) -> AnalyseRead:
    ao = session.get(AppelOffre, ao_id)
    if ao is None:
        raise HTTPException(status_code=404, detail="Appel d'offre introuvable")

    analyse = session.exec(
        select(AnalyseKrinos)
        .where(AnalyseKrinos.appel_offre_id == ao_id)
        .order_by(AnalyseKrinos.cree_le.desc())
    ).first()
    if analyse is None:
        raise HTTPException(status_code=404, detail="Aucune analyse pour cet appel d'offre")

    scores = _scores_dimensions(analyse)
    if not scores:
        raise HTTPException(
            status_code=409,
            detail="Cette analyse ne contient pas de scores par dimension",
        )

    analyse.score = calculer_score_final(scores, charger_ponderation(session))
    session.add(analyse)
    session.commit()
    session.refresh(analyse)
    return _analyse_read(analyse)


def _analyse_read(analyse: AnalyseKrinos) -> AnalyseRead:
    tags: list[str] = []
    if analyse.tags:
        try:
            valeurs = json.loads(analyse.tags)
            if isinstance(valeurs, list):
                tags = [str(v) for v in valeurs]
        except json.JSONDecodeError:
            tags = []

    return AnalyseRead(
        id=analyse.id,  # type: ignore[arg-type]
        appel_offre_id=analyse.appel_offre_id,
        resume=analyse.resume,
        score=analyse.score,
        justification_score=analyse.justification_score,
        scores_dimensions=_scores_dimensions(analyse),
        tags=tags,
        criteres_extraits=analyse.criteres_extraits,
        duree_analyse_ms=analyse.duree_analyse_ms,
        modele_llm=analyse.modele_llm,
        cree_le=analyse.cree_le.isoformat(),
    )


def _scores_dimensions(analyse: AnalyseKrinos) -> dict[str, float]:
    if not analyse.scores_dimensions:
        return {}
    try:
        valeurs = json.loads(analyse.scores_dimensions)
    except json.JSONDecodeError:
        return {}
    if not isinstance(valeurs, dict):
        return {}

    scores: dict[str, float] = {}
    for dim in Ponderation.DIMENSIONS:
        valeur = valeurs.get(dim)
        try:
            scores[dim] = max(0.0, min(100.0, float(valeur)))
        except (TypeError, ValueError):
            continue
    return scores


def _journaliser(
    session: Session,
    *,
    niveau: NiveauLog,
    message: str,
    appel_offre_id: int,
) -> None:
    session.add(
        LogAgent(
            agent="KRINOS",
            niveau=niveau,
            message=message,
            appel_offre_id=appel_offre_id,
        )
    )
    session.commit()


def _document_read(document: Document) -> DocumentRead:
    return DocumentRead(
        id=document.id,  # type: ignore[arg-type]
        nom_fichier=document.nom_fichier,
        chemin_local=document.chemin_local,
        type=document.type.value,
        taille_octets=document.taille_octets,
        checksum_sha256=document.checksum_sha256,
        contenu_extrait=document.contenu_extrait is not None,
    )

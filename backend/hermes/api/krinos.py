"""Endpoints REST pour KRINOS : extraction documentaire."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from hermes.agents.krinos.downloader import (
    ErreurTelechargementDocument,
    telecharger_documents_ao,
)
from hermes.agents.krinos.extractor import ErreurExtractionDocument, extraire_document
from hermes.db.models import AppelOffre, Document, LogAgent, NiveauLog, StatutAO
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

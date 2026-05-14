"""Téléchargement et attachement des documents d'appels d'offre."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from sqlmodel import Session, select

from hermes.config import settings
from hermes.db.models import AppelOffre, Document, TypeDocument

MAX_DOCUMENT_OCTETS = 25 * 1024 * 1024
_UA = "Mozilla/5.0 (compatible; HERMES/0.1; KRINOS-document-downloader)"


class ErreurTelechargementDocument(RuntimeError):
    """Erreur contrôlée lors du téléchargement d'un document."""


@dataclass(frozen=True)
class DocumentTelecharge:
    document: Document
    nouveau: bool


@dataclass(frozen=True)
class ReponseDocument:
    contenu: bytes
    content_type: str | None = None
    nom_fichier: str | None = None


async def telecharger_documents_ao(
    session: Session,
    appel_offre: AppelOffre,
    *,
    urls: list[str] | None = None,
) -> list[DocumentTelecharge]:
    """Télécharge les documents depuis les URLs fournies, ou `url_source` par défaut."""
    cibles = urls or [appel_offre.url_source]
    resultats: list[DocumentTelecharge] = []
    for url in cibles:
        reponse = await _telecharger_url(url)
        resultats.append(_persister_document(session, appel_offre, url, reponse))
    return resultats


async def _telecharger_url(url: str) -> ReponseDocument:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ErreurTelechargementDocument("Seules les URLs HTTP/HTTPS sont supportées")

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
    except httpx.HTTPError as exc:
        raise ErreurTelechargementDocument(f"Téléchargement impossible : {exc}") from exc

    contenu = r.content
    if len(contenu) > MAX_DOCUMENT_OCTETS:
        raise ErreurTelechargementDocument("Document trop volumineux")

    return ReponseDocument(
        contenu=contenu,
        content_type=r.headers.get("content-type"),
        nom_fichier=_nom_depuis_content_disposition(r.headers.get("content-disposition")),
    )


def _persister_document(
    session: Session,
    appel_offre: AppelOffre,
    url: str,
    reponse: ReponseDocument,
) -> DocumentTelecharge:
    checksum = hashlib.sha256(reponse.contenu).hexdigest()
    existant = session.exec(
        select(Document).where(
            Document.appel_offre_id == appel_offre.id,
            Document.checksum_sha256 == checksum,
        )
    ).first()
    if existant is not None:
        return DocumentTelecharge(document=existant, nouveau=False)

    type_document = _type_document(url, reponse.content_type, reponse.nom_fichier)
    nom_fichier = _nom_fichier(url, reponse.nom_fichier, type_document, checksum)
    chemin_relatif = Path("appels_offre") / str(appel_offre.id) / nom_fichier
    chemin_absolu = settings.storage_path / chemin_relatif
    chemin_absolu.parent.mkdir(parents=True, exist_ok=True)
    chemin_absolu.write_bytes(reponse.contenu)

    document = Document(
        appel_offre_id=appel_offre.id,  # type: ignore[arg-type]
        nom_fichier=nom_fichier,
        chemin_local=chemin_relatif.as_posix(),
        type=type_document,
        taille_octets=len(reponse.contenu),
        checksum_sha256=checksum,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return DocumentTelecharge(document=document, nouveau=True)


def _type_document(
    url: str,
    content_type: str | None,
    nom_fichier: str | None,
) -> TypeDocument:
    source = " ".join(x or "" for x in (url, content_type, nom_fichier)).lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    if "pdf" in source or suffix == ".pdf":
        return TypeDocument.PDF
    if "spreadsheet" in source or "excel" in source or suffix == ".xlsx":
        return TypeDocument.XLSX
    if "wordprocessing" in source or suffix == ".docx":
        return TypeDocument.DOCX
    if "html" in source or suffix in {".html", ".htm", ""}:
        return TypeDocument.HTML
    return TypeDocument.AUTRE


def _nom_fichier(
    url: str,
    nom_header: str | None,
    type_document: TypeDocument,
    checksum: str,
) -> str:
    nom = nom_header or Path(unquote(urlparse(url).path)).name
    nom = _nettoyer_nom_fichier(nom)
    if not nom:
        nom = f"document-{checksum[:12]}"

    extension = _extension(type_document)
    if extension and Path(nom).suffix.lower() != extension:
        nom = f"{Path(nom).stem}{extension}"
    return nom


def _nettoyer_nom_fichier(nom: str) -> str:
    nom = nom.strip().replace("\\", "/").split("/")[-1]
    nom = re.sub(r"[^A-Za-z0-9._-]+", "_", nom)
    return nom.strip("._-")[:120]


def _extension(type_document: TypeDocument) -> str:
    return {
        TypeDocument.PDF: ".pdf",
        TypeDocument.XLSX: ".xlsx",
        TypeDocument.DOCX: ".docx",
        TypeDocument.HTML: ".html",
    }.get(type_document, "")


def _nom_depuis_content_disposition(valeur: str | None) -> str | None:
    if not valeur:
        return None
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', valeur, re.IGNORECASE)
    if not match:
        return None
    return unquote(match.group(1).strip())

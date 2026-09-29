"""Téléchargement et attachement des documents d'appels d'offre."""

from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import json
import re
import socket
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from sqlmodel import Session, select

from hermes.config import settings
from hermes.db.models import AppelOffre, Document, TypeDocument

MAX_DOCUMENT_OCTETS = 25 * 1024 * 1024
MAX_REDIRECTIONS = 5
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
    erreurs: list[str] | None = None,
) -> list[DocumentTelecharge]:
    """Télécharge les documents de l'AO.

    Cibles, par ordre de priorité : `urls` explicites, sinon les liens
    documents détectés par ARGOS (`liens_documents`, ex. TED HTML/PDF/XML),
    sinon `url_source` en dernier recours. Chaque cible est best-effort
    indépendante : un échec sur une URL n'empêche pas les autres ; les messages
    d'erreur partiels sont ajoutés à `erreurs`. Si TOUTES les cibles échouent,
    l'erreur est levée.
    """
    cibles = urls or liens_documents_ao(appel_offre)
    resultats: list[DocumentTelecharge] = []
    messages: list[str] = []
    for url in cibles:
        try:
            reponse = await _telecharger_url(url)
        except ErreurTelechargementDocument as exc:
            messages.append(f"{url} : {exc}")
            continue
        resultats.append(_persister_document(session, appel_offre, url, reponse))
    if messages and not resultats:
        raise ErreurTelechargementDocument(" ; ".join(messages))
    if erreurs is not None:
        erreurs.extend(messages)
    return resultats


def liens_documents_ao(appel_offre: AppelOffre) -> list[str]:
    """Liens à télécharger pour un AO : détectés par ARGOS, sinon `url_source`."""
    if appel_offre.liens_documents:
        try:
            liens = json.loads(appel_offre.liens_documents)
        except json.JSONDecodeError:
            liens = None
        if isinstance(liens, list):
            propres = [str(u).strip() for u in liens if str(u).strip()]
            if propres:
                return propres
    return [appel_offre.url_source]


async def _resoudre_ips(hote: str) -> list[str]:
    """Résout `hote` en adresses IP (point d'extension pour les tests)."""
    infos = await asyncio.get_running_loop().getaddrinfo(hote, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def _verifier_url_publique(url: str) -> None:
    """Refuse tout schéma non HTTP(S) et toute cible non publique (anti-SSRF).

    Après résolution DNS, une seule IP loopback/privée/link-local/réservée
    suffit à refuser. Appelé avant la requête ET à chaque redirection.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ErreurTelechargementDocument("Seules les URLs HTTP/HTTPS sont supportées")
    try:
        ips = await _resoudre_ips(parsed.hostname)
    except OSError as exc:
        raise ErreurTelechargementDocument(f"Résolution DNS impossible : {exc}") from exc
    if not ips:
        raise ErreurTelechargementDocument("Résolution DNS sans résultat")
    for brute in ips:
        ip = ipaddress.ip_address(brute.split("%")[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ErreurTelechargementDocument("Adresse non publique refusée")


async def _telecharger_url(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> ReponseDocument:
    try:
        # Redirections suivies à la main : chaque saut est revalidé (anti-SSRF).
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
            headers={"User-Agent": _UA},
            transport=transport,
        ) as client:
            courante = url
            for _ in range(MAX_REDIRECTIONS + 1):
                await _verifier_url_publique(courante)
                async with client.stream("GET", courante) as r:
                    if r.is_redirect and r.headers.get("location"):
                        courante = urljoin(courante, r.headers["location"])
                        continue
                    r.raise_for_status()
                    annonce = r.headers.get("content-length")
                    if annonce and annonce.isdigit() and int(annonce) > MAX_DOCUMENT_OCTETS:
                        raise ErreurTelechargementDocument("Document trop volumineux")
                    morceaux: list[bytes] = []
                    recu = 0
                    async for morceau in r.aiter_bytes():
                        recu += len(morceau)
                        if recu > MAX_DOCUMENT_OCTETS:
                            raise ErreurTelechargementDocument("Document trop volumineux")
                        morceaux.append(morceau)
                    return ReponseDocument(
                        contenu=b"".join(morceaux),
                        content_type=r.headers.get("content-type"),
                        nom_fichier=_nom_depuis_content_disposition(
                            r.headers.get("content-disposition")
                        ),
                    )
            raise ErreurTelechargementDocument("Trop de redirections")
    except httpx.HTTPError as exc:
        raise ErreurTelechargementDocument(f"Téléchargement impossible : {exc}") from exc


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

    type_document = _type_document(
        url, reponse.content_type, reponse.nom_fichier, reponse.contenu
    )
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


def _type_office(contenu: bytes) -> TypeDocument | None:
    """Distingue DOCX/XLSX dans un conteneur ZIP (`PK\\x03\\x04`) via son sommaire."""
    try:
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            noms = z.namelist()
    except zipfile.BadZipFile:
        return None
    if any(n.startswith("word/") for n in noms):
        return TypeDocument.DOCX
    if any(n.startswith("xl/") for n in noms):
        return TypeDocument.XLSX
    return None


def _type_document(
    url: str,
    content_type: str | None,
    nom_fichier: str | None,
    contenu: bytes | None = None,
) -> TypeDocument:
    # Les magic bytes priment sur les indices déclaratifs (URL, Content-Type).
    if contenu:
        if contenu.startswith(b"%PDF"):
            return TypeDocument.PDF
        if contenu.startswith(b"PK\x03\x04"):
            type_zip = _type_office(contenu)
            if type_zip is not None:
                return type_zip
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
        nom = "document"

    extension = _extension(type_document)
    if extension and Path(nom).suffix.lower() != extension:
        nom = f"{Path(nom).stem}{extension}"
    # Préfixe checksum : deux documents distincts au même nom ne s'écrasent pas.
    return f"{checksum[:12]}-{nom}"


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

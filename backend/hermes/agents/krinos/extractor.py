"""Extraction de texte pour les documents liés aux appels d'offre."""

from __future__ import annotations

import hashlib
import html
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from hermes.config import settings
from hermes.db.models import Document, TypeDocument


class ErreurExtractionDocument(RuntimeError):
    """Erreur contrôlée lors de l'extraction d'un document."""


@dataclass(frozen=True)
class ExtractionDocument:
    texte: str
    checksum_sha256: str
    taille_octets: int


def extraire_document(document: Document) -> ExtractionDocument:
    """Extrait le texte du fichier local et calcule ses métadonnées fichier."""
    chemin = _chemin_document(document.chemin_local)
    if not chemin.exists() or not chemin.is_file():
        raise ErreurExtractionDocument(f"Document introuvable : {document.chemin_local}")

    brut = chemin.read_bytes()
    checksum = hashlib.sha256(brut).hexdigest()
    texte = _extraire_texte(chemin, document.type, brut)
    return ExtractionDocument(
        texte=_normaliser_texte(texte),
        checksum_sha256=checksum,
        taille_octets=len(brut),
    )


def _chemin_document(chemin_local: str) -> Path:
    storage = settings.storage_path.resolve()
    chemin = Path(chemin_local)
    if chemin.is_absolute():
        candidat = chemin.resolve()
    else:
        candidat = (storage / chemin).resolve()
    if storage != candidat and storage not in candidat.parents:
        raise ErreurExtractionDocument("Chemin document hors storage")
    return candidat


def _extraire_texte(chemin: Path, type_document: TypeDocument, brut: bytes) -> str:
    if type_document == TypeDocument.PDF:
        return _extraire_pdf(chemin)
    if type_document == TypeDocument.HTML:
        return _extraire_html(brut)
    if type_document == TypeDocument.XLSX:
        return _extraire_xlsx(chemin)
    return _extraire_texte_brut(brut)


def _extraire_pdf(chemin: Path) -> str:
    erreurs: list[str] = []
    try:
        import pdfplumber

        with pdfplumber.open(chemin) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError as exc:
        erreurs.append(f"pdfplumber indisponible : {exc}")
    except Exception as exc:  # noqa: BLE001
        erreurs.append(f"pdfplumber : {exc}")

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        erreurs.append(f"PyMuPDF indisponible : {exc}")
        raise ErreurExtractionDocument(
            "Aucun extracteur PDF disponible : " + " ; ".join(erreurs)
        ) from exc

    morceaux: list[str] = []
    try:
        with fitz.open(chemin) as doc:
            for page in doc:
                morceaux.append(page.get_text("text"))
    except Exception as exc:  # noqa: BLE001
        erreurs.append(f"PyMuPDF : {exc}")
        raise ErreurExtractionDocument("PDF illisible : " + " ; ".join(erreurs)) from exc
    return "\n".join(morceaux)


def _extraire_html(brut: bytes) -> str:
    soup = BeautifulSoup(brut, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


def _extraire_xlsx(chemin: Path) -> str:
    valeurs: list[str] = []
    try:
        with zipfile.ZipFile(chemin) as archive:
            shared = _shared_strings(archive)
            for nom in archive.namelist():
                if not nom.startswith("xl/worksheets/sheet") or not nom.endswith(".xml"):
                    continue
                racine = ElementTree.fromstring(archive.read(nom))
                for cellule in racine.iter(_tag("c")):
                    valeur = cellule.find(_tag("v"))
                    if valeur is None or valeur.text is None:
                        continue
                    if cellule.attrib.get("t") == "s":
                        idx = int(valeur.text)
                        if 0 <= idx < len(shared):
                            valeurs.append(shared[idx])
                    else:
                        valeurs.append(valeur.text)
    except Exception as exc:  # noqa: BLE001
        raise ErreurExtractionDocument(f"XLSX illisible : {exc}") from exc
    return "\n".join(valeurs)


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    racine = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in si.iter(_tag("t")))
        for si in racine.iter(_tag("si"))
    ]


def _tag(nom: str) -> str:
    return f"{{http://schemas.openxmlformats.org/spreadsheetml/2006/main}}{nom}"


def _extraire_texte_brut(brut: bytes) -> str:
    for encodage in ("utf-8", "cp1252", "latin-1"):
        try:
            return brut.decode(encodage)
        except UnicodeDecodeError:
            continue
    return brut.decode("utf-8", errors="ignore")


def _normaliser_texte(texte: str) -> str:
    texte = html.unescape(texte)
    texte = texte.replace("\x00", " ")
    texte = re.sub(r"[ \t\r\f\v]+", " ", texte)
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    return texte.strip()

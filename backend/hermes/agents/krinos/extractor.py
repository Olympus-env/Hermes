"""Extraction de texte pour les documents liés aux appels d'offre."""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from defusedxml import ElementTree
from loguru import logger
from sqlmodel import Session, select

from hermes.config import settings
from hermes.db.models import AppelOffre, Document, TypeDocument


class ErreurExtractionDocument(RuntimeError):
    """Erreur contrôlée lors de l'extraction d'un document."""


@dataclass(frozen=True)
class ExtractionDocument:
    texte: str
    checksum_sha256: str
    taille_octets: int
    # Limites rencontrées (scan non lu, plafond de pages…) : le texte reste
    # exploitable mais incomplet, l'appelant doit le signaler à l'utilisateur.
    avertissements: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RapportExtractionDocuments:
    documents_traites: int
    caracteres_extraits: int
    erreurs: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()


def extraire_document(document: Document) -> ExtractionDocument:
    """Extrait le texte du fichier local et calcule ses métadonnées fichier."""
    chemin = _chemin_document(document.chemin_local)
    if not chemin.exists() or not chemin.is_file():
        raise ErreurExtractionDocument(f"Document introuvable : {document.chemin_local}")

    taille = chemin.stat().st_size
    if taille > settings.krinos_extraction_max_octets:
        raise ErreurExtractionDocument(
            f"Document trop volumineux ({taille // (1024 * 1024)} Mo, "
            f"plafond {settings.krinos_extraction_max_octets // (1024 * 1024)} Mo)"
        )
    checksum = _checksum_fichier(chemin)
    avertissements: list[str] = []
    texte = _extraire_texte(chemin, document.type, avertissements)
    texte = _normaliser_texte(texte)
    plafond = settings.krinos_extraction_max_caracteres
    if len(texte) > plafond:
        texte = texte[:plafond]
        avertissements.append(f"Texte tronqué à {plafond} caractères")
    return ExtractionDocument(
        texte=texte,
        checksum_sha256=checksum,
        taille_octets=taille,
        avertissements=tuple(avertissements),
    )


def extraire_documents_appel_offre(
    session: Session,
    appel_offre: AppelOffre,
    *,
    seulement_non_extraits: bool = True,
    best_effort: bool = False,
) -> RapportExtractionDocuments:
    """Extrait les documents locaux attachés à un AO et persiste le résultat.

    Utilisé avant une analyse KRINOS pour éviter qu'un document déjà téléchargé,
    mais jamais extrait, soit ignoré par le contexte envoyé à PYTHIA.
    """
    if appel_offre.id is None:
        return RapportExtractionDocuments(documents_traites=0, caracteres_extraits=0)

    documents = _documents_a_extraire(session, appel_offre, seulement_non_extraits)
    traites = 0
    caracteres = 0
    erreurs: list[str] = []
    avertissements: list[str] = []
    for document in documents:
        try:
            extraction = extraire_document(document)
        except ErreurExtractionDocument as exc:
            if not best_effort:
                raise
            erreurs.append(f"Document {document.id}: {exc}")
            continue
        caracteres += _appliquer_extraction(session, document, extraction)
        avertissements.extend(
            f"Document {document.id}: {a}" for a in extraction.avertissements
        )
        traites += 1

    if traites:
        session.commit()

    return RapportExtractionDocuments(
        documents_traites=traites,
        caracteres_extraits=caracteres,
        erreurs=tuple(erreurs),
        avertissements=tuple(avertissements),
    )


async def extraire_documents_appel_offre_async(
    session: Session,
    appel_offre: AppelOffre,
    *,
    seulement_non_extraits: bool = True,
    best_effort: bool = False,
) -> RapportExtractionDocuments:
    """Variante non bloquante pour les endpoints/agents async.

    PyMuPDF/pdfplumber/OCR sont synchrones et lents sur de gros DCE : l'extraction
    tourne dans un thread (`asyncio.to_thread`) pour ne pas figer la boucle
    d'événements ; la persistance reste sur le thread courant (session SQLite).
    """
    if appel_offre.id is None:
        return RapportExtractionDocuments(documents_traites=0, caracteres_extraits=0)

    documents = _documents_a_extraire(session, appel_offre, seulement_non_extraits)
    traites = 0
    caracteres = 0
    erreurs: list[str] = []
    avertissements: list[str] = []
    for document in documents:
        try:
            extraction = await asyncio.to_thread(extraire_document, document)
        except ErreurExtractionDocument as exc:
            if not best_effort:
                raise
            erreurs.append(f"Document {document.id}: {exc}")
            continue
        caracteres += _appliquer_extraction(session, document, extraction)
        avertissements.extend(
            f"Document {document.id}: {a}" for a in extraction.avertissements
        )
        traites += 1

    if traites:
        session.commit()

    return RapportExtractionDocuments(
        documents_traites=traites,
        caracteres_extraits=caracteres,
        erreurs=tuple(erreurs),
        avertissements=tuple(avertissements),
    )


def _documents_a_extraire(
    session: Session, appel_offre: AppelOffre, seulement_non_extraits: bool
) -> list[Document]:
    documents = session.exec(
        select(Document)
        .where(Document.appel_offre_id == appel_offre.id)
        .order_by(Document.id)
    ).all()
    return [d for d in documents if not (seulement_non_extraits and d.contenu_extrait)]


def _appliquer_extraction(
    session: Session, document: Document, extraction: ExtractionDocument
) -> int:
    document.contenu_extrait = extraction.texte
    document.checksum_sha256 = extraction.checksum_sha256
    document.taille_octets = extraction.taille_octets
    session.add(document)
    return len(extraction.texte)


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


def _checksum_fichier(chemin: Path) -> str:
    """SHA-256 par blocs : pas besoin de charger tout le fichier en mémoire."""
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def _extraire_texte(
    chemin: Path, type_document: TypeDocument, avertissements: list[str]
) -> str:
    if type_document == TypeDocument.PDF:
        return _extraire_pdf(chemin, avertissements)
    if type_document == TypeDocument.HTML:
        return _extraire_html(chemin.read_bytes())
    if type_document == TypeDocument.XLSX:
        return _extraire_xlsx(chemin, avertissements)
    if type_document == TypeDocument.DOCX:
        return _extraire_docx(chemin)
    return _extraire_texte_brut(chemin.read_bytes())


# --------------------------------------------------------------------------- #
# PDF : PyMuPDF (texte + tableaux), OCR RapidOCR des pages scannées,
# pdfplumber en repli.
# --------------------------------------------------------------------------- #

# En dessous de ce nombre de caractères, une page porteuse d'images est
# considérée comme scannée (le texte résiduel est du bruit : numéro de page…).
_SEUIL_PAGE_SCANNEE = 20

_OCR_VERROU = threading.Lock()
_OCR_MOTEUR: Any = None
_OCR_ESSAYE = False


def _moteur_ocr() -> Any:
    """Moteur RapidOCR (chargé une fois), ou None s'il est indisponible.

    RapidOCR embarque ses modèles ONNX dans le wheel (PP-OCRv6 det+rec+cls,
    ~30 Mo) : aucun téléchargement, HERMES reste 100 % local.
    """
    global _OCR_MOTEUR, _OCR_ESSAYE
    with _OCR_VERROU:
        if not _OCR_ESSAYE:
            _OCR_ESSAYE = True
            try:
                from rapidocr import RapidOCR

                _OCR_MOTEUR = RapidOCR(params={"Global.log_level": "warning"})
            except Exception as exc:  # noqa: BLE001
                logger.warning("KRINOS : OCR indisponible — {}", exc)
        return _OCR_MOTEUR


def _ocr_page(moteur: Any, page: Any) -> str:
    pix = page.get_pixmap(dpi=settings.krinos_ocr_dpi)
    with _OCR_VERROU:  # une session ONNX partagée : on sérialise les inférences
        resultat = moteur(pix.tobytes("png"))
    return "\n".join(resultat.txts or ())


def _liste_pages(numeros: list[int]) -> str:
    vus = ", ".join(str(n) for n in numeros[:10])
    return vus + (f" … (+{len(numeros) - 10})" if len(numeros) > 10 else "")


def _table_markdown(lignes: list[list[str]]) -> str:
    lignes = [
        [(c or "").replace("\n", " ").replace("|", "\\|").strip() for c in ligne]
        for ligne in lignes
    ]
    if not any(c for ligne in lignes for c in ligne):
        return ""
    largeur = max(len(ligne) for ligne in lignes)
    lignes = [ligne + [""] * (largeur - len(ligne)) for ligne in lignes]
    rendu = ["| " + " | ".join(lignes[0]) + " |", "|" + " --- |" * largeur]
    rendu += ["| " + " | ".join(ligne) + " |" for ligne in lignes[1:]]
    return "\n".join(rendu)


def _texte_page_pymupdf(page: Any) -> str:
    """Texte d'une page, tableaux rendus en Markdown à leur place (ordre vertical)."""
    import fitz

    try:
        tables = [
            t for t in page.find_tables().tables if t.row_count >= 2 and t.col_count >= 2
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("KRINOS : détection de tableaux impossible — {}", exc)
        tables = []
    zones = [fitz.Rect(t.bbox) for t in tables]
    elements: list[tuple[float, str]] = []
    for x0, y0, x1, y1, texte, _no, type_bloc in page.get_text("blocks", sort=True):
        centre = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2)
        if type_bloc == 0 and not any(z.contains(centre) for z in zones):
            elements.append((y0, texte))
    for table, zone in zip(tables, zones, strict=True):
        rendu = _table_markdown(table.extract())
        if rendu:
            elements.append((zone.y0, rendu))
    elements.sort(key=lambda e: e[0])
    return "\n".join(t for _, t in elements)


def _extraire_pdf(chemin: Path, avertissements: list[str]) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        return _extraire_pdf_pdfplumber(chemin, f"PyMuPDF indisponible : {exc}")
    try:
        with fitz.open(chemin) as doc:
            if doc.needs_pass:
                raise ErreurExtractionDocument("PDF protégé par mot de passe")
            return _extraire_pdf_pymupdf(doc, avertissements)
    except ErreurExtractionDocument:
        raise
    except Exception as exc:  # noqa: BLE001
        avertissements.clear()  # le repli repart de zéro
        return _extraire_pdf_pdfplumber(chemin, f"PyMuPDF : {exc}")


def _extraire_pdf_pymupdf(doc: Any, avertissements: list[str]) -> str:
    total = doc.page_count
    limite = min(total, settings.krinos_extraction_max_pages)
    pages: list[str] = []
    ocr_faites = 0
    sans_ocr: list[int] = []  # OCR indisponible ou en échec
    hors_plafond_ocr: list[int] = []
    moteur: Any = None
    moteur_charge = False
    for index in range(limite):
        page = doc[index]
        texte = _texte_page_pymupdf(page)
        if len(texte.strip()) < _SEUIL_PAGE_SCANNEE and page.get_images():
            if ocr_faites >= settings.krinos_ocr_max_pages:
                hors_plafond_ocr.append(index + 1)
            else:
                if not moteur_charge:
                    moteur, moteur_charge = _moteur_ocr(), True
                if moteur is None:
                    sans_ocr.append(index + 1)
                else:
                    try:
                        texte = (texte + "\n" + _ocr_page(moteur, page)).strip()
                        ocr_faites += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("KRINOS : OCR page {} en échec — {}", index + 1, exc)
                        sans_ocr.append(index + 1)
        pages.append(texte)

    # Les mentions vont en tête : le contexte envoyé à PYTHIA est tronqué par la fin.
    mentions: list[str] = []
    if sans_ocr:
        mentions.append(
            "Document scanné non lu : OCR indisponible ou en échec "
            f"(pages {_liste_pages(sans_ocr)})"
        )
    if hors_plafond_ocr:
        mentions.append(
            f"Pages scannées non lues : plafond OCR de {settings.krinos_ocr_max_pages} "
            f"pages atteint (pages {_liste_pages(hors_plafond_ocr)})"
        )
    if limite < total:
        mentions.append(
            f"{total - limite} pages non lues : plafond de "
            f"{settings.krinos_extraction_max_pages} pages atteint"
        )
    avertissements.extend(mentions)
    entete = "".join(f"[{m}]\n" for m in mentions)
    return entete + "\n".join(pages)


def _extraire_pdf_pdfplumber(chemin: Path, motif: str) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(chemin) as pdf:
            pages = pdf.pages[: settings.krinos_extraction_max_pages]
            return "\n".join(page.extract_text() or "" for page in pages)
    except ImportError as exc:
        raise ErreurExtractionDocument(
            f"Aucun extracteur PDF disponible : {motif} ; pdfplumber indisponible : {exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise ErreurExtractionDocument(
            f"PDF illisible : {motif} ; pdfplumber : {exc}"
        ) from exc


def _extraire_html(brut: bytes) -> str:
    soup = BeautifulSoup(brut, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


# --------------------------------------------------------------------------- #
# OOXML (XLSX / DOCX) : parsing XML sûr (defusedxml) + garde anti zip bomb.
# --------------------------------------------------------------------------- #


def _local(tag: str) -> str:
    """Nom local d'une balise XML (sans espace de noms)."""
    return tag.rsplit("}", 1)[-1]


def _ouvrir_ooxml(chemin: Path, libelle: str) -> zipfile.ZipFile:
    """Ouvre l'archive et refuse celle dont la taille décompressée déclarée est excessive."""
    try:
        archive = zipfile.ZipFile(chemin)
    except Exception as exc:  # noqa: BLE001
        raise ErreurExtractionDocument(f"{libelle} illisible : {exc}") from exc
    total = sum(info.file_size for info in archive.infolist())
    plafond = settings.krinos_extraction_max_octets_decompresses
    if total > plafond:
        archive.close()
        raise ErreurExtractionDocument(
            f"{libelle} refusé : {total // (1024 * 1024)} Mo décompressés déclarés, "
            f"plafond {plafond // (1024 * 1024)} Mo (archive piégée ?)"
        )
    return archive


def _extraire_xlsx(chemin: Path, avertissements: list[str]) -> str:
    plafond = settings.krinos_extraction_max_caracteres
    sortie: list[str] = []
    taille = 0
    try:
        with _ouvrir_ooxml(chemin, "XLSX") as archive:
            partages = _shared_strings(archive)
            for nom_feuille, membre in _feuilles_xlsx(archive):
                sortie.append(f"## Feuille : {nom_feuille}")
                with archive.open(membre) as flux:
                    for ligne in _lignes_feuille(flux, partages):
                        sortie.append(ligne)
                        taille += len(ligne)
                        if taille > plafond:
                            break
                if taille > plafond:
                    avertissements.append(
                        f"XLSX lu partiellement : plafond de {plafond} caractères atteint"
                    )
                    break
    except ErreurExtractionDocument:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErreurExtractionDocument(f"XLSX illisible : {exc}") from exc
    return "\n".join(sortie)


def _feuilles_xlsx(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Feuilles dans l'ordre du classeur : (nom affiché, chemin dans l'archive)."""
    noms = set(archive.namelist())
    feuilles: list[tuple[str, str]] = []
    if "xl/workbook.xml" in noms and "xl/_rels/workbook.xml.rels" in noms:
        with archive.open("xl/_rels/workbook.xml.rels") as flux:
            cibles = {
                r.attrib.get("Id"): r.attrib.get("Target", "")
                for r in ElementTree.parse(flux).getroot()
            }
        with archive.open("xl/workbook.xml") as flux:
            for el in ElementTree.parse(flux).getroot().iter():
                if _local(el.tag) != "sheet":
                    continue
                rid = next((v for k, v in el.attrib.items() if _local(k) == "id"), "")
                cible = cibles.get(rid, "")
                membre = cible.lstrip("/") if cible.startswith("/") else f"xl/{cible}"
                if membre in noms:
                    feuilles.append((el.attrib.get("name", membre), membre))
    if not feuilles:  # classeur atypique : ordre alphabétique des feuilles
        feuilles = [
            (n.rsplit("/", 1)[-1], n)
            for n in sorted(noms)
            if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
        ]
    return feuilles


def _texte_si(si: Any) -> str:
    """Texte d'un <si>/<is> : <t> direct ou runs <r><t>, hors phonétique (<rPh>)."""
    morceaux: list[str] = []
    for enfant in si:
        nom = _local(enfant.tag)
        if nom == "t":
            morceaux.append(enfant.text or "")
        elif nom == "r":
            morceaux.extend(t.text or "" for t in enfant if _local(t.tag) == "t")
    return "".join(morceaux)


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    partages: list[str] = []
    with archive.open("xl/sharedStrings.xml") as flux:
        for _, el in ElementTree.iterparse(flux):
            if _local(el.tag) == "si":
                partages.append(_texte_si(el))
                el.clear()
    return partages


def _lignes_feuille(flux: Any, partages: list[str]):
    """Rend « L<n> | A: valeur | C: valeur » pour chaque ligne non vide (streaming)."""
    for _, el in ElementTree.iterparse(flux):
        if _local(el.tag) != "row":
            continue
        cellules: list[str] = []
        for i, cellule in enumerate(el, start=1):
            if _local(cellule.tag) != "c":
                continue
            valeur = _valeur_cellule(cellule, partages)
            if not valeur:
                continue
            m = re.match(r"[A-Z]+", cellule.attrib.get("r", ""))
            cellules.append(f"{m.group(0) if m else i}: {valeur}")
        if cellules:
            yield f"L{el.attrib.get('r', '?')} | " + " | ".join(cellules)
        el.clear()


def _valeur_cellule(cellule: Any, partages: list[str]) -> str:
    type_cellule = cellule.attrib.get("t")
    if type_cellule == "inlineStr":
        for enfant in cellule:
            if _local(enfant.tag) == "is":
                return _texte_si(enfant).strip()
        return ""
    v = next((e for e in cellule if _local(e.tag) == "v"), None)
    if v is None or v.text is None:
        return ""
    if type_cellule == "s":
        try:
            return partages[int(v.text)].strip()
        except (ValueError, IndexError):
            return ""
    if type_cellule == "b":
        return "Vrai" if v.text.strip() == "1" else "Faux"
    if type_cellule == "e":
        return ""
    return v.text.strip()


def _extraire_docx(chemin: Path) -> str:
    try:
        with _ouvrir_ooxml(chemin, "DOCX") as archive:
            with archive.open("word/document.xml") as flux:
                racine = ElementTree.parse(flux).getroot()
    except ErreurExtractionDocument:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErreurExtractionDocument(f"DOCX illisible : {exc}") from exc
    corps = next((e for e in racine if _local(e.tag) == "body"), None)
    if corps is None:
        raise ErreurExtractionDocument("DOCX illisible : corps du document absent")
    return "\n".join(_blocs_docx(corps))


def _texte_paragraphe(p: Any) -> str:
    morceaux: list[str] = []
    for el in p.iter():
        nom = _local(el.tag)
        if nom == "t":
            morceaux.append(el.text or "")
        elif nom == "tab":
            morceaux.append("\t")
        elif nom in {"br", "cr"}:
            morceaux.append("\n")
    return "".join(morceaux)


def _blocs_docx(parent: Any):
    """Paragraphes et tableaux (rendus en Markdown) dans l'ordre du document."""
    for el in parent:
        nom = _local(el.tag)
        if nom == "p":
            texte = _texte_paragraphe(el)
            if texte.strip():
                yield texte
        elif nom == "tbl":
            lignes = [
                [
                    " ".join(_texte_paragraphe(p) for p in tc.iter() if _local(p.tag) == "p")
                    for tc in tr
                    if _local(tc.tag) == "tc"
                ]
                for tr in el
                if _local(tr.tag) == "tr"
            ]
            rendu = _table_markdown(lignes) if lignes else ""
            if rendu:
                yield rendu
        elif nom == "sdt":  # contrôle de contenu : le texte est dans sdtContent
            for contenu in el:
                if _local(contenu.tag) == "sdtContent":
                    yield from _blocs_docx(contenu)


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

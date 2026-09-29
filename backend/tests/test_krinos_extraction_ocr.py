"""Tests KRINOS — extraction robuste : PDF (tableaux, OCR), DOCX, XLSX sûrs (#31)."""

from __future__ import annotations

import zipfile

import fitz
import pytest
from sqlmodel import Session

from hermes.agents.krinos import extractor
from hermes.agents.krinos.extractor import (
    ErreurExtractionDocument,
    extraire_document,
    extraire_documents_appel_offre,
)
from hermes.config import settings
from hermes.db.models import AppelOffre, TypeDocument
from hermes.db.session import get_engine

from .test_krinos_extractor import _ao_et_document

TEXTE_SCAN = "Reglement de consultation: date limite 12 mars 2026"


# --------------------------------------------------------------------------- #
# Générateurs de documents
# --------------------------------------------------------------------------- #


def _pdf_texte(pages: list[str]) -> bytes:
    doc = fitz.open()
    for texte in pages:
        page = doc.new_page()
        page.insert_text((72, 100), texte, fontsize=12)
    return doc.tobytes()


def _pdf_scanne(nb_pages: int = 1, texte: str = TEXTE_SCAN) -> bytes:
    """PDF dont les pages sont des images (aucune couche texte), comme un scan."""
    modele = fitz.open()
    p = modele.new_page()
    p.insert_text((72, 100), texte, fontsize=20)
    png = p.get_pixmap(dpi=200).tobytes("png")
    doc = fitz.open()
    for _ in range(nb_pages):
        page = doc.new_page()
        page.insert_image(page.rect, stream=png)
    return doc.tobytes()


def _pdf_tableau() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Bordereau des prix", fontsize=14)
    x0, y0, larg, haut = 72, 100, 120, 30
    cellules = [
        ["Lot", "Designation", "Prix"],
        ["1", "Maintenance", "1200"],
        ["2", "Support", "800"],
    ]
    for i, ligne in enumerate(cellules):
        for j, val in enumerate(ligne):
            r = fitz.Rect(x0 + j * larg, y0 + i * haut, x0 + (j + 1) * larg, y0 + (i + 1) * haut)
            page.draw_rect(r, width=1)
            page.insert_text((r.x0 + 5, r.y0 + 20), val, fontsize=11)
    page.insert_text((72, 300), "Fin du bordereau", fontsize=11)
    return doc.tobytes()


_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(corps: str) -> bytes:
    import io

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<w:document xmlns:w="{_NS_W}"><w:body>{corps}</w:body></w:document>',
        )
    return tampon.getvalue()


def _p(texte: str) -> str:
    return f"<w:p><w:r><w:t>{texte}</w:t></w:r></w:p>"


_NS_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _xlsx(feuilles: dict[str, str], partages: list[str] | None = None) -> bytes:
    """Classeur minimal : `feuilles` = {nom: contenu de <sheetData>}."""
    import io

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        sheets = "".join(
            f'<sheet name="{nom}" sheetId="{i}" r:id="rId{i}"/>'
            for i, nom in enumerate(feuilles, start=1)
        )
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{_NS_S}" xmlns:r="{_NS_R}"><sheets>{sheets}</sheets></workbook>',
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(feuilles) + 1)
        )
        z.writestr("xl/_rels/workbook.xml.rels", f"<Relationships>{rels}</Relationships>")
        if partages is not None:
            si = "".join(f"<si><t>{s}</t></si>" for s in partages)
            z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{_NS_S}">{si}</sst>')
        for i, contenu in enumerate(feuilles.values(), start=1):
            z.writestr(
                f"xl/worksheets/sheet{i}.xml",
                f'<worksheet xmlns="{_NS_S}"><sheetData>{contenu}</sheetData></worksheet>',
            )
    return tampon.getvalue()


def _extraire(nom: str, contenu: bytes, type_doc: TypeDocument):
    with Session(get_engine()) as session:
        document = _ao_et_document(session, nom, contenu, type_doc)
        return extraire_document(document)


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #


def test_pdf_texte_pymupdf_sans_avertissement():
    pdf = _pdf_texte(["Article 1 : objet du marche"])
    extraction = _extraire("ocr/texte.pdf", pdf, TypeDocument.PDF)
    assert "Article 1 : objet du marche" in extraction.texte
    assert extraction.avertissements == ()


def test_pdf_tableau_rendu_en_markdown():
    extraction = _extraire("ocr/tableau.pdf", _pdf_tableau(), TypeDocument.PDF)
    assert "Bordereau des prix" in extraction.texte
    assert "| Lot | Designation | Prix |" in extraction.texte
    assert "| 1 | Maintenance | 1200 |" in extraction.texte
    assert "Fin du bordereau" in extraction.texte
    # Le texte des cellules n'est pas dupliqué hors du tableau.
    assert extraction.texte.count("Maintenance") == 1


def test_pdf_scanne_lu_par_ocr():
    pytest.importorskip("rapidocr")
    extraction = _extraire("ocr/scan.pdf", _pdf_scanne(), TypeDocument.PDF)
    assert "Reglement de consultation" in extraction.texte
    assert "12 mars 2026" in extraction.texte
    assert extraction.avertissements == ()


def test_pdf_scanne_sans_ocr_signale_document_non_lu(monkeypatch):
    monkeypatch.setattr(extractor, "_moteur_ocr", lambda: None)
    extraction = _extraire("ocr/scan_sans_ocr.pdf", _pdf_scanne(2), TypeDocument.PDF)
    assert "Document scanné non lu" in extraction.texte
    assert extraction.texte.startswith("[Document scanné non lu")
    assert any("Document scanné non lu" in a and "1, 2" in a for a in extraction.avertissements)


def test_plafond_pages_ocr(monkeypatch):
    appels: list[int] = []

    def faux_moteur(_png):
        appels.append(1)
        return type("R", (), {"txts": ("texte ocr de la page",)})()

    monkeypatch.setattr(extractor, "_moteur_ocr", lambda: faux_moteur)
    monkeypatch.setattr(settings, "krinos_ocr_max_pages", 2)
    extraction = _extraire("ocr/scan5.pdf", _pdf_scanne(5), TypeDocument.PDF)
    assert len(appels) == 2
    assert extraction.texte.count("texte ocr de la page") == 2
    assert any("plafond OCR de 2 pages" in a and "3, 4, 5" in a for a in extraction.avertissements)


def test_plafond_pages_pdf(monkeypatch):
    monkeypatch.setattr(settings, "krinos_extraction_max_pages", 2)
    extraction = _extraire(
        "ocr/long.pdf", _pdf_texte(["page un", "page deux", "page trois"]), TypeDocument.PDF
    )
    assert "page deux" in extraction.texte
    assert "page trois" not in extraction.texte
    assert any("1 pages non lues" in a for a in extraction.avertissements)


def test_page_blanche_sans_image_n_est_pas_un_scan(monkeypatch):
    monkeypatch.setattr(extractor, "_moteur_ocr", lambda: None)
    doc = fitz.open()
    doc.new_page()
    extraction = _extraire("ocr/blanc.pdf", doc.tobytes(), TypeDocument.PDF)
    assert extraction.avertissements == ()


def test_pdf_illisible_erreur_controlee():
    with pytest.raises(ErreurExtractionDocument):
        _extraire("ocr/casse.pdf", b"%PDF-1.4 pas un vrai pdf", TypeDocument.PDF)


def test_fichier_trop_volumineux_refuse(monkeypatch):
    monkeypatch.setattr(settings, "krinos_extraction_max_octets", 100)
    with pytest.raises(ErreurExtractionDocument, match="trop volumineux"):
        _extraire("ocr/gros.txt", b"x" * 500, TypeDocument.AUTRE)


def test_extraction_ao_remonte_les_avertissements(monkeypatch):
    monkeypatch.setattr(extractor, "_moteur_ocr", lambda: None)
    with Session(get_engine()) as session:
        document = _ao_et_document(session, "ocr/scan_ao.pdf", _pdf_scanne(), TypeDocument.PDF)
        ao = session.get(AppelOffre, document.appel_offre_id)
        rapport = extraire_documents_appel_offre(session, ao, best_effort=True)
    assert rapport.documents_traites == 1
    assert any("Document scanné non lu" in a for a in rapport.avertissements)


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #


def test_docx_paragraphes_et_tableaux():
    corps = (
        _p("Cahier des charges")
        + "<w:tbl><w:tr><w:tc>" + _p("Critere") + "</w:tc><w:tc>" + _p("Poids") + "</w:tc></w:tr>"
        + "<w:tr><w:tc>" + _p("Prix") + "</w:tc><w:tc>" + _p("40") + "</w:tc></w:tr></w:tbl>"
        + _p("Conclusion")
    )
    extraction = _extraire("ocr/a.docx", _docx(corps), TypeDocument.DOCX)
    lignes = extraction.texte.split("\n")
    assert lignes[0] == "Cahier des charges"
    assert "| Critere | Poids |" in extraction.texte
    assert "| Prix | 40 |" in extraction.texte
    assert lignes[-1] == "Conclusion"
    assert "PK" not in extraction.texte  # plus de bruit binaire


def test_docx_corrompu_erreur_controlee():
    with pytest.raises(ErreurExtractionDocument, match="DOCX illisible"):
        _extraire("ocr/casse.docx", b"pas un zip", TypeDocument.DOCX)


def test_docx_entite_xml_refusee():
    piege = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        f'<w:document xmlns:w="{_NS_W}"><w:body>'
        "<w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>"
    )
    import io

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("word/document.xml", piege)
    with pytest.raises(ErreurExtractionDocument):
        _extraire("ocr/xxe.docx", tampon.getvalue(), TypeDocument.DOCX)


# --------------------------------------------------------------------------- #
# XLSX
# --------------------------------------------------------------------------- #


def test_xlsx_lecture_structuree_feuille_ligne_colonne():
    feuille1 = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>Maintenance</t></is></c>'
        '<c r="C2"><v>1200</v></c><c r="D2" t="b"><v>1</v></c></row>'
    )
    feuille2 = '<row r="5"><c r="B5" t="str"><f>1+1</f><v>deux</v></c></row>'
    contenu = _xlsx({"Prix": feuille1, "Notes": feuille2}, partages=["Lot", "Total"])
    texte = _extraire("ocr/a.xlsx", contenu, TypeDocument.XLSX).texte
    assert texte.split("\n") == [
        "## Feuille : Prix",
        "L1 | A: Lot | B: Total",
        "L2 | A: Maintenance | C: 1200 | D: Vrai",
        "## Feuille : Notes",
        "L5 | B: deux",
    ]


def test_xlsx_zip_bomb_refuse_sans_decompresser(monkeypatch):
    monkeypatch.setattr(settings, "krinos_extraction_max_octets_decompresses", 2 * 1024 * 1024)
    gros_texte = "a" * (8 * 1024 * 1024)
    enorme = f'<row r="1"><c r="A1" t="inlineStr"><is><t>{gros_texte}</t></is></c></row>'
    contenu = _xlsx({"Bombe": enorme})
    assert len(contenu) < 100_000  # quelques Ko compressés, des Mo décompressés
    with pytest.raises(ErreurExtractionDocument, match="archive piégée"):
        _extraire("ocr/bombe.xlsx", contenu, TypeDocument.XLSX)


def test_xlsx_entites_xml_refusees():
    piege = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        f'<worksheet xmlns="{_NS_S}"><sheetData><row r="1"><c r="A1" t="inlineStr">'
        "<is><t>&b;</t></is></c></row></sheetData></worksheet>"
    )
    import io

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", piege)
    with pytest.raises(ErreurExtractionDocument, match="XLSX illisible"):
        _extraire("ocr/xxe.xlsx", tampon.getvalue(), TypeDocument.XLSX)


def test_xlsx_plafond_caracteres(monkeypatch):
    monkeypatch.setattr(settings, "krinos_extraction_max_caracteres", 200)
    lignes = "".join(
        f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>ligne numero {i}</t></is></c></row>'
        for i in range(1, 200)
    )
    extraction = _extraire("ocr/long.xlsx", _xlsx({"F": lignes}), TypeDocument.XLSX)
    assert len(extraction.texte) <= 200
    assert any("plafond" in a for a in extraction.avertissements)


def test_endpoint_extraction_expose_les_avertissements(monkeypatch):
    from fastapi.testclient import TestClient

    from hermes.main import app

    monkeypatch.setattr(extractor, "_moteur_ocr", lambda: None)
    with Session(get_engine()) as session:
        document = _ao_et_document(session, "ocr/scan_api.pdf", _pdf_scanne(), TypeDocument.PDF)
        document_id = document.id

    reponse = TestClient(app).post(f"/krinos/documents/{document_id}/extraire")
    assert reponse.status_code == 200
    assert any("Document scanné non lu" in a for a in reponse.json()["avertissements"])

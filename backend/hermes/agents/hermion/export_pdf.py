"""Export PDF d'une réponse HERMION validée (tâche V1 #4).

100 % local : rendu via `fpdf2` (pur Python, aucune dépendance système, ni
service externe — conforme aux invariants HERMES). Le fichier est écrit sous
``storage/exports/`` et son chemin relatif est enregistré dans
``ReponseHermion.chemin_export``. La réponse passe en statut ``EXPORTEE``.

Garde-fou : seule une réponse **validée** (ou déjà exportée — ré-export) peut
être exportée. La validation reste exclusivement humaine ; l'export ne fait
que matérialiser une réponse déjà approuvée.

Note typographie : les polices cœur PDF (Helvetica) sont limitées au jeu
Windows-1252. Le contenu français passe (accents OK) ; les caractères
typographiques hors jeu (guillemets courbes, tiret cadratin, …, €) sont
translittérés. Un rendu typographique parfait (police TTF embarquée) est
hors périmètre V1.
"""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF
from sqlmodel import Session

from hermes.config import settings
from hermes.db.models import (
    AppelOffre,
    LogAgent,
    NiveauLog,
    ReponseHermion,
    StatutReponse,
)

_SOUS_DOSSIER = "exports"

_REMPLACEMENTS = {
    "…": "...",
    "–": "-",
    "—": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "•": "-",
    " ": " ",
    " ": " ",
    "€": " EUR",
    "œ": "oe",
    "Œ": "OE",
}


class ErreurExportPdf(RuntimeError):
    """Erreur contrôlée lors de l'export PDF d'une réponse."""


def exporter_reponse_pdf(session: Session, reponse: ReponseHermion) -> Path:
    """Génère le PDF de la réponse, met à jour son statut, retourne le chemin absolu.

    Lève `ErreurExportPdf` si la réponse n'est pas validée (ou déjà exportée).
    """
    if reponse.id is None:
        raise ErreurExportPdf("Réponse non persistée")

    if reponse.statut not in {StatutReponse.VALIDEE, StatutReponse.EXPORTEE}:
        raise ErreurExportPdf(
            f"Réponse en statut '{reponse.statut.value}' — seule une réponse "
            "validée peut être exportée."
        )

    ao = session.get(AppelOffre, reponse.appel_offre_id)

    dossier = settings.storage_path / _SOUS_DOSSIER
    dossier.mkdir(parents=True, exist_ok=True)
    nom_fichier = f"reponse_{reponse.id}_v{reponse.version}.pdf"
    chemin_absolu = dossier / nom_fichier

    pdf = _construire_pdf(reponse, ao)
    pdf.output(str(chemin_absolu))

    reponse.chemin_export = f"{_SOUS_DOSSIER}/{nom_fichier}"
    reponse.statut = StatutReponse.EXPORTEE
    session.add(reponse)
    session.add(
        LogAgent(
            agent="HERMION",
            niveau=NiveauLog.INFO,
            message=(
                f"Réponse {reponse.id} v{reponse.version} exportée en PDF "
                f"({reponse.chemin_export})"
            ),
            appel_offre_id=reponse.appel_offre_id,
        )
    )
    session.commit()
    session.refresh(reponse)
    return chemin_absolu


# --------------------------------------------------------------------------- #
# Rendu PDF
# --------------------------------------------------------------------------- #


def _construire_pdf(reponse: ReponseHermion, ao: AppelOffre | None) -> FPDF:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.add_page()

    # En-tête : métadonnées AO + version.
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(120, 120, 120)
    entete = f"HERMES — Réponse v{reponse.version}"
    if ao is not None:
        if ao.reference_externe:
            entete += f"  ·  Réf. {ao.reference_externe}"
        if ao.emetteur:
            entete += f"  ·  {ao.emetteur}"
    pdf.multi_cell(0, 5, _net(entete), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    for bloc in re.split(r"\n{2,}", reponse.contenu.strip()):
        _rendre_bloc(pdf, bloc.strip())

    return pdf


def _rendre_bloc(pdf: FPDF, bloc: str) -> None:
    if not bloc:
        return

    if bloc.startswith("# "):
        _titre(pdf, _net(bloc[2:]), taille=18, espace_avant=2, espace_apres=4)
        return
    if bloc.startswith("## "):
        _titre(pdf, _net(bloc[3:]), taille=14, espace_avant=4, espace_apres=2)
        return
    if bloc.startswith("### "):
        _titre(pdf, _net(bloc[4:]), taille=12, espace_avant=3, espace_apres=1)
        return

    lignes = [ligne_brute.strip() for ligne_brute in bloc.split("\n")]
    if lignes and all(re.match(r"^(\d+\.|-|\*)\s+", x) for x in lignes if x):
        pdf.set_font("Helvetica", "", 11)
        for x in lignes:
            if not x:
                continue
            texte = re.sub(r"^(\d+\.|-|\*)\s+", "", x)
            pdf.multi_cell(
                0, 6, _net(f"  -  {_inline(texte)}"),
                new_x="LMARGIN", new_y="NEXT",
            )
        pdf.ln(2)
        return

    # Ligne entièrement en italique (*texte*) → métadonnée discrète.
    if re.fullmatch(r"\*[^*].+\*", bloc):
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(110, 110, 110)
        pdf.multi_cell(0, 5, _net(bloc[1:-1]), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)
        return

    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, _net(_inline(bloc)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _titre(
    pdf: FPDF, texte: str, *, taille: int, espace_avant: int, espace_apres: int
) -> None:
    pdf.ln(espace_avant)
    pdf.set_font("Helvetica", "B", taille)
    pdf.multi_cell(0, taille * 0.5, texte, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(espace_apres)


def _inline(texte: str) -> str:
    """Retire les marqueurs markdown inline (**gras**, *italique*, `code`)."""
    texte = re.sub(r"\*\*(.+?)\*\*", r"\1", texte)
    texte = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", texte)
    texte = re.sub(r"`(.+?)`", r"\1", texte)
    return texte


def _net(texte: str) -> str:
    """Translittère vers le jeu Windows-1252 supporté par les polices cœur."""
    for source, cible in _REMPLACEMENTS.items():
        texte = texte.replace(source, cible)
    return texte.encode("latin-1", "replace").decode("latin-1")

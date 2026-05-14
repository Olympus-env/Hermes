"""KRINOS analyseur — résumé, scoring et tags via PYTHIA.

L'analyseur prend un appel d'offre (et ses documents extraits) et produit :
    - un résumé en français (3-6 phrases)
    - un score de pertinence/réalisabilité 0-100 + justification
    - une liste de tags métier
    - les critères principaux extraits du règlement de consultation

Le résultat est persisté dans `analyses_krinos` et l'AO passe en statut
`StatutAO.ANALYSE`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from hermes.agents import pythia
from hermes.agents.krinos.ponderation import (
    Ponderation,
    calculer_score_final,
    charger_ponderation,
)
from hermes.config import settings
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    Document,
    LogAgent,
    NiveauLog,
    StatutAO,
)

SYSTEM_PROMPT = (
    "Tu es KRINOS, un analyste expert des appels d'offre publics français. "
    "Tu réponds toujours en français, de manière concise, factuelle et neutre. "
    "Tu ne fais aucune hypothèse non étayée par le texte fourni. "
    "Tu produis EXCLUSIVEMENT un objet JSON valide conforme au schéma demandé."
)


class ErreurAnalyseKrinos(RuntimeError):
    """Erreur contrôlée lors de l'analyse KRINOS."""


@dataclass(frozen=True)
class ResultatAnalyse:
    analyse: AnalyseKrinos
    nouveau: bool


async def analyser_ao(
    session: Session,
    appel_offre: AppelOffre,
    *,
    forcer: bool = False,
) -> ResultatAnalyse:
    """Analyse l'AO via PYTHIA et persiste le résultat.

    Si une analyse existe déjà et `forcer` est faux, renvoie l'existante.
    """
    if appel_offre.id is None:
        raise ErreurAnalyseKrinos("Appel d'offre non persisté")

    existante = session.exec(
        select(AnalyseKrinos)
        .where(AnalyseKrinos.appel_offre_id == appel_offre.id)
        .order_by(AnalyseKrinos.cree_le.desc())
    ).first()
    if existante is not None and not forcer:
        return ResultatAnalyse(analyse=existante, nouveau=False)

    ponderation = charger_ponderation(session)
    contexte = _construire_contexte(session, appel_offre)
    prompt = _construire_prompt(contexte, ponderation)

    debut = time.perf_counter()
    try:
        reponse = await pythia.generer(prompt, system=SYSTEM_PROMPT, format_json=True)
    except pythia.ErreurPythia as exc:
        _journaliser(
            session,
            niveau=NiveauLog.ERROR,
            message=f"PYTHIA indisponible pour AO {appel_offre.id} : {exc}",
            appel_offre_id=appel_offre.id,
        )
        raise ErreurAnalyseKrinos(str(exc)) from exc

    try:
        payload = pythia.parser_json_sortie(reponse.texte)
    except pythia.ErreurPythia as exc:
        _journaliser(
            session,
            niveau=NiveauLog.ERROR,
            message=f"Sortie PYTHIA inexploitable pour AO {appel_offre.id} : {exc}",
            appel_offre_id=appel_offre.id,
        )
        raise ErreurAnalyseKrinos("Sortie PYTHIA invalide") from exc

    champs = _normaliser_payload(payload)
    # Score pondéré final si on a les dimensions, sinon fallback sur le score
    # global renvoyé par PYTHIA (rétrocompat).
    if champs["scores_dimensions"]:
        score_final = calculer_score_final(champs["scores_dimensions"], ponderation)
    else:
        score_final = champs["score"]
    duree_ms = int((time.perf_counter() - debut) * 1000)

    analyse = AnalyseKrinos(
        appel_offre_id=appel_offre.id,
        resume=champs["resume"],
        score=score_final,
        justification_score=champs["justification"],
        tags=json.dumps(champs["tags"], ensure_ascii=False) if champs["tags"] else None,
        criteres_extraits=champs["criteres"] or None,
        scores_dimensions=(
            json.dumps(champs["scores_dimensions"], ensure_ascii=False)
            if champs["scores_dimensions"]
            else None
        ),
        duree_analyse_ms=duree_ms,
        modele_llm=reponse.modele,
    )
    session.add(analyse)

    if appel_offre.statut == StatutAO.BRUT:
        appel_offre.statut = StatutAO.ANALYSE
        session.add(appel_offre)

    session.commit()
    session.refresh(analyse)

    _journaliser(
        session,
        niveau=NiveauLog.INFO,
        message=(
            f"Analyse KRINOS terminée pour AO {appel_offre.id} "
            f"(score={analyse.score:.0f}, {duree_ms} ms)"
        ),
        appel_offre_id=appel_offre.id,
    )
    # Le commit du journal a expiré l'instance — recharge pour que les
    # accesseurs restent valides côté caller.
    session.refresh(analyse)

    return ResultatAnalyse(analyse=analyse, nouveau=True)


def _construire_contexte(session: Session, appel_offre: AppelOffre) -> dict[str, Any]:
    documents = session.exec(
        select(Document)
        .where(Document.appel_offre_id == appel_offre.id)
        .order_by(Document.id)
    ).all()

    extraits: list[str] = []
    budget_restant = settings.krinos_contexte_max_caracteres
    for doc in documents:
        if not doc.contenu_extrait or budget_restant <= 0:
            continue
        morceau = doc.contenu_extrait[:budget_restant]
        extraits.append(f"--- {doc.nom_fichier} ---\n{morceau}")
        budget_restant -= len(morceau)

    return {
        "titre": appel_offre.titre,
        "objet": appel_offre.objet or "",
        "emetteur": appel_offre.emetteur or "",
        "budget": appel_offre.budget_estime,
        "devise": appel_offre.devise,
        "date_limite": appel_offre.date_limite.isoformat() if appel_offre.date_limite else "",
        "zone": appel_offre.zone_geographique or "",
        "type_marche": appel_offre.type_marche or "",
        "code_naf": appel_offre.code_naf or "",
        "documents": "\n\n".join(extraits) if extraits else "(aucun document extrait)",
    }


def _construire_prompt(contexte: dict[str, Any], ponderation: Ponderation) -> str:
    poids_lignes = "\n".join(
        f"      - {Ponderation.LIBELLES[d]} ({d}) : {getattr(ponderation, d)} %"
        for d in Ponderation.DIMENSIONS
    )

    return (
        "Analyse l'appel d'offre suivant et renvoie un objet JSON avec ces champs :\n"
        '  - "resume" : string (3 à 6 phrases en français)\n'
        '  - "scores_dimensions" : objet avec un score 0-100 par dimension :\n'
        '      { "affinite_metier", "references", "adequation_budget",\n'
        '        "capacite_equipe", "calendrier" }\n'
        '  - "justification" : string (1 à 3 phrases expliquant le scoring)\n'
        '  - "tags" : tableau de 3 à 8 chaînes (mots-clés métier en français)\n'
        '  - "criteres" : string (critères d\'attribution / exigences principales)\n'
        "\n"
        "Définition des dimensions :\n"
        "  - affinite_metier : correspondance entre l'AO et le savoir-faire/activité\n"
        "  - references      : possibilité d'appuyer sur des références similaires\n"
        "  - adequation_budget : taille du marché vs capacité (ni trop petit ni trop gros)\n"
        "  - capacite_equipe : taille équipe requise / délais vs équipe disponible\n"
        "  - calendrier      : réalisme des délais de réponse et d'exécution\n"
        "\n"
        "Pondération utilisateur (info — ne modifie PAS les scores, scores tout\n"
        "indépendamment, le backend pondère ensuite) :\n"
        f"{poids_lignes}\n"
        "\n"
        "Métadonnées AO :\n"
        f"  titre      : {contexte['titre']}\n"
        f"  émetteur   : {contexte['emetteur']}\n"
        f"  objet      : {contexte['objet']}\n"
        f"  budget     : {contexte['budget']} {contexte['devise']}\n"
        f"  date limite: {contexte['date_limite']}\n"
        f"  zone       : {contexte['zone']}\n"
        f"  type marché: {contexte['type_marche']}\n"
        f"  code NAF   : {contexte['code_naf']}\n"
        "\n"
        "Contenu documentaire extrait :\n"
        f"{contexte['documents']}\n"
        "\n"
        "Réponds en JSON strict, sans texte autour."
    )


def _normaliser_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Valide / coerce la sortie LLM dans une forme prévisible."""
    if not isinstance(payload, dict):
        raise ErreurAnalyseKrinos("Réponse PYTHIA n'est pas un objet JSON")

    resume = str(payload.get("resume") or "").strip()
    if not resume:
        raise ErreurAnalyseKrinos("Résumé manquant dans la réponse PYTHIA")

    # Score global (rétrocompat : si PYTHIA renvoie l'ancien format à un seul score).
    try:
        score_brut = float(payload.get("score", 0))
    except (TypeError, ValueError):
        score_brut = 0.0
    score = max(0.0, min(100.0, score_brut))

    # Scores par dimension — nouveau format
    scores_dimensions: dict[str, float] = {}
    raw_dims = payload.get("scores_dimensions")
    if isinstance(raw_dims, dict):
        for dim in Ponderation.DIMENSIONS:
            valeur = raw_dims.get(dim)
            if valeur is None:
                continue
            try:
                scores_dimensions[dim] = max(0.0, min(100.0, float(valeur)))
            except (TypeError, ValueError):
                continue

    justification = str(payload.get("justification") or "").strip()

    tags_brut = payload.get("tags") or []
    if isinstance(tags_brut, str):
        tags_brut = [tags_brut]
    tags: list[str] = []
    for t in tags_brut:
        if not isinstance(t, (str, int, float)):
            continue
        valeur = str(t).strip()
        if valeur and valeur not in tags:
            tags.append(valeur)

    criteres = payload.get("criteres")
    if isinstance(criteres, list):
        criteres = "\n".join(str(c).strip() for c in criteres if str(c).strip())
    criteres_str = str(criteres or "").strip()

    return {
        "resume": resume,
        "score": score,
        "scores_dimensions": scores_dimensions,
        "justification": justification,
        "tags": tags,
        "criteres": criteres_str,
    }


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

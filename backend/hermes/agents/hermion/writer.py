"""HERMION — rédaction multi-étapes via PYTHIA.

Workflow par défaut :
    1. Génération d'un plan structuré (3 à 6 sections) à partir du contexte AO
       + analyse KRINOS + extraits documentaires.
    2. Rédaction de chaque section en markdown, en réinjectant le plan global.
    3. Assemblage final en un document markdown unique.

La réponse est versionnée par AO (v = max(versions) + 1) et persistée en
statut EN_ATTENTE — la validation finale est humaine.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, func, select

from hermes.agents import pythia
from hermes.config import settings
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    Document,
    LogAgent,
    NiveauLog,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)

SYSTEM_PROMPT_PLAN = (
    "Tu es HERMION, expert français de la réponse aux appels d'offre publics. "
    "Tu structures les réponses de manière claire, factuelle et conforme aux "
    "attendus du règlement de consultation. Tu produis EXCLUSIVEMENT du JSON "
    "valide quand on te le demande, sans texte autour."
)

SYSTEM_PROMPT_SECTION = (
    "Tu es HERMION, expert français de la réponse aux appels d'offre publics. "
    "Tu rédiges des sections en français professionnel, neutre et factuel. "
    "Tu utilises uniquement les informations fournies, sans inventer de "
    "compétences ou de références non vérifiées. Tu produis du markdown clair."
)

NB_SECTIONS_DEFAUT = (3, 6)  # min, max sections imposées au LLM


class ErreurRedactionHermion(RuntimeError):
    """Erreur contrôlée lors d'une rédaction HERMION."""


@dataclass(frozen=True)
class ProfilUtilisateur:
    """Profil minimal injecté dans les prompts (vient du frontend)."""

    prenom: str = ""
    nom: str = ""
    email: str = ""
    entreprise: str = ""
    activite: str = ""

    def en_texte(self) -> str:
        lignes: list[str] = []
        nom_complet = f"{self.prenom} {self.nom}".strip()
        if nom_complet:
            lignes.append(f"Contact : {nom_complet}")
        if self.email:
            lignes.append(f"Email : {self.email}")
        if self.entreprise:
            lignes.append(f"Entreprise : {self.entreprise}")
        if self.activite:
            lignes.append(f"Activité : {self.activite}")
        return "\n".join(lignes) if lignes else "(profil utilisateur non renseigné)"


@dataclass(frozen=True)
class ResultatRedaction:
    reponse: ReponseHermion
    plan: list[dict[str, str]]


async def rediger_reponse(
    session: Session,
    appel_offre: AppelOffre,
    *,
    profil: ProfilUtilisateur | None = None,
    consignes_supplementaires: str | None = None,
) -> ResultatRedaction:
    """Génère une nouvelle version de réponse pour l'AO.

    Une analyse KRINOS est requise — sinon l'opération échoue (HERMION s'appuie
    sur le résumé, le score et les critères extraits par KRINOS).
    """
    if appel_offre.id is None:
        raise ErreurRedactionHermion("Appel d'offre non persisté")

    analyse = session.exec(
        select(AnalyseKrinos)
        .where(AnalyseKrinos.appel_offre_id == appel_offre.id)
        .order_by(AnalyseKrinos.cree_le.desc())
    ).first()
    if analyse is None:
        raise ErreurRedactionHermion(
            "Aucune analyse KRINOS pour cet AO — lancer /krinos/.../analyser d'abord"
        )

    contexte = _construire_contexte(
        session, appel_offre, analyse, profil, consignes_supplementaires
    )

    debut = time.perf_counter()
    plan = await _generer_plan(contexte)
    sections = await _rediger_sections(plan, contexte)
    contenu = _assembler_document(appel_offre, plan, sections)
    duree_ms = int((time.perf_counter() - debut) * 1000)

    version = _prochaine_version(session, appel_offre.id)
    workflow = {
        "nom": "plan_puis_sections",
        "modele": settings.pythia_modele,
        "sections": [s["titre"] for s in plan],
    }
    reponse = ReponseHermion(
        appel_offre_id=appel_offre.id,
        version=version,
        contenu=contenu,
        statut=StatutReponse.EN_ATTENTE,
        workflow_utilise=json.dumps(workflow, ensure_ascii=False),
        longueur_mots=_compter_mots(contenu),
        duree_generation_ms=duree_ms,
    )
    session.add(reponse)

    if appel_offre.statut == StatutAO.A_REPONDRE:
        appel_offre.statut = StatutAO.EN_REDACTION
        session.add(appel_offre)

    session.commit()
    session.refresh(reponse)

    _journaliser(
        session,
        niveau=NiveauLog.INFO,
        message=(
            f"HERMION : réponse v{version} générée pour AO {appel_offre.id} "
            f"({reponse.longueur_mots} mots, {duree_ms} ms)"
        ),
        appel_offre_id=appel_offre.id,
    )
    session.refresh(reponse)

    return ResultatRedaction(reponse=reponse, plan=plan)


# --------------------------------------------------------------------------- #
# Étapes du workflow
# --------------------------------------------------------------------------- #


async def _generer_plan(contexte: dict[str, Any]) -> list[dict[str, str]]:
    mini, maxi = NB_SECTIONS_DEFAUT
    prompt = (
        f"Propose un plan de réponse en {mini} à {maxi} sections pour l'appel "
        "d'offre ci-dessous.\n"
        "IMPORTANT : tous les titres et tous les briefs DOIVENT être rédigés "
        "en français (pas d'anglais, pas de calque type 'Scope of Work').\n"
        "Réponds en JSON strict, sous la forme :\n"
        '  {"sections": [{"titre": "...", "brief": "..."}]}\n'
        "Le 'titre' est court (3-6 mots, français), le 'brief' précise en 1-2 "
        "phrases (en français) ce que doit contenir la section.\n"
        "\n"
        f"{_bloc_contexte(contexte)}"
    )
    try:
        reponse = await pythia.generer(
            prompt, system=SYSTEM_PROMPT_PLAN, format_json=True
        )
        payload = pythia.parser_json_sortie(reponse.texte)
    except pythia.ErreurPythia as exc:
        raise ErreurRedactionHermion(f"PYTHIA — plan : {exc}") from exc

    sections_brut = payload.get("sections") if isinstance(payload, dict) else None
    if not isinstance(sections_brut, list) or not sections_brut:
        raise ErreurRedactionHermion("Plan HERMION vide ou invalide")

    plan: list[dict[str, str]] = []
    for item in sections_brut[:maxi]:
        if not isinstance(item, dict):
            continue
        titre = str(item.get("titre") or "").strip()
        brief = str(item.get("brief") or "").strip()
        if not titre:
            continue
        plan.append({"titre": titre, "brief": brief})
    if len(plan) < mini:
        raise ErreurRedactionHermion(
            f"Plan HERMION trop court ({len(plan)} sections, minimum {mini})"
        )
    return plan


async def _rediger_sections(
    plan: list[dict[str, str]], contexte: dict[str, Any]
) -> list[str]:
    titres = [s["titre"] for s in plan]
    sections_textes: list[str] = []
    for index, section in enumerate(plan, start=1):
        prompt = (
            f"Rédige la section {index}/{len(plan)} d'une réponse à appel d'offre.\n"
            f"Titre de la section    : {section['titre']}\n"
            f"Attendu de la section  : {section['brief'] or '(libre)'}\n"
            f"Plan global de la réponse :\n  - "
            + "\n  - ".join(titres)
            + "\n\n"
            "Contraintes :\n"
            "  - Rédige en français professionnel, factuel, sans superlatifs vides.\n"
            "  - Markdown : un seul titre de niveau 2 (## ) pour la section.\n"
            "  - 150 à 400 mots, paragraphes courts.\n"
            "  - N'invente aucune référence client, certification ou chiffre.\n"
            "\n"
            f"{_bloc_contexte(contexte)}"
        )
        try:
            reponse = await pythia.generer(prompt, system=SYSTEM_PROMPT_SECTION)
        except pythia.ErreurPythia as exc:
            raise ErreurRedactionHermion(
                f"PYTHIA — section '{section['titre']}' : {exc}"
            ) from exc
        sections_textes.append(_normaliser_section(reponse.texte, section["titre"]))
    return sections_textes


def _assembler_document(
    appel_offre: AppelOffre,
    plan: list[dict[str, str]],
    sections: list[str],
) -> str:
    en_tete = [
        f"# Réponse — {appel_offre.titre}",
        "",
    ]
    if appel_offre.emetteur:
        en_tete.append(f"*Émetteur : {appel_offre.emetteur}*")
    if appel_offre.reference_externe:
        en_tete.append(f"*Référence : {appel_offre.reference_externe}*")
    if appel_offre.date_limite:
        en_tete.append(f"*Date limite : {appel_offre.date_limite.date().isoformat()}*")
    en_tete.append("")

    sommaire = ["## Sommaire", ""]
    for index, section in enumerate(plan, start=1):
        sommaire.append(f"{index}. {section['titre']}")
    sommaire.append("")

    return "\n".join(en_tete + sommaire + sections).strip() + "\n"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _construire_contexte(
    session: Session,
    appel_offre: AppelOffre,
    analyse: AnalyseKrinos,
    profil: ProfilUtilisateur | None,
    consignes_supplementaires: str | None,
) -> dict[str, Any]:
    tags: list[str] = []
    if analyse.tags:
        try:
            valeurs = json.loads(analyse.tags)
            if isinstance(valeurs, list):
                tags = [str(v) for v in valeurs]
        except json.JSONDecodeError:
            tags = []

    documents = session.exec(
        select(Document)
        .where(Document.appel_offre_id == appel_offre.id)
        .order_by(Document.id)
    ).all()

    # Budget de caractères plus serré qu'en analyse — HERMION envoie le contexte
    # à chaque section, ce qui multiplie le coût d'inférence.
    budget = max(2000, settings.krinos_contexte_max_caracteres // 2)
    extraits: list[str] = []
    for doc in documents:
        if not doc.contenu_extrait or budget <= 0:
            continue
        morceau = doc.contenu_extrait[:budget]
        extraits.append(f"--- {doc.nom_fichier} ---\n{morceau}")
        budget -= len(morceau)

    return {
        "ao": {
            "titre": appel_offre.titre,
            "emetteur": appel_offre.emetteur or "",
            "objet": appel_offre.objet or "",
            "budget": appel_offre.budget_estime,
            "devise": appel_offre.devise,
            "date_limite": (
                appel_offre.date_limite.isoformat() if appel_offre.date_limite else ""
            ),
            "type_marche": appel_offre.type_marche or "",
            "zone": appel_offre.zone_geographique or "",
            "code_naf": appel_offre.code_naf or "",
        },
        "analyse": {
            "resume": analyse.resume,
            "score": analyse.score,
            "justification": analyse.justification_score,
            "tags": tags,
            "criteres": analyse.criteres_extraits or "",
        },
        "documents": "\n\n".join(extraits) if extraits else "(aucun extrait documentaire)",
        "profil": (profil or ProfilUtilisateur()).en_texte(),
        "consignes": (consignes_supplementaires or "").strip(),
    }


def _bloc_contexte(contexte: dict[str, Any]) -> str:
    ao = contexte["ao"]
    analyse = contexte["analyse"]
    lignes = [
        "## Appel d'offre",
        f"Titre      : {ao['titre']}",
        f"Émetteur   : {ao['emetteur']}",
        f"Objet      : {ao['objet']}",
        f"Budget     : {ao['budget']} {ao['devise']}",
        f"Date limite: {ao['date_limite']}",
        f"Type marché: {ao['type_marche']}",
        f"Zone       : {ao['zone']}",
        f"Code NAF   : {ao['code_naf']}",
        "",
        "## Analyse KRINOS",
        f"Score      : {analyse['score']:.0f}/100",
        f"Résumé     : {analyse['resume']}",
        f"Tags       : {', '.join(analyse['tags']) if analyse['tags'] else '(aucun)'}",
        f"Critères   : {analyse['criteres'] or '(non précisés)'}",
        "",
        "## Profil du répondant",
        contexte["profil"],
    ]
    if contexte["consignes"]:
        lignes.extend(["", "## Consignes utilisateur", contexte["consignes"]])
    lignes.extend(["", "## Extraits documentaires", contexte["documents"]])
    return "\n".join(lignes)


def _normaliser_section(texte: str, titre: str) -> str:
    """S'assure que la section commence bien par un titre de niveau 2.

    Si le LLM oublie le `## titre`, on le préfixe ; s'il met un `#` ou un titre
    différent, on remplace par celui du plan pour rester cohérent.
    """
    contenu = texte.strip().strip("`").strip()
    if contenu.lower().startswith("markdown\n"):
        contenu = contenu[len("markdown\n") :].strip()

    lignes = contenu.splitlines()
    if lignes and lignes[0].lstrip().startswith("#"):
        lignes[0] = f"## {titre}"
    else:
        lignes.insert(0, f"## {titre}")
        lignes.insert(1, "")
    return "\n".join(lignes).strip() + "\n"


def _prochaine_version(session: Session, ao_id: int) -> int:
    max_version = session.exec(
        select(func.max(ReponseHermion.version)).where(
            ReponseHermion.appel_offre_id == ao_id
        )
    ).one()
    return int(max_version or 0) + 1


def _compter_mots(texte: str) -> int:
    return len([m for m in texte.split() if m.strip()])


def _journaliser(
    session: Session,
    *,
    niveau: NiveauLog,
    message: str,
    appel_offre_id: int,
) -> None:
    session.add(
        LogAgent(
            agent="HERMION",
            niveau=niveau,
            message=message,
            appel_offre_id=appel_offre_id,
        )
    )
    session.commit()

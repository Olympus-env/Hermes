"""Orchestrateur — pipeline autonome ARGOS → KRINOS → HERMION (tâche V1 #2).

Sans intervention humaine, après chaque collecte :

    1. AO `BRUT` → téléchargement + extraction documentaire (best-effort),
       puis analyse KRINOS (résumé, score pondéré, tags) → statut `ANALYSE`.
    2. AO `ANALYSE` dont le score ≥ seuil configuré et sans réponse →
       statut `A_REPONDRE` puis rédaction HERMION → `ReponseHermion`
       en `EN_ATTENTE` (validation humaine obligatoire) → AO `EN_REDACTION`.

La configuration (interrupteur d'autonomie, seuil, plafond par cycle) est
persistée dans `parametres` sous `orchestration.config`, même pattern que
`argos.filtre` / `krinos.ponderation_scoring` / `hermion.workflow`.

Invariant HERMES : aucune soumission automatique. HERMION rédige et s'arrête
en `EN_ATTENTE` — la validation finale reste exclusivement humaine.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger
from sqlmodel import Session, select

from hermes.agents.hermion import ErreurRedactionHermion, rediger_reponse
from hermes.agents.krinos import (
    ErreurAnalyseKrinos,
    analyser_ao,
    jev,
    telecharger_documents_ao,
)
from hermes.agents.krinos.analyzer import _profil_metier
from hermes.agents.krinos.extractor import extraire_documents_appel_offre_async
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    LogAgent,
    NiveauLog,
    Parametre,
    Portail,
    ReponseHermion,
    StatutAO,
    TypePortail,
)

CLE_PARAMETRE = "orchestration.config"

SEUIL_MIN = 0.0
SEUIL_MAX = 100.0
MAX_PAR_CYCLE_PLAFOND = 50

# Verrou global : un seul pipeline à la fois dans le process. Les jobs BOAMP et
# TED (et `POST /orchestration/traiter`) sélectionnent les mêmes AO ; sans lui,
# analyses KRINOS et réponses HERMION seraient produites en double (#13).
# Jobs planifiés : ils attendent leur tour. API manuelle : 409 (voir api/).
_VERROU_PIPELINE = asyncio.Lock()


def pipeline_en_cours() -> bool:
    """Vrai si un pipeline est déjà en train de tourner."""
    return _VERROU_PIPELINE.locked()


@dataclass(frozen=True)
class ConfigOrchestration:
    """Réglages du pipeline autonome."""

    actif: bool = True
    seuil_score: float = 70.0
    auto_rediger: bool = True
    max_par_cycle: int = 5

    def en_dict(self) -> dict[str, object]:
        return {
            "actif": self.actif,
            "seuil_score": self.seuil_score,
            "auto_rediger": self.auto_rediger,
            "max_par_cycle": self.max_par_cycle,
        }


@dataclass
class RapportOrchestration:
    """Synthèse d'un passage du pipeline."""

    actif: bool = True
    ao_analyses: int = 0
    ao_rediges: int = 0
    ao_sous_seuil: int = 0
    # AO au-dessus du seuil mais drapeautés par KRINOS : décision humaine requise.
    ao_a_verifier: int = 0
    ao_echecs: int = 0
    details: list[dict[str, object]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Configuration (MNEMOSYNE)
# --------------------------------------------------------------------------- #


def charger_config(session: Session) -> ConfigOrchestration:
    """Charge la config ; valeurs par défaut si absente ou illisible."""
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None or not entree.valeur:
        return ConfigOrchestration()
    try:
        data = json.loads(entree.valeur)
    except json.JSONDecodeError:
        return ConfigOrchestration()
    if not isinstance(data, dict):
        return ConfigOrchestration()
    defaut = ConfigOrchestration()
    return ConfigOrchestration(
        actif=bool(data.get("actif", defaut.actif)),
        seuil_score=_seuil_valide(data.get("seuil_score"), defaut.seuil_score),
        auto_rediger=bool(data.get("auto_rediger", defaut.auto_rediger)),
        max_par_cycle=_plafond_valide(
            data.get("max_par_cycle"), defaut.max_par_cycle
        ),
    )


def enregistrer_config(
    session: Session, cfg: ConfigOrchestration
) -> ConfigOrchestration:
    """Persiste la config en normalisant seuil et plafond."""
    nettoye = ConfigOrchestration(
        actif=bool(cfg.actif),
        seuil_score=_seuil_valide(cfg.seuil_score, 70.0),
        auto_rediger=bool(cfg.auto_rediger),
        max_par_cycle=_plafond_valide(cfg.max_par_cycle, 5),
    )
    payload = json.dumps(nettoye.en_dict(), ensure_ascii=False)
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None:
        entree = Parametre(
            cle=CLE_PARAMETRE,
            valeur=payload,
            description="Orchestration — pipeline autonome (JSON)",
        )
    else:
        entree.valeur = payload
        entree.maj_le = datetime.now(UTC)
    session.add(entree)
    session.commit()
    return nettoye


# --------------------------------------------------------------------------- #
# Expiration automatique
# --------------------------------------------------------------------------- #

# Statuts périmables : AO sans réponse rédigée. On ne touche jamais aux statuts
# portant un travail ou une décision (EN_REDACTION a une réponse en cours,
# REPONDU/REJETE sont finaux ; HORS_FILTRE est déjà écarté).
_STATUTS_EXPIRABLES = (StatutAO.BRUT, StatutAO.ANALYSE, StatutAO.A_REPONDRE)


def expirer_ao_depasses(
    session: Session, *, maintenant: datetime | None = None
) -> int:
    """Passe en `EXPIRE` les AO périmables dont la date limite est dépassée.

    Comparaison au **jour** : un AO reste actif tout le jour de sa date limite
    (beaucoup d'échéances n'ont que la date, à minuit) — on n'expire qu'à partir
    du lendemain. Renvoie le nombre d'AO expirés.
    """
    maintenant = maintenant or datetime.now(UTC)
    seuil = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)

    candidats = session.exec(
        select(AppelOffre).where(AppelOffre.statut.in_(_STATUTS_EXPIRABLES))
    ).all()

    expires = 0
    for ao in candidats:
        limite = ao.date_limite
        if limite is None:
            continue
        if limite.tzinfo is None:
            limite = limite.replace(tzinfo=UTC)
        if limite < seuil:
            ao.statut = StatutAO.EXPIRE
            ao.maj_le = maintenant
            session.add(ao)
            expires += 1

    if expires:
        _journaliser(
            session,
            niveau=NiveauLog.INFO,
            message=f"Expiration automatique : {expires} AO périmés passés en EXPIRE",
        )
    return expires


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


async def traiter_pipeline(
    session: Session, *, limite: int | None = None
) -> RapportOrchestration:
    """Exécute un passage complet du pipeline autonome (un seul à la fois).

    Les appels concurrents sont sérialisés par un verrou global : le second
    attend la fin du premier, puis ne retrouve plus les AO déjà traités.

    Robuste : chaque AO est traité indépendamment ; un échec (PYTHIA down,
    document illisible…) n'interrompt pas le cycle et laisse l'AO récupérable
    au prochain passage. Aucune exception n'est propagée.
    """
    async with _VERROU_PIPELINE:
        return await _traiter_pipeline_verrouille(session, limite)


async def _traiter_pipeline_verrouille(
    session: Session, limite: int | None
) -> RapportOrchestration:
    # Reprise : un arrêt du process pendant la rédaction laisse des AO en
    # A_REPONDRE sans réponse. Sous verrou, aucune rédaction du pipeline n'est
    # en cours : on les repasse en ANALYSE pour que la phase rédaction les reprenne.
    _reprendre_a_repondre_orphelins(session)

    # Maintenance systématique : on périme les AO dont la date limite est
    # passée, indépendamment de l'autonomie (un AO expiré ne doit ni être
    # analysé ni rédigé). Exécuté en tête, avant le court-circuit `cfg.actif`.
    expirer_ao_depasses(session)

    cfg = charger_config(session)
    rapport = RapportOrchestration(actif=cfg.actif)
    if not cfg.actif:
        return rapport

    plafond = min(limite or cfg.max_par_cycle, MAX_PAR_CYCLE_PLAFOND)

    await _phase_analyse(session, cfg, plafond, rapport)
    if cfg.auto_rediger:
        await _phase_redaction(session, cfg, plafond, rapport)

    if rapport.ao_analyses or rapport.ao_rediges or rapport.ao_echecs:
        _journaliser(
            session,
            niveau=NiveauLog.INFO,
            message=(
                f"Pipeline autonome : {rapport.ao_analyses} analysés, "
                f"{rapport.ao_rediges} mis en rédaction, "
                f"{rapport.ao_sous_seuil} sous le seuil, "
                f"{rapport.ao_echecs} échecs"
            ),
        )
    return rapport


async def _phase_analyse(
    session: Session,
    cfg: ConfigOrchestration,
    plafond: int,
    rapport: RapportOrchestration,
) -> None:
    """AO BRUT → docs (best-effort) → analyse KRINOS."""
    requete = select(AppelOffre).where(AppelOffre.statut == StatutAO.BRUT)
    # Le marquage « hors profil (Jev) » n'écarte de PYTHIA que tant que le pré-tri
    # est actif : sinon (réglage coupé, clé retirée) l'AO redevient analysable
    # et ne reste jamais BRUT en silence.
    if jev.pretri_actif(session):
        requete = requete.where(AppelOffre.hors_profil_jev == False)  # noqa: E712
    bruts = session.exec(requete.order_by(AppelOffre.cree_le).limit(plafond)).all()

    for ao in bruts:
        ao_id = ao.id
        try:
            if await _pretri_jev(session, ao):
                rapport.details.append({"ao_id": ao_id, "action": "hors_profil_jev"})
                continue
            await _documents_best_effort(session, ao)
            resultat = await analyser_ao(session, ao)
            rapport.ao_analyses += 1
            # Analysé : le badge « Hors profil (Jev) » n'a plus lieu d'être (pré-tri
            # coupé depuis le marquage, par exemple).
            if ao.hors_profil_jev:
                ao.hors_profil_jev = False
                session.add(ao)
                session.commit()
            rapport.details.append(
                {
                    "ao_id": ao_id,
                    "action": "analyse",
                    "score": round(resultat.analyse.score, 1),
                }
            )
        except ErreurAnalyseKrinos as exc:
            # AO laissé en BRUT : retry au prochain cycle.
            rapport.ao_echecs += 1
            _journaliser(
                session,
                niveau=NiveauLog.WARNING,
                message=f"Pipeline : analyse AO {ao_id} échouée — {exc}",
                appel_offre_id=ao_id,
            )
        except Exception as exc:  # noqa: BLE001
            rapport.ao_echecs += 1
            logger.exception("Pipeline : erreur inattendue analyse AO {}", ao_id)
            _journaliser(
                session,
                niveau=NiveauLog.ERROR,
                message=f"Pipeline : erreur inattendue AO {ao_id} — {exc}",
                appel_offre_id=ao_id,
            )


async def _pretri_jev(session: Session, ao: AppelOffre) -> bool:
    """Pré-tri Jev (opt-in) : True si l'AO est jugé hors profil (donc non analysé).

    Portails publics uniquement. Toute panne / budget épuisé / portail non public
    → False (analyse normale). L'AO n'est jamais supprimé ni rejeté : il reste
    BRUT, marqué, et l'utilisateur peut forcer l'analyse.
    """
    if not jev.pretri_actif(session):
        return False
    # Déjà évalué (jugé pertinent puis analyse échouée, ou analyse forcée par
    # l'utilisateur) : ne pas consommer de budget Jev à chaque cycle.
    if ao.pertinence_jev is not None:
        return False
    portail = session.get(Portail, ao.portail_id) if ao.portail_id else None
    if portail is None or portail.type != TypePortail.PUBLIC:
        return False
    ao_id = ao.id
    state = jev.construire_state(
        titre=ao.titre or "",
        objet=ao.objet or "",
        acheteur=ao.emetteur or "",
        type_marche=ao.type_marche or "",
        budget=f"{ao.budget_estime} {ao.devise}" if ao.budget_estime else "",
        date_limite=ao.date_limite.isoformat() if ao.date_limite else "",
        profil_metier=_profil_metier(session),
        extrait_documents="",
    )
    try:
        pertinence = await jev.evaluer_pertinence(session, state)
    except jev.ErreurJev as exc:
        _journaliser(
            session,
            niveau=NiveauLog.INFO,
            message=f"Pré-tri Jev ignoré pour AO {ao_id} (analyse normale) : {exc}",
            appel_offre_id=ao_id,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — le pré-tri ne doit jamais bloquer le pipeline
        logger.warning("Pré-tri Jev : erreur inattendue AO {} — {}", ao_id, type(exc).__name__)
        return False
    seuil = jev.pretri_seuil(session)
    ao.pertinence_jev = pertinence
    if pertinence >= seuil:
        session.add(ao)
        session.commit()
        return False
    ao.hors_profil_jev = True
    session.add(ao)
    session.commit()
    _journaliser(
        session,
        niveau=NiveauLog.INFO,
        message=(
            f"AO {ao_id} hors profil (Jev) : pertinence {pertinence:.2f} < seuil "
            f"{seuil:.2f} — non analysé par PYTHIA, analyse forçable"
        ),
        appel_offre_id=ao_id,
    )
    return True


async def _phase_redaction(
    session: Session,
    cfg: ConfigOrchestration,
    plafond: int,
    rapport: RapportOrchestration,
) -> None:
    """AO ANALYSE au-dessus du seuil et sans réponse → rédaction HERMION."""
    candidats = session.exec(
        select(AppelOffre)
        .where(AppelOffre.statut == StatutAO.ANALYSE)
        .order_by(AppelOffre.cree_le)
    ).all()

    rediges = 0
    for ao in candidats:
        if rediges >= plafond:
            break
        ao_id = ao.id

        analyse = session.exec(
            select(AnalyseKrinos)
            .where(AnalyseKrinos.appel_offre_id == ao_id)
            .order_by(AnalyseKrinos.cree_le.desc())
        ).first()
        if analyse is None:
            continue

        if analyse.score < cfg.seuil_score:
            rapport.ao_sous_seuil += 1
            continue

        # Garde-fou KRINOS : injection suspectée / résultat incohérent → jamais de
        # promotion automatique, l'AO reste en ANALYSE pour décision humaine.
        if analyse.suspect_injection or analyse.a_verifier:
            rapport.ao_a_verifier += 1
            continue

        deja = session.exec(
            select(ReponseHermion.id).where(
                ReponseHermion.appel_offre_id == ao_id
            )
        ).first()
        if deja is not None:
            continue

        ao.statut = StatutAO.A_REPONDRE
        session.add(ao)
        session.commit()

        try:
            await rediger_reponse(session, ao)
            rediges += 1
            rapport.ao_rediges += 1
            rapport.details.append(
                {
                    "ao_id": ao_id,
                    "action": "redaction",
                    "score": round(analyse.score, 1),
                }
            )
        except ErreurRedactionHermion as exc:
            # Rédaction non produite : on revient à ANALYSE pour que la
            # sélection du prochain cycle retente le même AO.
            _restaurer_analyse_si_aucune_reponse(session, ao)
            rapport.ao_echecs += 1
            _journaliser(
                session,
                niveau=NiveauLog.WARNING,
                message=f"Pipeline : rédaction AO {ao_id} échouée — {exc}",
                appel_offre_id=ao_id,
            )
        except Exception as exc:  # noqa: BLE001
            _restaurer_analyse_si_aucune_reponse(session, ao)
            rapport.ao_echecs += 1
            logger.exception("Pipeline : erreur inattendue rédaction AO {}", ao_id)
            _journaliser(
                session,
                niveau=NiveauLog.ERROR,
                message=f"Pipeline : erreur inattendue rédaction AO {ao_id} — {exc}",
                appel_offre_id=ao_id,
            )


async def _documents_best_effort(session: Session, ao: AppelOffre) -> None:
    """Télécharge + extrait les documents sans jamais faire échouer le cycle.

    KRINOS sait analyser sur les seules métadonnées si aucun document n'est
    exploitable : le téléchargement est un bonus, pas un prérequis.
    """
    try:
        await telecharger_documents_ao(session, ao)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pipeline : téléchargement docs AO {} ignoré — {}", ao.id, exc)

    # Hors boucle async : l'OCR/PDF d'un gros DCE bloquerait tout FastAPI.
    rapport = await extraire_documents_appel_offre_async(session, ao, best_effort=True)
    for erreur in rapport.erreurs:
        logger.debug("Pipeline : extraction AO {} ignorée — {}", ao.id, erreur)
    for avertissement in rapport.avertissements:
        logger.warning("Pipeline : extraction AO {} incomplète — {}", ao.id, avertissement)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _seuil_valide(valeur: object, defaut: float) -> float:
    try:
        f = float(valeur)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defaut
    return max(SEUIL_MIN, min(SEUIL_MAX, round(f, 1)))


def _plafond_valide(valeur: object, defaut: int) -> int:
    try:
        n = int(valeur)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defaut
    return max(1, min(MAX_PAR_CYCLE_PLAFOND, n))


def _reprendre_a_repondre_orphelins(session: Session) -> int:
    """Repasse en ANALYSE les AO `A_REPONDRE` sans aucune réponse HERMION."""
    orphelins = session.exec(
        select(AppelOffre).where(
            AppelOffre.statut == StatutAO.A_REPONDRE,
            ~select(ReponseHermion.id)
            .where(ReponseHermion.appel_offre_id == AppelOffre.id)
            .exists(),
        )
    ).all()
    for ao in orphelins:
        ao.statut = StatutAO.ANALYSE
        ao.maj_le = datetime.now(UTC)
        session.add(ao)
    if orphelins:
        session.commit()
        logger.info("Pipeline : {} AO A_REPONDRE orphelins repris", len(orphelins))
    return len(orphelins)


def _restaurer_analyse_si_aucune_reponse(session: Session, ao: AppelOffre) -> None:
    if ao.id is None:
        return
    existe = session.exec(
        select(ReponseHermion.id).where(ReponseHermion.appel_offre_id == ao.id)
    ).first()
    if existe is None and ao.statut == StatutAO.A_REPONDRE:
        ao.statut = StatutAO.ANALYSE
        ao.maj_le = datetime.now(UTC)
        session.add(ao)
        session.commit()


def _journaliser(
    session: Session,
    *,
    niveau: NiveauLog,
    message: str,
    appel_offre_id: int | None = None,
) -> None:
    session.add(
        LogAgent(
            agent="HERMES",
            niveau=niveau,
            message=message,
            appel_offre_id=appel_offre_id,
        )
    )
    session.commit()

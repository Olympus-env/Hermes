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

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger
from sqlmodel import Session, select

from hermes.agents.hermion import ErreurRedactionHermion, rediger_reponse
from hermes.agents.krinos import (
    ErreurAnalyseKrinos,
    analyser_ao,
    telecharger_documents_ao,
)
from hermes.agents.krinos.extractor import ErreurExtractionDocument, extraire_document
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    LogAgent,
    NiveauLog,
    Parametre,
    ReponseHermion,
    StatutAO,
)

CLE_PARAMETRE = "orchestration.config"

SEUIL_MIN = 0.0
SEUIL_MAX = 100.0
MAX_PAR_CYCLE_PLAFOND = 50


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
    """Exécute un passage complet du pipeline autonome.

    Robuste : chaque AO est traité indépendamment ; un échec (PYTHIA down,
    document illisible…) n'interrompt pas le cycle et laisse l'AO récupérable
    au prochain passage. Aucune exception n'est propagée.
    """
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
    bruts = session.exec(
        select(AppelOffre)
        .where(AppelOffre.statut == StatutAO.BRUT)
        .order_by(AppelOffre.cree_le)
        .limit(plafond)
    ).all()

    for ao in bruts:
        ao_id = ao.id
        try:
            await _documents_best_effort(session, ao)
            resultat = await analyser_ao(session, ao)
            rapport.ao_analyses += 1
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
            logger.exception("Pipeline : erreur inattendue analyse AO %s", ao_id)
            _journaliser(
                session,
                niveau=NiveauLog.ERROR,
                message=f"Pipeline : erreur inattendue AO {ao_id} — {exc}",
                appel_offre_id=ao_id,
            )


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
            # AO laissé en A_REPONDRE : reprenable manuellement ou au prochain
            # cycle (la garde "déjà une réponse" ne bloque pas tant qu'aucune
            # version n'a été produite).
            rapport.ao_echecs += 1
            _journaliser(
                session,
                niveau=NiveauLog.WARNING,
                message=f"Pipeline : rédaction AO {ao_id} échouée — {exc}",
                appel_offre_id=ao_id,
            )
        except Exception as exc:  # noqa: BLE001
            rapport.ao_echecs += 1
            logger.exception("Pipeline : erreur inattendue rédaction AO %s", ao_id)
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
        resultats = await telecharger_documents_ao(session, ao)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pipeline : téléchargement docs AO %s ignoré — %s", ao.id, exc)
        return

    for resultat in resultats:
        if not resultat.nouveau:
            continue
        document = resultat.document
        try:
            extraction = extraire_document(document)
        except ErreurExtractionDocument as exc:
            logger.debug(
                "Pipeline : extraction doc %s ignorée — %s", document.id, exc
            )
            continue
        document.contenu_extrait = extraction.texte
        document.checksum_sha256 = extraction.checksum_sha256
        document.taille_octets = extraction.taille_octets
        session.add(document)
        session.commit()


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

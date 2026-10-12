"""MNEMOSYNE — politique de rétention (CDC §8.2) et job de maintenance quotidien.

- logs agents : supprimés après 30 jours ;
- AO rejetés depuis plus de 90 jours : archivés (masqués, conservés en BDD) ;
- AO validés/exportés et leurs réponses : jamais touchés ;
- documents d'un AO inactif : purge manuelle des fichiers (lignes et checksums gardés).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlmodel import Session, col, delete, select

from hermes.config import settings
from hermes.db.models import (
    AppelOffre,
    Document,
    LogAgent,
    NiveauLog,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)
from hermes.db.sauvegarde import (
    ResultatSauvegarde,
    dossier_sauvegarde,
    sauvegarder_base,
    sauvegardes_conservees,
)

RETENTION_LOGS_JOURS = 30
RETENTION_REJETES_JOURS = 90
# AO « actifs » : leurs documents servent encore (analyse, rédaction).
STATUTS_ACTIFS = {StatutAO.BRUT, StatutAO.ANALYSE, StatutAO.A_REPONDRE, StatutAO.EN_REDACTION}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def purger_logs(session: Session, *, maintenant: datetime | None = None) -> int:
    seuil = (maintenant or datetime.now(UTC)) - timedelta(days=RETENTION_LOGS_JOURS)
    res = session.exec(delete(LogAgent).where(col(LogAgent.cree_le) < seuil))
    session.commit()
    return res.rowcount or 0


def a_reponse_finalisee(session: Session, ao_id: int) -> bool:
    return session.exec(
        select(ReponseHermion.id).where(
            ReponseHermion.appel_offre_id == ao_id,
            col(ReponseHermion.statut).in_({StatutReponse.VALIDEE, StatutReponse.EXPORTEE}),
        )
    ).first() is not None


def archiver_ao_rejetes(session: Session, *, maintenant: datetime | None = None) -> int:
    """Archive les AO `rejete` dont le dernier changement date de plus de 90 jours."""
    seuil = (maintenant or datetime.now(UTC)) - timedelta(days=RETENTION_REJETES_JOURS)
    candidats = session.exec(
        select(AppelOffre).where(AppelOffre.statut == StatutAO.REJETE, ~AppelOffre.archive)
    ).all()
    n = 0
    for ao in candidats:
        if _aware(ao.maj_le) < seuil and not a_reponse_finalisee(session, ao.id):
            ao.archive = True
            session.add(ao)
            n += 1
    session.commit()
    return n


class PurgeRefusee(Exception):
    """AO encore actif ou protégé par une réponse validée/exportée."""


def purger_documents(session: Session, ao: AppelOffre) -> tuple[int, int]:
    """Supprime du disque les fichiers d'un AO non actif. Renvoie (fichiers, octets).

    Les lignes `documents` (nom, checksum SHA-256, taille) restent ; `purge_le` est posé.
    """
    if ao.statut in STATUTS_ACTIFS:
        raise PurgeRefusee("AO encore actif : ses documents sont conservés")
    if a_reponse_finalisee(session, ao.id):
        raise PurgeRefusee("AO avec réponse validée ou exportée : jamais purgé")
    racine = settings.storage_path.resolve()
    fichiers = octets = 0
    for doc in session.exec(
        select(Document).where(Document.appel_offre_id == ao.id, col(Document.purge_le).is_(None))
    ).all():
        chemin = (racine / doc.chemin_local).resolve()
        if racine in chemin.parents and chemin.is_file():  # jamais hors du stockage
            octets += chemin.stat().st_size
            chemin.unlink()
            fichiers += 1
        doc.purge_le = datetime.now(UTC)
        session.add(doc)
    session.add(
        LogAgent(
            agent="HERMES",
            niveau=NiveauLog.INFO,
            message=f"MNEMOSYNE : documents purgés ({fichiers} fichier(s), {octets} octets)",
            appel_offre_id=ao.id,
        )
    )
    session.commit()
    return fichiers, octets


def sauvegarder_maintenant(session: Session) -> ResultatSauvegarde:
    return sauvegarder_base(
        Path(dossier_sauvegarde(session)), conservees=sauvegardes_conservees(session)
    )


def maintenance_mnemosyne(session: Session) -> dict:
    """Job quotidien : sauvegarde, purge des logs, archivage des AO rejetés."""
    bilan: dict = {}
    try:
        res = sauvegarder_maintenant(session)
        bilan["sauvegarde"] = res.chemin.name
    except Exception:  # noqa: BLE001 — la rétention doit tourner même si le disque est plein
        logger.exception("MNEMOSYNE : échec de la sauvegarde quotidienne")
        bilan["sauvegarde"] = None
    bilan["logs_purges"] = purger_logs(session)
    bilan["ao_archives"] = archiver_ao_rejetes(session)
    session.add(
        LogAgent(
            agent="HERMES",
            niveau=NiveauLog.INFO if bilan["sauvegarde"] else NiveauLog.ERROR,
            message=f"MNEMOSYNE maintenance : {bilan}",
        )
    )
    session.commit()
    return bilan

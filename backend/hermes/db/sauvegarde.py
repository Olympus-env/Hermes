"""MNEMOSYNE — sauvegarde cohérente de la BDD SQLite (CDC §8.2).

Copie via `sqlite3.Connection.backup` (API de sauvegarde en ligne de SQLite) :
cohérente même en mode WAL avec des écritures en cours, contrairement à une copie
du fichier `.db` qui ignorerait le `-wal`. Sauvegarde locale uniquement.

ATTENTION : la clé maître (`master.key`) n'est JAMAIS copiée ici. Une sauvegarde
seule ne permet donc pas de relire les credentials chiffrés des portails ; la clé
doit être conservée séparément. Si le dossier de sauvegarde contient la clé,
`avertissements_dossier` le signale.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from sqlmodel import Session

from hermes.config import settings
from hermes.db.models import Parametre

CLE_DOSSIER = "mnemosyne.dossier_sauvegarde"
CLE_CONSERVEES = "mnemosyne.sauvegardes_conservees"
_MOTIF = re.compile(r"^hermes-(\d{8})\.db$")


@dataclass
class ResultatSauvegarde:
    chemin: Path
    taille_octets: int
    supprimees: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)


def _lire_parametre(session: Session, cle: str) -> str | None:
    entree = session.get(Parametre, cle)
    return entree.valeur.strip() if entree and entree.valeur and entree.valeur.strip() else None


def dossier_sauvegarde(session: Session) -> Path:
    """Dossier configuré (paramètre `parametres`), sinon `settings.backup_path`."""
    valeur = _lire_parametre(session, CLE_DOSSIER)
    return Path(valeur) if valeur else settings.backup_path


def sauvegardes_conservees(session: Session) -> int:
    """Nombre de sauvegardes gardées (>= 1 ; 7 par défaut)."""
    valeur = _lire_parametre(session, CLE_CONSERVEES)
    try:
        n = int(valeur) if valeur is not None else settings.backup_conservees
    except ValueError:
        n = settings.backup_conservees
    return max(1, n)


def avertissements_dossier(dossier: Path) -> list[str]:
    """Signale une sauvegarde posée à côté de la clé maître (jamais copiée, mais voisine)."""
    try:
        cle = settings.master_key_path.resolve()
        racine = dossier.resolve()
    except OSError:
        return []
    if racine == cle.parent or racine in cle.parents:
        return [
            "Le dossier de sauvegarde contient la clé maître : elle n'est pas copiée, "
            "mais un dossier partagé exposerait aussi les credentials chiffrés. "
            "Choisissez un dossier distinct de la clé."
        ]
    return []


def sauvegarder_base(
    dossier: Path, *, conservees: int, source: Path | None = None,
    maintenant: datetime | None = None,
) -> ResultatSauvegarde:
    """Sauvegarde la BDD dans `dossier/hermes-AAAAMMJJ.db` puis applique la rotation.

    Écriture dans un fichier temporaire puis `os.replace` : une sauvegarde
    interrompue ne remplace jamais la précédente. Relance le même jour = écrase.
    """
    source = source or settings.db_path
    maintenant = maintenant or datetime.now(UTC)
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f"hermes-{maintenant:%Y%m%d}.db"
    temporaire = dossier / f".{cible.name}.tmp"
    temporaire.unlink(missing_ok=True)

    src = sqlite3.connect(Path(source), timeout=30)
    try:
        dst = sqlite3.connect(temporaire)
        try:
            src.backup(dst)
            controle = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if controle != "ok":
                raise RuntimeError(f"Sauvegarde MNEMOSYNE corrompue : {controle}")
        finally:
            dst.close()
    except BaseException:
        temporaire.unlink(missing_ok=True)
        raise
    finally:
        src.close()
    os.replace(temporaire, cible)

    supprimees = appliquer_rotation(dossier, conservees)
    logger.info("MNEMOSYNE : sauvegarde {} ({} supprimée(s))", cible.name, len(supprimees))
    return ResultatSauvegarde(
        chemin=cible,
        taille_octets=cible.stat().st_size,
        supprimees=supprimees,
        avertissements=avertissements_dossier(dossier),
    )


def lister_sauvegardes(dossier: Path) -> list[Path]:
    """Sauvegardes `hermes-AAAAMMJJ.db` du dossier, de la plus récente à la plus ancienne."""
    if not dossier.is_dir():
        return []
    return sorted((p for p in dossier.iterdir() if _MOTIF.match(p.name)), reverse=True)


def appliquer_rotation(dossier: Path, conservees: int) -> list[str]:
    """Garde les `conservees` plus récentes (par date du nom), supprime le reste."""
    supprimees: list[str] = []
    for ancien in lister_sauvegardes(dossier)[max(1, conservees):]:
        ancien.unlink(missing_ok=True)
        supprimees.append(ancien.name)
    return supprimees

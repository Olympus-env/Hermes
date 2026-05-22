"""État d'onboarding applicatif — verrou de premier lancement.

ARGOS ne doit pas collecter tant que l'utilisateur n'a pas validé ses filtres
métier dans le wizard d'onboarding (issue #3) : sinon la première collecte se
fait sans filtre (tout passe) et MNEMOSYNE se remplit d'AO hors périmètre.

L'état est persisté dans `parametres` sous la clé `app.onboarding.termine`,
même pattern que `argos.filtre` / `orchestration.config`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session

from hermes.db.models import Parametre

CLE_PARAMETRE = "app.onboarding.termine"


def est_termine(session: Session) -> bool:
    """Vrai si l'onboarding a été finalisé au moins une fois."""
    entree = session.get(Parametre, CLE_PARAMETRE)
    return bool(entree and entree.valeur == "true")


def marquer_termine(session: Session) -> None:
    """Marque l'onboarding comme terminé (idempotent)."""
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None:
        entree = Parametre(
            cle=CLE_PARAMETRE,
            valeur="true",
            description="Onboarding finalisé — déverrouille les collectes ARGOS",
        )
    else:
        entree.valeur = "true"
        entree.maj_le = datetime.now(UTC)
    session.add(entree)
    session.commit()

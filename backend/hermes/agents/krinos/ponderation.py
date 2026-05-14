"""Pondération du scoring KRINOS — chaque dimension a un poids ajusté par l'utilisateur.

La pondération est stockée dans la table `parametres` (clé/valeur JSON sous
la clé `krinos.ponderation_scoring`). Les poids sont des entiers 0-100, la
somme attendue est 100 mais on tolère un total différent (re-normalisation
côté `calculer_score_final`).

Dimensions par défaut (héritées du mockup historique, validées avec l'utilisateur) :

    affinite_metier  : 30 %  Correspondance avec l'activité / le savoir-faire
    references       : 20 %  Possibilité d'appuyer sur des réf. passées
    adequation_budget: 20 %  Budget marché vs capacité de l'entreprise
    capacite_equipe  : 15 %  Taille équipe requise vs disponible
    calendrier       : 15 %  Réalisme des délais

L'analyseur KRINOS demande à PYTHIA un score 0-100 par dimension ; le
backend calcule ensuite le score final en somme pondérée puis re-normalise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from sqlmodel import Session

from hermes.db.models import Parametre

CLE_PARAMETRE = "krinos.ponderation_scoring"


@dataclass(frozen=True)
class Ponderation:
    """Poids 0-100 par dimension de scoring."""

    affinite_metier: int = 30
    references: int = 20
    adequation_budget: int = 20
    capacite_equipe: int = 15
    calendrier: int = 15

    DIMENSIONS: ClassVar[tuple[str, ...]] = (
        "affinite_metier",
        "references",
        "adequation_budget",
        "capacite_equipe",
        "calendrier",
    )

    LIBELLES: ClassVar[dict[str, str]] = {
        "affinite_metier": "Affinité métier",
        "references": "Références",
        "adequation_budget": "Adéquation budget",
        "capacite_equipe": "Capacité équipe",
        "calendrier": "Risque calendrier",
    }

    def en_dict(self) -> dict[str, int]:
        return {d: getattr(self, d) for d in self.DIMENSIONS}

    @property
    def total(self) -> int:
        return sum(self.en_dict().values())

    def normalise(self) -> "Ponderation":
        """Re-normalise les poids pour que la somme soit 100."""
        total = self.total
        if total == 100 or total == 0:
            return self
        facteur = 100 / total
        return Ponderation(
            **{d: max(0, round(getattr(self, d) * facteur)) for d in self.DIMENSIONS}
        )


@dataclass
class _Etat:
    """Wrapper mutable pour tester l'idempotence (peu utilisé hors tests)."""

    valeurs: dict[str, int] = field(default_factory=dict)


def charger_ponderation(session: Session) -> Ponderation:
    """Charge la pondération depuis MNEMOSYNE. Retourne les valeurs par défaut si absente."""
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None or not entree.valeur:
        return Ponderation()
    try:
        data = json.loads(entree.valeur)
    except json.JSONDecodeError:
        return Ponderation()
    if not isinstance(data, dict):
        return Ponderation()
    args: dict[str, int] = {}
    for d in Ponderation.DIMENSIONS:
        valeur = data.get(d)
        try:
            args[d] = max(0, min(100, int(valeur))) if valeur is not None else getattr(Ponderation(), d)
        except (TypeError, ValueError):
            args[d] = getattr(Ponderation(), d)
    return Ponderation(**args)


def enregistrer_ponderation(session: Session, ponderation: Ponderation) -> Ponderation:
    """Persiste la pondération (sans la normaliser — on laisse l'utilisateur fixer)."""
    payload = json.dumps(ponderation.en_dict(), ensure_ascii=False)
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None:
        entree = Parametre(
            cle=CLE_PARAMETRE,
            valeur=payload,
            description="Pondération KRINOS — poids par dimension de scoring (JSON)",
        )
    else:
        entree.valeur = payload
        entree.maj_le = datetime.now(UTC)
    session.add(entree)
    session.commit()
    return ponderation


def calculer_score_final(
    scores_dimensions: dict[str, float],
    ponderation: Ponderation,
) -> float:
    """Somme pondérée des scores 0-100 par dimension, normalisée pour rester en 0-100.

    Si une dimension manque dans `scores_dimensions`, on l'ignore (et on ajuste
    la somme des poids effective). Si toutes les dimensions manquent, retourne 0.
    """
    poids = ponderation.en_dict()
    somme_pond_effective = 0
    somme = 0.0
    for d in Ponderation.DIMENSIONS:
        s = scores_dimensions.get(d)
        if s is None:
            continue
        try:
            valeur = float(s)
        except (TypeError, ValueError):
            continue
        valeur = max(0.0, min(100.0, valeur))
        somme += valeur * poids[d]
        somme_pond_effective += poids[d]

    if somme_pond_effective == 0:
        return 0.0
    return round(somme / somme_pond_effective, 1)

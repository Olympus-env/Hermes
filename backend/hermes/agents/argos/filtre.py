"""Filtrage des AO collectés par ARGOS selon des mots-clés utilisateur.

Le filtre est stocké dans la table `parametres` (clé/valeur), sous la clé
`argos.filtre.mots_cles` au format JSON :

    {"inclus": ["maintenance", "java"], "exclus": ["nettoyage"]}

Règles :
- Comparaison insensible à la casse et aux accents.
- Match si **au moins un** mot-clé inclus apparaît dans le titre, l'objet ou
  l'émetteur de l'AO. Si la liste `inclus` est vide → tout AO matche (filtre
  désactivé côté inclusion).
- Rejet immédiat si **au moins un** mot-clé exclus apparaît dans ces champs.
- Le filtre s'applique **avant insertion** : un AO rejeté ne touche jamais
  MNEMOSYNE.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import Session

from hermes.agents.argos.base import AOCollecte
from hermes.db.models import Parametre

CLE_PARAMETRE = "argos.filtre.mots_cles"


@dataclass(frozen=True)
class FiltreVeille:
    """Critères mots-clés appliqués aux collectes ARGOS."""

    inclus: tuple[str, ...] = field(default_factory=tuple)
    exclus: tuple[str, ...] = field(default_factory=tuple)

    @property
    def actif(self) -> bool:
        return bool(self.inclus) or bool(self.exclus)

    def correspond(self, item: AOCollecte) -> bool:
        """Retourne True si l'AO doit être conservé."""
        cible = _normaliser(" ".join(filter(None, [item.titre, item.objet, item.emetteur])))
        if not cible:
            # Pas de texte exploitable : on garde si pas d'inclusion exigée.
            return not self.inclus

        for mot in self.exclus:
            if _normaliser(mot) and _normaliser(mot) in cible:
                return False

        if not self.inclus:
            return True
        for mot in self.inclus:
            terme = _normaliser(mot)
            if terme and terme in cible:
                return True
        return False


def charger_filtre(session: Session) -> FiltreVeille:
    """Charge le filtre depuis MNEMOSYNE. Retourne un filtre vide si absent."""
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None or not entree.valeur:
        return FiltreVeille()
    try:
        data = json.loads(entree.valeur)
    except json.JSONDecodeError:
        return FiltreVeille()
    return _filtre_depuis_dict(data)


def enregistrer_filtre(session: Session, filtre: FiltreVeille) -> FiltreVeille:
    """Persiste le filtre (création ou mise à jour). Normalise les listes."""
    nettoye = _filtre_normalise(filtre)
    payload = json.dumps(
        {"inclus": list(nettoye.inclus), "exclus": list(nettoye.exclus)},
        ensure_ascii=False,
    )
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None:
        entree = Parametre(
            cle=CLE_PARAMETRE,
            valeur=payload,
            description="Filtre ARGOS — mots-clés inclus/exclus (JSON)",
        )
    else:
        entree.valeur = payload
        entree.maj_le = datetime.now(UTC)
    session.add(entree)
    session.commit()
    return nettoye


def _filtre_depuis_dict(data: object) -> FiltreVeille:
    if not isinstance(data, dict):
        return FiltreVeille()
    inclus = _liste_chaines(data.get("inclus"))
    exclus = _liste_chaines(data.get("exclus"))
    return _filtre_normalise(FiltreVeille(inclus=inclus, exclus=exclus))


def _filtre_normalise(filtre: FiltreVeille) -> FiltreVeille:
    return FiltreVeille(
        inclus=_dedoublonner(filtre.inclus),
        exclus=_dedoublonner(filtre.exclus),
    )


def _liste_chaines(valeur: object) -> tuple[str, ...]:
    if not isinstance(valeur, list):
        return ()
    return tuple(str(v).strip() for v in valeur if str(v).strip())


def _dedoublonner(valeurs: tuple[str, ...]) -> tuple[str, ...]:
    vues: set[str] = set()
    propres: list[str] = []
    for v in valeurs:
        cle = _normaliser(v)
        if not cle or cle in vues:
            continue
        vues.add(cle)
        propres.append(v.strip())
    return tuple(propres)


def _normaliser(texte: str | None) -> str:
    if not texte:
        return ""
    decomp = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in decomp if not unicodedata.combining(c))
    return sans_accents.casefold().strip()

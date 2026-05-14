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

Bonus : suggestion de mots-clés via PYTHIA (`suggerer_mots_cles`) pour
proposer une première liste pertinente à partir du profil de l'entreprise.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import Session

from hermes.agents import pythia
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


# --------------------------------------------------------------------------- #
# Suggestion de mots-clés via PYTHIA
# --------------------------------------------------------------------------- #


SYSTEM_PROMPT_SUGGESTION = (
    "Tu es un expert français de la veille sur les appels d'offre publics. "
    "À partir du profil d'une entreprise, tu proposes les mots-clés les plus "
    "pertinents pour filtrer un flux d'AO BOAMP. Les mots-clés doivent être "
    "courts (1-3 mots), spécifiques au métier, en français, sans doublons. "
    "Tu produis EXCLUSIVEMENT un objet JSON valide."
)


@dataclass(frozen=True)
class SuggestionMotsCles:
    inclus: tuple[str, ...]
    exclus: tuple[str, ...]
    raisonnement: str


async def suggerer_mots_cles(
    *,
    entreprise: str,
    activite: str,
    infos: str = "",
    nb_inclus: tuple[int, int] = (8, 15),
    nb_exclus: tuple[int, int] = (3, 6),
) -> SuggestionMotsCles:
    """Demande à PYTHIA une liste de mots-clés inclus/exclus.

    Retourne un objet normalisé (déduplication, trimming) prêt à passer à
    `enregistrer_filtre`. Lève `pythia.ErreurPythia` si PYTHIA est down ou
    si la sortie est inexploitable.
    """
    if not (entreprise.strip() or activite.strip()):
        raise pythia.ErreurPythia(
            "Profil entreprise vide — impossible de suggérer des mots-clés."
        )

    prompt = (
        f"Profil de l'entreprise :\n"
        f"  Nom        : {entreprise.strip() or '(non renseigné)'}\n"
        f"  Activité   : {activite.strip() or '(non renseigné)'}\n"
        f"  Détails    : {infos.strip() or '(aucun)'}\n"
        "\n"
        f"Propose entre {nb_inclus[0]} et {nb_inclus[1]} mots-clés INCLUS "
        f"(à matcher dans le titre/objet/émetteur des AO BOAMP) et entre "
        f"{nb_exclus[0]} et {nb_exclus[1]} mots-clés EXCLUS (pour écarter "
        "automatiquement les marchés hors périmètre).\n"
        "\n"
        "Réponds en JSON strict, sans texte autour :\n"
        '  {"inclus": ["...", "..."], "exclus": ["...", "..."], '
        '"raisonnement": "1-2 phrases expliquant ton choix"}\n'
        "\n"
        "Conseils :\n"
        "  - Les 'inclus' doivent être des termes métier précis (ex : "
        "'maintenance applicative', 'audit cyber', 'AMO'), pas génériques.\n"
        "  - Les 'exclus' couvrent les marchés évidemment hors périmètre "
        "(ex : pour une ESN logicielle : 'nettoyage', 'espaces verts', "
        "'climatisation').\n"
        "  - Pas d'acronymes ambigus seuls (ex : 'SI' → utiliser 'système "
        "information' ou 'SI métier').\n"
    )

    reponse = await pythia.generer(
        prompt, system=SYSTEM_PROMPT_SUGGESTION, format_json=True
    )
    payload = pythia.parser_json_sortie(reponse.texte)
    if not isinstance(payload, dict):
        raise pythia.ErreurPythia("Réponse PYTHIA n'est pas un objet JSON")

    inclus = _normaliser_liste(payload.get("inclus"))
    exclus = _normaliser_liste(payload.get("exclus"))
    if not inclus:
        raise pythia.ErreurPythia(
            "PYTHIA n'a renvoyé aucun mot-clé 'inclus' exploitable."
        )

    raisonnement = str(payload.get("raisonnement") or "").strip()
    return SuggestionMotsCles(
        inclus=inclus,
        exclus=exclus,
        raisonnement=raisonnement,
    )


def _normaliser_liste(valeur: object) -> tuple[str, ...]:
    if not isinstance(valeur, list):
        return ()
    propres: list[str] = []
    vues: set[str] = set()
    for v in valeur:
        if not isinstance(v, (str, int, float)):
            continue
        terme = str(v).strip().strip(",.;:!?\"'")
        cle = _normaliser(terme)
        if not cle or cle in vues or len(terme) > 80:
            continue
        vues.add(cle)
        propres.append(terme)
    return tuple(propres)

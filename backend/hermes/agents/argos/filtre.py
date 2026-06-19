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
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import Session, select

from hermes.agents import pythia
from hermes.agents.argos.base import (
    NATURES_CANONIQUES,
    AOCollecte,
    CriteresAvances,
    parse_iso_date,
)
from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    LogAgent,
    NiveauLog,
    Parametre,
    StatutAO,
)

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
        """Retourne True si l'AO collecté doit être conservé."""
        return self.correspond_champs(item.titre, item.objet, item.emetteur)

    def correspond_champs(
        self,
        titre: str | None,
        objet: str | None = None,
        emetteur: str | None = None,
    ) -> bool:
        """Cœur du filtrage, applicable à un AO collecté comme persisté."""
        cible = _normaliser(" ".join(filter(None, [titre, objet, emetteur])))
        if not cible:
            # Pas de texte exploitable : on garde si pas d'inclusion exigée.
            return not self.inclus

        for mot in self.exclus:
            if _contient(cible, _normaliser(mot)):
                return False

        if not self.inclus:
            return True
        for mot in self.inclus:
            if _contient(cible, _normaliser(mot)):
                return True
        return False


def _lire_brut(session: Session) -> dict:
    """Lit le paramètre JSON brut (mots-clés + avancé). {} si absent/corrompu."""
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None or not entree.valeur:
        return {}
    try:
        data = json.loads(entree.valeur)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _ecrire_brut(session: Session, data: dict) -> None:
    """Écrit le paramètre JSON brut (création ou mise à jour)."""
    payload = json.dumps(data, ensure_ascii=False)
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None:
        entree = Parametre(
            cle=CLE_PARAMETRE,
            valeur=payload,
            description="Filtre ARGOS — mots-clés + critères avancés (JSON)",
        )
    else:
        entree.valeur = payload
        entree.maj_le = datetime.now(UTC)
    session.add(entree)
    session.commit()


def charger_filtre(session: Session) -> FiltreVeille:
    """Charge le filtre mots-clés depuis MNEMOSYNE. Filtre vide si absent."""
    return _filtre_depuis_dict(_lire_brut(session))


def enregistrer_filtre(session: Session, filtre: FiltreVeille) -> FiltreVeille:
    """Persiste le filtre mots-clés. Préserve les critères avancés existants."""
    nettoye = _filtre_normalise(filtre)
    data = _lire_brut(session)
    data["inclus"] = list(nettoye.inclus)
    data["exclus"] = list(nettoye.exclus)
    _ecrire_brut(session, data)
    return nettoye


def charger_criteres(session: Session) -> CriteresAvances:
    """Charge les critères avancés (sous-objet ``avance``). Vide si absent."""
    return _criteres_depuis_dict(_lire_brut(session).get("avance"))


def enregistrer_criteres(
    session: Session, criteres: CriteresAvances
) -> CriteresAvances:
    """Persiste les critères avancés. Préserve les mots-clés existants."""
    nettoye = _criteres_normalise(criteres)
    data = _lire_brut(session)
    data["avance"] = _criteres_en_dict(nettoye)
    _ecrire_brut(session, data)
    return nettoye


@dataclass(frozen=True)
class ResultatRefiltrage:
    """Bilan d'un re-filtrage des AO déjà présents en base."""

    conserves: int = 0
    exclus: int = 0
    reintegres: int = 0

    def en_dict(self) -> dict[str, int]:
        return {
            "conserves": self.conserves,
            "exclus": self.exclus,
            "reintegres": self.reintegres,
        }


# Statuts « précoces » re-filtrables : l'AO n'a pas encore fait l'objet d'une
# décision humaine (à répondre / rejeté) ni d'une rédaction. On ne touche
# jamais aux statuts engagés pour ne pas défaire un choix de l'utilisateur.
_STATUTS_REFILTRABLES = (StatutAO.BRUT, StatutAO.ANALYSE)


def refiltrer_existants(session: Session, filtre: FiltreVeille) -> ResultatRefiltrage:
    """Réapplique le filtre métier courant aux AO déjà présents (issue #6).

    - AO précoces (BRUT/ANALYSE) ne correspondant plus → `HORS_FILTRE`.
    - AO `HORS_FILTRE` correspondant de nouveau → réintégrés (ANALYSE s'il
      existe une analyse, sinon BRUT) pour repasser dans le pipeline.
    - Filtre inactif (aucun mot-clé) → tous les `HORS_FILTRE` sont réintégrés.

    Les statuts engagés (A_REPONDRE, EN_REDACTION, REPONDU, REJETE, EXPIRE)
    sont laissés intacts.
    """
    conserves = exclus = reintegres = 0

    precoces = session.exec(
        select(AppelOffre).where(AppelOffre.statut.in_(_STATUTS_REFILTRABLES))
    ).all()
    for ao in precoces:
        if filtre.actif and not filtre.correspond_champs(ao.titre, ao.objet, ao.emetteur):
            ao.statut = StatutAO.HORS_FILTRE
            ao.maj_le = datetime.now(UTC)
            session.add(ao)
            exclus += 1
        else:
            conserves += 1

    hors_filtre = session.exec(
        select(AppelOffre).where(AppelOffre.statut == StatutAO.HORS_FILTRE)
    ).all()
    for ao in hors_filtre:
        if filtre.actif and not filtre.correspond_champs(ao.titre, ao.objet, ao.emetteur):
            continue
        a_analyse = session.exec(
            select(AnalyseKrinos.id).where(AnalyseKrinos.appel_offre_id == ao.id)
        ).first()
        ao.statut = StatutAO.ANALYSE if a_analyse is not None else StatutAO.BRUT
        ao.maj_le = datetime.now(UTC)
        session.add(ao)
        reintegres += 1

    if exclus or reintegres:
        session.add(
            LogAgent(
                agent="ARGOS",
                niveau=NiveauLog.INFO,
                message=(
                    f"Re-filtrage des AO existants : {conserves} conservés, "
                    f"{exclus} exclus (hors filtre), {reintegres} réintégrés"
                ),
            )
        )
    session.commit()
    return ResultatRefiltrage(conserves=conserves, exclus=exclus, reintegres=reintegres)


def _filtre_depuis_dict(data: object) -> FiltreVeille:
    if not isinstance(data, dict):
        return FiltreVeille()
    inclus = _liste_chaines(data.get("inclus"))
    exclus = _liste_chaines(data.get("exclus"))
    return _filtre_normalise(FiltreVeille(inclus=inclus, exclus=exclus))


def _criteres_depuis_dict(data: object) -> CriteresAvances:
    if not isinstance(data, dict):
        return CriteresAvances()
    return _criteres_normalise(
        CriteresAvances(
            cpv=_liste_chaines(data.get("cpv")),
            descripteurs=_liste_chaines(data.get("descripteurs")),
            natures=_liste_chaines(data.get("natures")),
            pays=_liste_chaines(data.get("pays")),
            departements=_liste_chaines(data.get("departements")),
            date_publication_depuis=_str_ou_none(data.get("date_publication_depuis")),
            deadline_min=_str_ou_none(data.get("deadline_min")),
            deadline_max=_str_ou_none(data.get("deadline_max")),
        )
    )


def _criteres_en_dict(criteres: CriteresAvances) -> dict:
    return {
        "cpv": list(criteres.cpv),
        "descripteurs": list(criteres.descripteurs),
        "natures": list(criteres.natures),
        "pays": list(criteres.pays),
        "departements": list(criteres.departements),
        "date_publication_depuis": criteres.date_publication_depuis,
        "deadline_min": criteres.deadline_min,
        "deadline_max": criteres.deadline_max,
    }


def _criteres_normalise(criteres: CriteresAvances) -> CriteresAvances:
    """Nettoie les listes (dédoublonnage) et valide les dates ISO.

    - `cpv` : chiffres uniquement (codes 8 positions) ; valeurs non numériques
      écartées (sécurité query eForms `IN`).
    - `natures` : restreintes aux valeurs canoniques connues.
    - `pays` : codes ISO3 en majuscules ; `departements` : chaînes brutes.
    - dates : conservées seulement si ISO `YYYY-MM-DD` valide.
    """
    cpv = _dedoublonner_simple(c.strip() for c in criteres.cpv if c.strip().isdigit())
    natures = _dedoublonner_simple(
        n.strip().lower()
        for n in criteres.natures
        if n.strip().lower() in NATURES_CANONIQUES
    )
    pays = _dedoublonner_simple(p.strip().upper() for p in criteres.pays if p.strip())
    return CriteresAvances(
        cpv=cpv,
        descripteurs=_dedoublonner(criteres.descripteurs),
        natures=natures,
        pays=pays,
        departements=_dedoublonner_simple(
            d.strip() for d in criteres.departements if d.strip()
        ),
        date_publication_depuis=_date_valide(criteres.date_publication_depuis),
        deadline_min=_date_valide(criteres.deadline_min),
        deadline_max=_date_valide(criteres.deadline_max),
    )


def _date_valide(valeur: str | None) -> str | None:
    d = parse_iso_date(valeur)
    return d.isoformat() if d else None


def _str_ou_none(valeur: object) -> str | None:
    if valeur is None:
        return None
    s = str(valeur).strip()
    return s or None


def _dedoublonner_simple(valeurs) -> tuple[str, ...]:
    """Dédoublonne en préservant l'ordre, sans normalisation accent/casse."""
    vues: set[str] = set()
    propres: list[str] = []
    for v in valeurs:
        if not v or v in vues:
            continue
        vues.add(v)
        propres.append(v)
    return tuple(propres)


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


def _est_acronyme_court(terme: str) -> bool:
    """Terme mono-token court (≤ 4 caractères alphanumériques).

    Ces termes — typiquement des acronymes (SMS, RCS) — sont matchés en **mot
    entier** pour éviter les faux positifs : en sous-chaîne nue, `RCS` matche
    les mentions légales (« Registre du Commerce et des Sociétés ») et `SMS`
    matcherait à l'intérieur d'autres mots.
    """
    return len(terme) <= 4 and terme.isalnum()


def _contient(cible: str, terme: str) -> bool:
    """Présence d'un terme (déjà normalisé) dans une cible (déjà normalisée).

    Sous-chaîne pour les expressions métier (souple, ex. « maintenance
    applicative ») ; mot entier pour les acronymes courts (strict, anti faux
    positifs SMS/RCS). Voir [[project_hermes_scraping_todo]].
    """
    if not terme:
        return False
    if _est_acronyme_court(terme):
        return re.search(rf"\b{re.escape(terme)}\b", cible) is not None
    return terme in cible


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

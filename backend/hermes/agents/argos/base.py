"""Contrat commun à tous les scrapers ARGOS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# Pagination des collectes (incrémental réalisé côté client).
TAILLE_PAGE = 100  # plafond par requête des deux APIs (BOAMP, TED)
MAX_PAGES = 10  # garde-fou : au plus 1000 avis par cycle et par portail
# Recouvrement de sécurité : on pagine un peu au-delà de la dernière collecte
# pour absorber l'imprécision des dates (jour) et un éventuel cycle raté.
MARGE_INCREMENTALE = timedelta(days=2)


def borne_incrementale(depuis: datetime | None) -> datetime | None:
    """Date en-deçà de laquelle il est inutile de paginer plus loin.

    `None` (première collecte) → pas de borne : rattrapage jusqu'au plafond de
    pages. Sinon `depuis - MARGE_INCREMENTALE` : les résultats étant triés par
    date décroissante, on arrête la pagination dès qu'une page est entièrement
    antérieure à cette borne.
    """
    if depuis is None:
        return None
    return depuis - MARGE_INCREMENTALE


@dataclass
class AOCollecte:
    """Représentation brute d'un AO récupéré par un scraper.

    Indépendant des modèles SQLModel pour rester testable hors BDD.
    Le runner se charge de la conversion vers `AppelOffre`.
    """

    titre: str
    url_source: str

    reference_externe: str | None = None
    emetteur: str | None = None
    objet: str | None = None

    budget_estime: float | None = None
    devise: str = "EUR"

    date_publication: datetime | None = None
    date_limite: datetime | None = None

    type_marche: str | None = None
    zone_geographique: str | None = None
    code_naf: str | None = None

    def cle_unicite(self) -> str:
        """Clé utilisée pour dédoublonner.

        Priorité : référence externe officielle > url_source.
        """
        return self.reference_externe or self.url_source


# --------------------------------------------------------------------------- #
# Critères de filtrage avancé (contrat partagé scrapers ↔ runner ↔ persistance)
# --------------------------------------------------------------------------- #

# Natures de marché canoniques (français) → représentation par portail.
# Mapping validé en live (2026-06-19) : BOAMP `type_marche`, TED `contract-nature`.
NATURES_CANONIQUES: tuple[str, ...] = ("services", "travaux", "fournitures")
_NATURE_BOAMP = {"services": "SERVICES", "travaux": "TRAVAUX", "fournitures": "FOURNITURES"}
_NATURE_TED = {"services": "services", "travaux": "works", "fournitures": "supplies"}


def parse_iso_date(valeur: str | None) -> date | None:
    """Parse une date ISO ``YYYY-MM-DD`` ; None si vide ou invalide."""
    if not valeur:
        return None
    try:
        return date.fromisoformat(str(valeur).strip()[:10])
    except (ValueError, TypeError):
        return None


def _date_only(valeur: datetime | None) -> date | None:
    return valeur.date() if isinstance(valeur, datetime) else None


@dataclass(frozen=True)
class CriteresAvances:
    """Filtres avancés poussés côté serveur (best-effort) puis re-vérifiés.

    Tous optionnels, persistés avec le filtre mots-clés (sous-objet ``avance``).
    Les dates sont en ISO ``YYYY-MM-DD`` et converties au format de chaque
    portail par les query builders (TED ``YYYYMMDD``, BOAMP ``date'…'``).

    Répartition par portail :
    - ``cpv`` → TED (``classification-cpv IN``) ; non exposé par BOAMP.
    - ``descripteurs`` → BOAMP (``search(descripteur_libelle, …)``).
    - ``natures`` → les deux (canonique mappé via NATURES_CANONIQUES).
    - ``pays`` → TED (``place-of-performance IN``, ISO3) ; défaut FRA.
    - ``departements`` → BOAMP (``code_departement``).
    - dates → les deux portails.
    """

    cpv: tuple[str, ...] = field(default_factory=tuple)
    descripteurs: tuple[str, ...] = field(default_factory=tuple)
    natures: tuple[str, ...] = field(default_factory=tuple)
    pays: tuple[str, ...] = field(default_factory=tuple)
    departements: tuple[str, ...] = field(default_factory=tuple)
    date_publication_depuis: str | None = None
    deadline_min: str | None = None
    deadline_max: str | None = None

    @property
    def actif(self) -> bool:
        return bool(
            self.cpv
            or self.descripteurs
            or self.natures
            or self.pays
            or self.departements
            or self.date_publication_depuis
            or self.deadline_min
            or self.deadline_max
        )

    def natures_pour(self, portail: str) -> tuple[str, ...]:
        """Traduit les natures canoniques dans le vocabulaire d'un portail."""
        table = _NATURE_BOAMP if portail == "boamp" else _NATURE_TED
        return tuple(table[n] for n in self.natures if n in table)

    def correspond_client(self, item: AOCollecte) -> bool:
        """Garde-fou client sur les dates (best-effort, jamais sur zone/CPV).

        Le filtrage serveur reste autoritaire ; ce garde-fou rattrape les cas où
        la requête serveur a été rejetée (repli sur collecte non filtrée). On ne
        rejette **que** sur une date présente et clairement hors borne — un AO
        sans date n'est jamais écarté ici.
        """
        pub = _date_only(item.date_publication)
        depuis = parse_iso_date(self.date_publication_depuis)
        if depuis and pub and pub < depuis:
            return False

        fin = _date_only(item.date_limite)
        dmin = parse_iso_date(self.deadline_min)
        dmax = parse_iso_date(self.deadline_max)
        if dmin and fin and fin < dmin:
            return False
        if dmax and fin and fin > dmax:
            return False
        return True


@dataclass
class ResultatCollecte:
    """Bilan d'une exécution de collecte."""

    portail: str
    ao_trouves: int = 0
    ao_nouveaux: int = 0
    ao_dedoublonnes: int = 0
    ao_filtres: int = 0
    duree_ms: int = 0
    erreurs: list[str] = field(default_factory=list)
    items: list[AOCollecte] = field(default_factory=list)

    @property
    def succes(self) -> bool:
        return not self.erreurs


class Scraper(ABC):
    """Interface implémentée par chaque scraper de portail.

    Convention : un scraper *ne touche pas* à la BDD. Il renvoie une liste
    d'AOCollecte et le runner s'occupe de la persistance.
    """

    nom: str  # identifiant court ("boamp", "ted", …)
    url_base: str

    @abstractmethod
    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        """Renvoie au plus `limite` AO les plus récents du portail."""
        raise NotImplementedError

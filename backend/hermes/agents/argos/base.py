"""Contrat commun à tous les scrapers ARGOS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


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

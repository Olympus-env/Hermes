"""Registre des scrapers disponibles, indexés par nom court de portail."""

from __future__ import annotations

from hermes.agents.argos.base import Scraper
from hermes.agents.argos.boamp import BoampScraper

# Pour ajouter un portail : implémenter `Scraper` dans un nouveau fichier
# puis l'enregistrer ici. Aucun import dynamique → exigence sécurité (pas de
# chargement de code basé sur des données BDD).
_REGISTRE: dict[str, type[Scraper]] = {
    BoampScraper.nom: BoampScraper,
}


def scrapers_disponibles() -> list[str]:
    return sorted(_REGISTRE.keys())


def creer_scraper(nom: str) -> Scraper:
    if nom not in _REGISTRE:
        raise KeyError(
            f"Scraper inconnu : {nom!r}. Disponibles : {scrapers_disponibles()}"
        )
    return _REGISTRE[nom]()

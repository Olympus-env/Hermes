"""ARGOS — agent de collecte / scraping des portails AO.

Architecture :
- `base.py`      : interface `Scraper` que chaque portail implémente.
- `boamp.py`     : premier scraper (BOAMP — boamp.fr, portail public).
- `runner.py`    : exécution d'un scraper, persistance MNEMOSYNE, gestion logs.
- `scheduler.py` : APScheduler — planification automatique des collectes.

Le nom ARGOS renvoie à Argos Panoptès, le géant aux cent yeux de la mythologie
grecque. Surveille tout, ne dort jamais (ou presque — APScheduler gère).
"""

from hermes.agents.argos.base import (  # noqa: F401
    AOCollecte,
    ResultatCollecte,
    Scraper,
)
from hermes.agents.argos.runner import executer_collecte  # noqa: F401

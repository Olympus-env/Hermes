"""Robustesse réseau partagée des scrapers ARGOS : retry/backoff.

Mutualise la politique de tolérance aux pannes des scrapers HTTP (BOAMP, TED).
Un échec réseau ponctuel — 429 (quota), 5xx (panne serveur), timeout — ne doit
pas coûter un cycle de collecte entier : c'est critique quand la cadence est de
seulement 2 collectes/jour (cf. veille LinkMobility).

Politique appliquée :
- **Réessaie** sur 429, 5xx et erreurs réseau transitoires (timeout, transport).
- **Respecte `Retry-After`** (secondes entières ou date HTTP) quand le serveur
  le fournit, plafonné pour ne pas geler une collecte indéfiniment.
- Sinon **backoff exponentiel** plafonné, avec jitter pour éviter les rafales
  synchronisées.
- **N'insiste jamais** sur une erreur 4xx définitive (400, 401, 403, 404…) :
  rejouer une requête malformée ou refusée est inutile — la réponse est rendue
  telle quelle à l'appelant, qui décidera (`raise_for_status`, repli…).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from loguru import logger

# Codes HTTP transitoires justifiant une nouvelle tentative.
_STATUTS_RETRY = frozenset({429, 500, 502, 503, 504})

# Plafond de respect d'un `Retry-After` : au-delà, mieux vaut abandonner la
# tentative et laisser le cycle suivant retenter que bloquer la collecte.
_PLAFOND_RETRY_AFTER = 60.0


async def _attendre(delai: float) -> None:
    """Pause entre deux tentatives (indirection pour la testabilité)."""
    await asyncio.sleep(delai)


async def requeter_avec_retry(
    envoyer: Callable[[], Awaitable[httpx.Response]],
    *,
    max_tentatives: int = 3,
    base_delai: float = 1.0,
    delai_max: float = 30.0,
    nom: str = "requête",
) -> httpx.Response:
    """Exécute `envoyer()` avec retry/backoff sur erreurs transitoires.

    `envoyer` est une *factory* de coroutine qui réalise une requête HTTP et
    renvoie la `httpx.Response` **sans** `raise_for_status` (le helper a besoin
    d'inspecter le code de statut). Elle est rejouée intégralement à chaque
    tentative (un nouveau client est donc créé à chaque essai — le coût est
    négligeable à cette cadence).

    Renvoie la réponse dès qu'elle n'est plus transitoirement en échec (succès,
    ou erreur définitive 4xx laissée à l'appelant). Relève la dernière exception
    réseau si toutes les tentatives échouent.
    """
    for tentative in range(1, max_tentatives + 1):
        derniere = tentative == max_tentatives
        try:
            reponse = await envoyer()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if derniere:
                logger.warning(
                    f"ARGOS {nom} : échec réseau définitif après "
                    f"{max_tentatives} tentatives ({exc!r})"
                )
                raise
            delai = _delai_backoff(tentative, base_delai, delai_max)
            logger.warning(
                f"ARGOS {nom} : échec réseau ({exc!r}), nouvelle tentative "
                f"{tentative + 1}/{max_tentatives} dans {delai:.1f}s"
            )
            await _attendre(delai)
            continue

        if reponse.status_code in _STATUTS_RETRY and not derniere:
            delai = _delai_retry_after(reponse)
            if delai is None:
                delai = _delai_backoff(tentative, base_delai, delai_max)
            logger.warning(
                f"ARGOS {nom} : HTTP {reponse.status_code}, nouvelle tentative "
                f"{tentative + 1}/{max_tentatives} dans {delai:.1f}s"
            )
            await _attendre(delai)
            continue

        return reponse

    # Inatteignable : la boucle retourne ou relève toujours à la dernière
    # itération. Garde-fou explicite pour le typeur.
    raise RuntimeError(f"ARGOS {nom} : boucle de retry épuisée sans issue")


def _delai_backoff(tentative: int, base: float, plafond: float) -> float:
    """Backoff exponentiel plafonné avec jitter « equal jitter ».

    `base * 2^(tentative-1)`, borné par `plafond`, puis on garde la moitié fixe
    et on tire l'autre moitié au hasard : on évite à la fois les délais quasi
    nuls (full jitter) et les rafales parfaitement synchronisées.
    """
    expo = min(base * (2 ** (tentative - 1)), plafond)
    moitie = expo / 2
    return moitie + random.uniform(0.0, moitie)


def _delai_retry_after(reponse: httpx.Response) -> float | None:
    """Interprète l'en-tête `Retry-After` (secondes entières ou date HTTP)."""
    brut = reponse.headers.get("Retry-After")
    if not brut:
        return None
    brut = brut.strip()
    if brut.isdigit():
        return min(float(brut), _PLAFOND_RETRY_AFTER)
    try:
        cible = parsedate_to_datetime(brut)
    except (TypeError, ValueError):
        return None
    if cible is None:
        return None
    if cible.tzinfo is None:
        cible = cible.replace(tzinfo=UTC)
    delta = (cible - datetime.now(UTC)).total_seconds()
    return max(0.0, min(delta, _PLAFOND_RETRY_AFTER))

"""Scraper TED — Tenders Electronic Daily (Journal officiel S de l'UE).

Source : <https://ted.europa.eu> / API publique « Search API v3 ».

URL exploitée :
    POST https://api.ted.europa.eu/v3/notices/search

Caractéristiques :
- API REST publique, **gratuite**, **sans clé d'authentification**
  (confirmé par la doc TED Developer / Publications Office de l'UE).
- Corps JSON : ``query`` (langage expert eForms), ``fields``, ``limit``,
  ``scope``, ``paginationMode``. Réponse : ``{"notices": [...],
  "totalNoticeCount": N, "iterationNextToken": "..."}``.
- On cible les avis dont le lieu d'exécution est la France, triés par date
  de publication décroissante.

Note schéma : le détail exact des champs eForms n'est documenté que via
Swagger (interface JS non introspectable hors ligne). Le parseur est donc
**défensif** — il tolère, pour chaque donnée, plusieurs noms de champs et
trois formes multilingues (chaîne / liste / objet indexé par code langue),
en privilégiant le français. Même philosophie que le parseur BOAMP.

Filtrage serveur : les mots-clés métier inclus sont poussés via
``notice-title ~ "terme"`` (précis, validé en live ; ``FT~`` est trop large),
avec **repli** automatique sur la query « France seule » si l'API rejette la
requête filtrée. La date limite de réponse est extraite du champ
``deadline-receipt-tender-date-lot`` (le seul validé sans 400).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from hermes.agents.argos.base import (
    MAX_PAGES,
    TAILLE_PAGE,
    AOCollecte,
    Scraper,
    borne_incrementale,
)
from hermes.agents.argos.reseau import requeter_avec_retry

_UA = (
    "Mozilla/5.0 (compatible; HERMES/0.1; +https://github.com/local) "
    "FastAPI-httpx"
)

API_URL = "https://api.ted.europa.eu/v3/notices/search"

# Langues préférées pour résoudre un champ multilingue eForms.
_LANGUES_PREFEREES = ("fra", "fr", "FRA", "FR", "eng", "en", "ENG", "EN")

# Champs eForms demandés. `deadline-receipt-tender-date-lot` est le champ de
# date limite *validé en live* (le plus stable) : `deadline-receipt-tender`
# provoque des 400 selon le type d'avis. Il revient en liste (un élément par
# lot), parsé défensivement côté `_date_limite`.
_FIELDS = [
    "publication-number",
    "notice-title",
    "publication-date",
    "deadline-receipt-tender-date-lot",
    "buyer-name",
    "place-of-performance",
    "classification-cpv",
    "links",
]

# Tri appliqué à toutes les requêtes (fait partie de la query expert eForms).
_TRI = "SORT BY publication-date DESC"


class TedScraper(Scraper):
    """Scraper TED via la Search API v3 (publique, sans authentification)."""

    nom = "ted"
    url_base = "https://ted.europa.eu"

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        # Injectés par le runner avant collecte (même pattern que BOAMP). Les
        # mots-clés inclus sont poussés à l'API via `notice-title ~ "terme"`
        # (précis — validé en live, contrairement à `FT~` trop large). Les
        # exclus restent au filtre client (runner) : la négation eForms n'a pas
        # été validée, et le garde-fou client re-trie déjà sur le titre.
        self.filtre_inclus: tuple[str, ...] = ()
        self.filtre_exclus: tuple[str, ...] = ()
        # Date de la dernière collecte (injectée par le runner) : borne la
        # pagination incrémentale. None à la première collecte.
        self.depuis: datetime | None = None

    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        query = _construire_query(self.filtre_inclus)
        borne = borne_incrementale(self.depuis)
        try:
            notices = await self._collecter_pagine(query, borne)
        except httpx.HTTPError:
            # Sans filtre, un échec est une vraie panne : on laisse remonter au
            # runner pour journalisation. Avec filtre, on tente le repli.
            if not self.filtre_inclus:
                raise
            notices = None

        if notices is None:
            # Requête filtrée rejetée (query eForms invalide, champ…) : repli sûr
            # sur la query « France seule ». Le runner re-filtrera côté client.
            # Un échec ici lève → journalisé par le runner.
            notices = await self._collecter_pagine(_construire_query(()), borne)

        return [_notice_vers_ao(n) for n in notices if _est_valide(n)]

    async def _collecter_pagine(
        self, query: str, borne: datetime | None
    ) -> list[dict[str, Any]]:
        """Pagine via `page` jusqu'à la borne incrémentale ou au plafond.

        Propage les erreurs HTTP : `collecter` décide du repli selon le filtre.
        """
        cumul: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            lot = await self._requeter(query, TAILLE_PAGE, page)
            if not lot:
                break
            cumul.extend(lot)
            if len(lot) < TAILLE_PAGE:
                break  # dernière page disponible
            if borne is not None and _page_anterieure(lot, borne):
                break  # fenêtre incrémentale dépassée
        return cumul

    async def _requeter(
        self, query: str, limite: int, page: int = 1
    ) -> list[dict[str, Any]]:
        """Exécute une requête TED (avec retry/backoff). Lève sur échec HTTP."""
        payload = {
            "query": query,
            "fields": _FIELDS,
            "limit": min(max(1, limite), 100),
            "scope": "ACTIVE",
            "paginationMode": "PAGE_NUMBER",
            "page": page,
        }

        async def envoyer() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "User-Agent": _UA,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                follow_redirects=True,
            ) as client:
                return await client.post(API_URL, json=payload)

        r = await requeter_avec_retry(envoyer, nom="TED")
        r.raise_for_status()
        data = r.json()
        return data.get("notices") or data.get("results") or []


# --------------------------------------------------------------------------- #
# Construction de la query serveur (langage expert eForms)
# --------------------------------------------------------------------------- #


def _construire_query(inclus: tuple[str, ...]) -> str:
    """Construit la query eForms : France + mots-clés inclus sur le titre.

    Forme : ``(place-of-performance IN (FRA)) AND (notice-title ~ "kw1" OR …)``
    suivie du tri. Sans mot-clé inclus → query « France seule » (comportement
    historique).
    """
    base = "place-of-performance IN (FRA)"
    termes = [_echapper(k) for k in inclus if _echapper(k)]
    if termes:
        ors = " OR ".join(f'notice-title ~ "{t}"' for t in termes)
        base = f"({base}) AND ({ors})"
    return f"{base} {_TRI}"


def _echapper(terme: str | None) -> str:
    """Nettoie un mot-clé pour l'insérer entre guillemets dans une query eForms."""
    if not terme:
        return ""
    return terme.replace('"', "").strip()


# --------------------------------------------------------------------------- #
# Conversion notice eForms → AOCollecte
# --------------------------------------------------------------------------- #


def _est_valide(notice: dict[str, Any]) -> bool:
    """Filtre les notices inexploitables (ni titre ni acheteur)."""
    return bool(
        _texte_multi(notice.get("notice-title"))
        or _texte_multi(notice.get("buyer-name"))
    )


def _page_anterieure(notices: list[dict[str, Any]], borne: datetime) -> bool:
    """Vrai si la notice la plus ancienne de la page est antérieure à la borne.

    Résultats triés par `publication-date` décroissante : si la dernière est
    déjà avant la borne, les pages suivantes le sont aussi.
    """
    if not notices:
        return True
    d = _parse_date(notices[-1].get("publication-date"))
    return d is not None and d < borne


def _notice_vers_ao(notice: dict[str, Any]) -> AOCollecte:
    titre = _texte_multi(notice.get("notice-title")) or "Avis TED (sans titre)"
    if len(titre) > 500:
        titre = titre[:497] + "…"

    reference = _texte_simple(notice.get("publication-number"))
    url = _premier_lien(notice.get("links")) or _url_par_defaut(reference)
    emetteur = _texte_multi(notice.get("buyer-name"))

    return AOCollecte(
        titre=titre,
        url_source=url,
        reference_externe=reference,
        emetteur=emetteur,
        objet=(_texte_multi(notice.get("notice-title")) or "")[:1000] or None,
        date_publication=_parse_date(notice.get("publication-date")),
        date_limite=_date_limite(notice.get("deadline-receipt-tender-date-lot")),
        type_marche=_texte_multi(notice.get("notice-type")),
        zone_geographique=_zone(notice.get("place-of-performance")),
        code_naf=_premier(notice.get("classification-cpv")),
    )


def _texte_multi(
    value: Any, prefer: tuple[str, ...] = _LANGUES_PREFEREES
) -> str | None:
    """Résout un champ eForms en texte : str | list | dict indexé par langue."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for v in value:
            t = _texte_multi(v, prefer)
            if t:
                return t
        return None
    if isinstance(value, dict):
        for cle in prefer:
            if cle in value:
                t = _texte_multi(value[cle], prefer)
                if t:
                    return t
        for v in value.values():
            t = _texte_multi(v, prefer)
            if t:
                return t
    return None


def _texte_simple(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _premier(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])[:32]
    if value:
        return str(value)[:32]
    return None


def _zone(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        codes = [str(v).strip() for v in value if str(v).strip()]
        return ",".join(dict.fromkeys(codes)) or None
    s = str(value).strip()
    return s or None


def _premier_lien(links: Any) -> str | None:
    """Extrait une URL exploitable de l'objet `links` eForms.

    Forme attendue : ``{"html": {"FRA": "url", ...}, "pdf": {...}, ...}``.
    Priorité : HTML puis PDF, langue française puis anglaise puis n'importe.
    """
    if not isinstance(links, dict):
        return _texte_simple(links)
    for famille in ("html", "htmlDirect", "pdf", "pdfDirect", "xml"):
        bloc = links.get(famille)
        url = _texte_multi(bloc)
        if url and url.startswith("http"):
            return url
    # Dernier recours : n'importe quelle valeur ressemblant à une URL.
    url = _texte_multi(links)
    return url if url and url.startswith("http") else None


def _url_par_defaut(reference: str | None) -> str:
    if reference:
        return f"https://ted.europa.eu/en/notice/-/detail/{reference}"
    return "https://ted.europa.eu/"


def _parse_date(valeur: Any) -> datetime | None:
    if not valeur:
        return None
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=UTC)
    s = str(valeur).strip().replace("Z", "+00:00")
    for tentative in (s, s[:10]):  # gère "2026-05-12+02:00" et "2026-05-12"
        try:
            dt = datetime.fromisoformat(tentative)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue
    return None


def _date_limite(valeur: Any) -> datetime | None:
    """Extrait la date limite de réponse de `deadline-receipt-tender-date-lot`.

    Le champ revient en liste (un élément par lot), chaque valeur au format
    ``2026-06-30+02:00`` (parfois une simple date). On retient la **plus
    tardive** : un AO multi-lots reste ouvert tant qu'un lot accepte des
    offres — l'expiration automatique ne doit pas le masquer prématurément.
    Parsing défensif : toute valeur illisible est ignorée.
    """
    valeurs = valeur if isinstance(valeur, list) else [valeur]
    dates = [d for d in (_parse_date(v) for v in valeurs) if d is not None]
    return max(dates) if dates else None

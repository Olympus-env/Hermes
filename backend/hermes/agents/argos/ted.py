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

Conséquence : seuls les champs eForms les plus stables sont demandés. La
date limite de réponse (nom de champ eForms variable selon le type d'avis)
n'est pas demandée pour éviter un rejet 400 ; elle restera ``None`` côté
AO — le pipeline KRINOS/HERMION fonctionne sans (analyse sur métadonnées).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from hermes.agents.argos.base import AOCollecte, Scraper

_UA = (
    "Mozilla/5.0 (compatible; HERMES/0.1; +https://github.com/local) "
    "FastAPI-httpx"
)

API_URL = "https://api.ted.europa.eu/v3/notices/search"

# Langues préférées pour résoudre un champ multilingue eForms.
_LANGUES_PREFEREES = ("fra", "fr", "FRA", "FR", "eng", "en", "ENG", "EN")

# Champs eForms demandés (volontairement conservateur — voir docstring).
_FIELDS = [
    "publication-number",
    "notice-title",
    "publication-date",
    "buyer-name",
    "place-of-performance",
    "classification-cpv",
    "links",
]


class TedScraper(Scraper):
    """Scraper TED via la Search API v3 (publique, sans authentification)."""

    nom = "ted"
    url_base = "https://ted.europa.eu"

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        payload = {
            # Lieu d'exécution = France, plus récents d'abord.
            "query": (
                "place-of-performance IN (FRA) "
                "SORT BY publication-date DESC"
            ),
            "fields": _FIELDS,
            "limit": min(max(1, limite), 100),
            "scope": "ACTIVE",
            "paginationMode": "PAGE_NUMBER",
            "page": 1,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "User-Agent": _UA,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            follow_redirects=True,
        ) as client:
            r = await client.post(API_URL, json=payload)
            r.raise_for_status()
            data = r.json()

        notices = data.get("notices") or data.get("results") or []
        return [_notice_vers_ao(n) for n in notices if _est_valide(n)]


# --------------------------------------------------------------------------- #
# Conversion notice eForms → AOCollecte
# --------------------------------------------------------------------------- #


def _est_valide(notice: dict[str, Any]) -> bool:
    """Filtre les notices inexploitables (ni titre ni acheteur)."""
    return bool(
        _texte_multi(notice.get("notice-title"))
        or _texte_multi(notice.get("buyer-name"))
    )


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
        date_limite=None,  # cf. docstring : champ eForms non demandé
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

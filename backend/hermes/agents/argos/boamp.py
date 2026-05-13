"""Scraper BOAMP — Bulletin Officiel des Annonces de Marchés Publics.

Source : <https://www.boamp.fr> / API publique DILA hébergée par Opendatasoft.

URL exploitée :
    https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records

Caractéristiques :
- API REST publique, **gratuite**, **sans clé d'authentification**.
- Réponse JSON structurée (champs `objet`, `nomacheteur`, `datelimitereponse`,
  `url_avis`, etc.) — bien plus stable que du scraping HTML.
- ~1,6 million d'avis indexés au total ; on récupère les plus récents
  triés par `dateparution`.

C'est le canal légitime de consommation prévu par la DILA pour les éditeurs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from hermes.agents.argos.base import AOCollecte, Scraper


_UA = (
    "Mozilla/5.0 (compatible; HERMES/0.1; +https://github.com/local) "
    "FastAPI-httpx"
)

API_URL = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/"
    "catalog/datasets/boamp/records"
)


class BoampScraper(Scraper):
    """Scraper BOAMP via l'API Opendatasoft de la DILA."""

    nom = "boamp"
    url_base = "https://www.boamp.fr"

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        # L'API Opendatasoft plafonne à 100 records par requête.
        limite_api = min(limite, 100)
        params = {
            "limit": limite_api,
            "order_by": "dateparution desc",
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            r = await client.get(API_URL, params=params)
            r.raise_for_status()
            data = r.json()

        records = data.get("results", [])
        return [_record_vers_ao(rec) for rec in records if _est_valide(rec)]


# --------------------------------------------------------------------------- #
# Conversion record API → AOCollecte
# --------------------------------------------------------------------------- #


def _est_valide(rec: dict[str, Any]) -> bool:
    """Filtre les records inexploitables (sans titre ni objet)."""
    return bool(rec.get("objet") or rec.get("titre_marche") or rec.get("nomacheteur"))


def _record_vers_ao(rec: dict[str, Any]) -> AOCollecte:
    titre = (
        rec.get("objet")
        or rec.get("titre_marche")
        or rec.get("nomacheteur")
        or "Avis BOAMP (sans titre)"
    )
    titre = str(titre).strip()
    if len(titre) > 500:
        titre = titre[:497] + "…"

    url = rec.get("url_avis") or _url_par_defaut(rec)
    reference = rec.get("idweb") or rec.get("id") or rec.get("contractfolderid")

    emetteur = rec.get("nomacheteur")
    if emetteur:
        emetteur = str(emetteur).strip()

    zone = _format_zone(rec.get("code_departement"), rec.get("code_departement_prestation"))

    return AOCollecte(
        titre=titre,
        url_source=url,
        reference_externe=str(reference) if reference is not None else None,
        emetteur=emetteur,
        objet=str(rec.get("objet"))[:1000] if rec.get("objet") else None,
        date_publication=_parse_iso(rec.get("dateparution")),
        date_limite=_parse_iso(rec.get("datelimitereponse")),
        type_marche=rec.get("nature_libelle") or rec.get("type_marche"),
        zone_geographique=zone,
        code_naf=_premier_descripteur(rec.get("descripteur_code")),
    )


def _url_par_defaut(rec: dict[str, Any]) -> str:
    """Fallback si `url_avis` est absent : construit l'URL de détail BOAMP."""
    ref = rec.get("idweb") or rec.get("id") or rec.get("contractfolderid")
    if ref:
        return f"https://www.boamp.fr/avis/detail/{ref}"
    return "https://www.boamp.fr/"


def _parse_iso(valeur: Any) -> datetime | None:
    if not valeur:
        return None
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)
    try:
        s = str(valeur).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _format_zone(dpt: Any, dpt_prestation: Any) -> str | None:
    """Concatène code_departement / code_departement_prestation."""

    def _stringify(x: Any) -> str | None:
        if x is None:
            return None
        if isinstance(x, list):
            x = ",".join(str(i) for i in x if i is not None)
        s = str(x).strip()
        return s or None

    a = _stringify(dpt)
    b = _stringify(dpt_prestation)
    if a and b and a != b:
        return f"{a} / {b}"
    return a or b


def _premier_descripteur(code: Any) -> str | None:
    if isinstance(code, list) and code:
        return str(code[0])[:32]
    if code:
        return str(code)[:32]
    return None

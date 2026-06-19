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

from datetime import UTC, datetime
from typing import Any

import httpx

from hermes.agents.argos.base import (
    MAX_PAGES,
    TAILLE_PAGE,
    AOCollecte,
    CriteresAvances,
    Scraper,
    borne_incrementale,
)
from hermes.agents.argos.capabilities import CHAMPS_BOAMP, PROFIL_BOAMP
from hermes.agents.argos.reseau import requeter_avec_retry

_UA = (
    "Mozilla/5.0 (compatible; HERMES/0.1; +https://github.com/local) "
    "FastAPI-httpx"
)

API_URL = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/"
    "catalog/datasets/boamp/records"
)

# Liste `select` versionnée (champs validés en live) : réduit la taille des
# payloads quand la pagination monte en volume, sans rien retirer au parseur.
_SELECT = ",".join(CHAMPS_BOAMP)


class BoampScraper(Scraper):
    """Scraper BOAMP via l'API Opendatasoft de la DILA."""

    nom = "boamp"
    url_base = "https://www.boamp.fr"
    capacites = PROFIL_BOAMP

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        # Injectés par le runner avant collecte (même pattern que credentials) :
        # mots-clés métier poussés à l'API pour filtrer dans tout le corpus,
        # plutôt que de ne récupérer que les derniers avis (sinon une cible
        # étroite — ex. SMS/RCS — donne une veille quasi vide).
        self.filtre_inclus: tuple[str, ...] = ()
        self.filtre_exclus: tuple[str, ...] = ()
        # Critères avancés (CPV non géré côté BOAMP) injectés par le runner.
        self.criteres: CriteresAvances = CriteresAvances()
        # Date de la dernière collecte (injectée par le runner) : borne la
        # pagination incrémentale. None à la première collecte.
        self.depuis: datetime | None = None

    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        where = _construire_where(self.filtre_inclus, self.filtre_exclus, self.criteres)
        if where is None:
            # Sans filtre : derniers avis seulement (comportement historique ;
            # la veille ciblée passe toujours un filtre, donc pas de pagination).
            records = await self._requeter(min(limite, 100), 0, None)
            return _vers_aos(records or [])

        # Avec filtre serveur : les avis pertinents sont rares et dispersés —
        # on pagine jusqu'à la fenêtre incrémentale ou au plafond de pages.
        records = await self._collecter_pagine(where, borne_incrementale(self.depuis))
        if records is None:
            # Requête filtrée rejetée par l'API (ODSQL invalide, champ, etc.) :
            # repli sûr sur une collecte non filtrée — le runner re-filtrera
            # côté client. On ne perd jamais un cycle à cause du filtre.
            records = await self._requeter(min(limite, 100), 0, None) or []
        return _vers_aos(records)

    async def _collecter_pagine(
        self, where: str, borne: datetime | None
    ) -> list[dict[str, Any]] | None:
        """Pagine via `offset` jusqu'à la borne incrémentale ou au plafond.

        Renvoie None si la *première* page échoue (déclenche le repli) ; sinon
        renvoie ce qui a pu être collecté.
        """
        cumul: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            lot = await self._requeter(TAILLE_PAGE, page * TAILLE_PAGE, where)
            if lot is None:
                return None if page == 0 else cumul
            cumul.extend(lot)
            if len(lot) < TAILLE_PAGE:
                break  # dernière page disponible
            if borne is not None and _page_anterieure(lot, borne):
                break  # fenêtre incrémentale dépassée
        return cumul

    async def _requeter(
        self, limite_api: int, offset: int, where: str | None
    ) -> list[dict[str, Any]] | None:
        """Exécute une requête Opendatasoft. Renvoie None en cas d'échec HTTP."""
        params: dict[str, Any] = {
            "limit": limite_api,
            "offset": offset,
            "order_by": "dateparution desc",
            "select": _SELECT,
        }
        if where:
            params["where"] = where

        async def envoyer() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": _UA, "Accept": "application/json"},
                follow_redirects=True,
            ) as client:
                return await client.get(API_URL, params=params)

        try:
            r = await requeter_avec_retry(envoyer, nom="BOAMP")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError:
            return None
        return data.get("results", [])


# --------------------------------------------------------------------------- #
# Construction de la requête serveur (ODSQL Opendatasoft)
# --------------------------------------------------------------------------- #


def _construire_where(
    inclus: tuple[str, ...],
    exclus: tuple[str, ...],
    criteres: CriteresAvances | None = None,
) -> str | None:
    """Construit une clause ODSQL `where` à partir des mots-clés + critères avancés.

    Forme : <clauses positives jointes par AND> [AND NOT (exclus…)]

    On cible le champ `objet` via la fonction `search()` (full-text par mot).
    C'est volontaire : une recherche plein-texte nue sur tout l'enregistrement
    matche les mentions légales (ex. « RCS » = Registre du Commerce, présent
    partout) et explose en faux positifs.

    Renvoie None si **aucune** clause positive (mots-clés inclus, descripteurs,
    départements, natures ou dates) : on garde alors la collecte des derniers
    avis. Un `exclus` seul ne justifie pas une requête serveur (le NOT seul
    ramènerait tout le corpus).
    """
    criteres = criteres or CriteresAvances()
    clauses: list[str] = []

    inc = [_echapper(k) for k in inclus if _echapper(k)]
    if inc:
        clauses.append("(" + " OR ".join(f'search(objet, "{k}")' for k in inc) + ")")

    desc = [_echapper(d) for d in criteres.descripteurs if _echapper(d)]
    if desc:
        clauses.append(
            "(" + " OR ".join(f'search(descripteur_libelle, "{d}")' for d in desc) + ")"
        )

    deps = [_echapper(d) for d in criteres.departements if _echapper(d)]
    if deps:
        clauses.append("(" + " OR ".join(f'code_departement = "{d}"' for d in deps) + ")")

    nats = criteres.natures_pour("boamp")
    if nats:
        clauses.append("(" + " OR ".join(f'type_marche = "{n}"' for n in nats) + ")")

    if criteres.date_publication_depuis:
        clauses.append(f"dateparution >= date'{criteres.date_publication_depuis}'")
    if criteres.deadline_min:
        clauses.append(f"datelimitereponse >= date'{criteres.deadline_min}'")
    if criteres.deadline_max:
        clauses.append(f"datelimitereponse <= date'{criteres.deadline_max}'")

    if not clauses:
        return None
    where = " AND ".join(clauses)

    exc = [_echapper(k) for k in exclus if _echapper(k)]
    if exc:
        where += " AND NOT (" + " OR ".join(f'search(objet, "{k}")' for k in exc) + ")"
    return where


def _echapper(terme: str | None) -> str:
    """Nettoie un mot-clé pour l'insérer entre guillemets dans une clause ODSQL."""
    if not terme:
        return ""
    # On retire les guillemets pour ne pas casser la chaîne ODSQL.
    return terme.replace('"', "").strip()


# --------------------------------------------------------------------------- #
# Conversion record API → AOCollecte
# --------------------------------------------------------------------------- #


def _vers_aos(records: list[dict[str, Any]]) -> list[AOCollecte]:
    return [_record_vers_ao(rec) for rec in records if _est_valide(rec)]


def _page_anterieure(records: list[dict[str, Any]], borne: datetime) -> bool:
    """Vrai si le record le plus ancien de la page est antérieur à la borne.

    Les résultats sont triés par `dateparution` décroissante : si le dernier
    élément est déjà avant la borne, les pages suivantes le sont aussi.
    """
    if not records:
        return True
    d = _parse_iso(records[-1].get("dateparution"))
    return d is not None and d < borne


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
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=UTC)
    try:
        s = str(valeur).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
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

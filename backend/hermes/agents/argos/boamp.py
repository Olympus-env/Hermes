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

import json
import re
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
    departement_valide,
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
        self.collecte_partielle = False
        where = _construire_where(self.filtre_inclus, self.filtre_exclus, self.criteres)
        # Restriction « avis ouverts » : toujours appliquée, y compris au repli.
        where_ouvert = _restreindre_aux_avis_ouverts(where)

        if where is None:
            # Sans filtre : derniers avis seulement (comportement historique ;
            # la veille ciblée passe toujours un filtre, donc pas de pagination).
            # Une panne lève : ne jamais la confondre avec « aucun avis ».
            records = await self._requeter(min(limite, 100), 0, where_ouvert)
            return _vers_aos(records)

        # Avec filtre serveur : les avis pertinents sont rares et dispersés —
        # on pagine jusqu'à la fenêtre incrémentale ou au plafond de pages.
        borne = borne_incrementale(self.depuis)
        try:
            records = await self._collecter_pagine(where_ouvert, borne)
        except httpx.HTTPError:
            # Requête filtrée rejetée par l'API (ODSQL invalide, champ, etc.) :
            # repli sûr sur les avis ouverts non filtrés — le runner re-filtrera
            # côté client. Si le repli échoue aussi, l'erreur remonte au runner
            # (journalisée, `derniere_collecte` inchangée : aucun avis perdu).
            repli = _restreindre_aux_avis_ouverts(None)
            records = await self._requeter(min(limite, 100), 0, repli)
        return _vers_aos(records)

    async def _collecter_pagine(
        self, where: str, borne: datetime | None
    ) -> list[dict[str, Any]]:
        """Pagine via `offset` jusqu'à la borne incrémentale ou au plafond.

        Lève si la *première* page échoue (déclenche le repli). Un échec sur une
        page suivante renvoie ce qui a été collecté et marque la collecte comme
        partielle : le runner n'avancera pas `derniere_collecte`.
        """
        cumul: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            try:
                lot = await self._requeter(TAILLE_PAGE, page * TAILLE_PAGE, where)
            except httpx.HTTPError:
                if page == 0:
                    raise
                self.collecte_partielle = True
                break
            cumul.extend(lot)
            if len(lot) < TAILLE_PAGE:
                break  # dernière page disponible
            if borne is not None and _page_anterieure(lot, borne):
                break  # fenêtre incrémentale dépassée
        return cumul

    async def _requeter(
        self, limite_api: int, offset: int, where: str | None
    ) -> list[dict[str, Any]]:
        """Exécute une requête Opendatasoft. Lève `httpx.HTTPError` en cas d'échec."""
        params: dict[str, Any] = {
            "limit": limite_api,
            "offset": offset,
            # Clé secondaire `idweb` : sans elle, les avis d'un même jour peuvent
            # changer de page entre deux requêtes (offset) et être sautés/doublés.
            "order_by": "dateparution desc, idweb desc",
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

        r = await requeter_avec_retry(envoyer, nom="BOAMP")
        r.raise_for_status()
        data = r.json()
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

    # Départements : format validé avant interpolation (jamais de texte libre).
    deps = [d for d in criteres.departements if departement_valide(d)]
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


# Avis d'appel à concurrence initiaux uniquement. Valeurs vérifiées en live
# (2026-09-29) : `nature` ∈ {APPEL_OFFRE, ATTRIBUTION, RECTIFICATIF, MODIFICATION,
# ANNULATION, PRE-INFORMATION, EX_ANTE_VOLONTAIRE, PERIODIQUE} et `etat` ∈
# {INITIAL, RECTIFICATIF, MODIFICATION, ANNULATION}. Un rectificatif ou une
# attribution n'est pas un AO à traiter (doublon ou marché déjà attribué).
_AVIS_OUVERT = 'nature = "APPEL_OFFRE" AND etat = "INITIAL"'


def _restreindre_aux_avis_ouverts(where: str | None) -> str:
    """Ajoute la restriction « avis d'appel initial » à une clause utilisateur."""
    return _AVIS_OUVERT if where is None else f"{_AVIS_OUVERT} AND {where}"


def _echapper(terme: str | None) -> str:
    """Nettoie un mot-clé pour l'insérer entre guillemets dans une clause ODSQL."""
    if not terme:
        return ""
    # On retire les guillemets et on double les antislashs pour ne pas casser
    # (ni détourner) la chaîne ODSQL.
    return terme.replace('"', "").replace("\\", "\\\\").strip()


# --------------------------------------------------------------------------- #
# Conversion record API → AOCollecte
# --------------------------------------------------------------------------- #


def _vers_aos(records: list[dict[str, Any]]) -> list[AOCollecte]:
    return [_record_vers_ao(rec) for rec in records if _est_valide(rec)]


def _page_anterieure(records: list[dict[str, Any]], borne: datetime) -> bool:
    """Vrai si le record daté le plus ancien de la page est antérieur à la borne.

    Les résultats sont triés par `dateparution` décroissante : si le dernier
    élément daté est déjà avant la borne, les pages suivantes le sont aussi.
    Une page sans aucune date exploitable ne permet pas de poursuivre (on
    s'arrête plutôt que de paginer jusqu'au plafond pour rien).
    """
    for rec in reversed(records):
        d = _parse_iso(rec.get("dateparution"))
        if d is not None:
            return d < borne
    return True


def _est_valide(rec: dict[str, Any]) -> bool:
    """Filtre les records inexploitables (sans titre ni objet) ou non initiaux.

    Garde-fou client de la restriction serveur : un avis dont `nature`/`etat`
    est renseigné et n'est pas un appel d'offre initial est écarté.
    """
    nature, etat = rec.get("nature"), rec.get("etat")
    if (nature and nature != "APPEL_OFFRE") or (etat and etat != "INITIAL"):
        return False
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
    siret, cpv = extraire_identifiants(rec.get("donnees"))

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
        emetteur_siret=siret,
        code_cpv=cpv,
    )


# --------------------------------------------------------------------------- #
# Identifiants acheteur / CPV dans le JSON `donnees` (liaison DECP)
# --------------------------------------------------------------------------- #

_RE_SIRET = re.compile(r"\d{14}")
_RE_CPV = re.compile(r"\d{8}")


def _chercher(obj: Any, cle: str) -> Any:
    """Première valeur de la clé `cle`, en profondeur d'abord (None sinon)."""
    if isinstance(obj, dict):
        if cle in obj:
            return obj[cle]
        for v in obj.values():
            trouve = _chercher(v, cle)
            if trouve is not None:
                return trouve
    elif isinstance(obj, list):
        for v in obj:
            trouve = _chercher(v, cle)
            if trouve is not None:
                return trouve
    return None


def _texte_ubl(v: Any) -> str | None:
    """Valeur texte d'un nœud eForms (str ou {'#text': …})."""
    if isinstance(v, dict):
        v = v.get("#text")
    return str(v).strip() if v is not None else None


def _siret_eforms(donnees: dict[str, Any]) -> str | None:
    """SIRET de l'acheteur d'un avis eForms (organisation liée au ContractingParty)."""
    partie = _chercher(donnees, "cac:ContractingParty")
    id_acheteur = None
    if isinstance(partie, dict):
        identification = (partie.get("cac:Party") or {}).get("cac:PartyIdentification") or {}
        id_acheteur = _texte_ubl(identification.get("cbc:ID"))
    orgs = _chercher(donnees, "efac:Organization")
    if isinstance(orgs, dict):
        orgs = [orgs]
    for org in orgs or []:
        societe = org.get("efac:Company") or {}
        ident = _texte_ubl((societe.get("cac:PartyIdentification") or {}).get("cbc:ID"))
        if id_acheteur and ident == id_acheteur:
            return _texte_ubl((societe.get("cac:PartyLegalEntity") or {}).get("cbc:CompanyID"))
    return None


def extraire_identifiants(donnees: Any) -> tuple[str | None, str | None]:
    """(SIRET acheteur, CPV principal) extraits du JSON `donnees` d'un avis BOAMP.

    Trois formats coexistent : eForms (depuis 2024), FNSimple (MAPA récents) et
    l'ancien format (IDENTITE/OBJET). Best-effort : (None, None) si absent ou
    illisible — jamais d'exception.
    """
    if isinstance(donnees, str):
        try:
            donnees = json.loads(donnees)
        except ValueError:
            return None, None
    if not isinstance(donnees, dict):
        return None, None

    siret: str | None = None
    cpv: str | None = None
    if "EFORMS" in donnees:
        siret = _siret_eforms(donnees)
        noeud = _chercher(donnees, "cbc:ItemClassificationCode")
        if isinstance(noeud, dict) and noeud.get("@listName") == "cpv":
            cpv = _texte_ubl(noeud)
    else:
        siret = _texte_ubl(
            _chercher(donnees, "codeIdentificationNational")
            or _chercher(donnees, "CODE_IDENT_NATIONAL")
        )
        cpv = _texte_ubl(
            _chercher(donnees, "classPrincipale")
            or _chercher(_chercher(donnees, "CPV") or {}, "PRINCIPAL")
        )
    siret = re.sub(r"\s", "", siret) if siret else None
    return (
        siret if siret and _RE_SIRET.fullmatch(siret) else None,
        cpv if cpv and _RE_CPV.fullmatch(cpv) else None,
    )


async def recuperer_identifiants(
    idweb: str, timeout: float = 30.0
) -> tuple[str | None, str | None]:
    """Relit un avis BOAMP par `idweb` et en extrait (SIRET, CPV) — lecture seule.

    Sert au rattrapage des AO collectés avant l'ajout de ces colonnes. Lève
    `httpx.HTTPError` en cas de panne (à l'appelant de décider).
    """
    params = {"limit": 1, "select": "donnees", "where": f'idweb = "{_echapper(idweb)}"'}

    async def envoyer() -> httpx.Response:
        async with httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": _UA, "Accept": "application/json"}
        ) as client:
            return await client.get(API_URL, params=params)

    r = await requeter_avec_retry(envoyer, nom="BOAMP")
    r.raise_for_status()
    resultats = r.json().get("results", [])
    return extraire_identifiants(resultats[0].get("donnees")) if resultats else (None, None)


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

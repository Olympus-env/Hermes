"""ARGOS — DECP : historique des marchés attribués (analyse concurrentielle).

Source : Données essentielles de la commande publique consolidées (format
tabulaire), publiées en open data sur data.gouv.fr et interrogées via l'API
tabulaire officielle (lecture seule, sans clé, sans authentification) :

    https://tabular-api.data.gouv.fr/api/resources/<RESOURCE_ID>/data/

Voir `docs/decp.md` (champs, requêtes, limites, licence).

Principes :
- **Requêtes ciblées**, jamais de téléchargement massif : par SIRET acheteur
  (`acheteur_id`) ou par CPV, sur 3 ans, marchés à jour (`donneesActuelles`).
- **Cache local** (MNEMOSYNE, table `cache_decp`) avec TTL : un AO consulté
  plusieurs fois ne rappelle pas l'API ; en cas de panne, le cache périmé est
  servi plutôt que rien.
- **Rate-limit poli** : une requête à la fois, ≥ 1 s entre deux appels.
- Le module ne parle qu'à data.gouv.fr (portail public officiel).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from hermes.agents.argos.reseau import requeter_avec_retry
from hermes.config import settings
from hermes.db.models import CacheDecp

_UA = "HERMES/0.1 (veille appels d'offre locale; lecture seule)"

COLONNES = (
    "uid,acheteur_id,titulaire_id,titulaire_nom,montant,codeCPV,objet,"
    "offresRecues,dateNotification"
)
TAILLE_PAGE = 200
MAX_PAGES = 3  # plafond : 600 lignes par requête ciblée
FENETRE_ANNEES = 3
TTL_CACHE = timedelta(hours=24)
INTERVALLE_MIN_S = 1.0
SEUIL_TENDANCE = 0.10  # ±10 % sur le montant médian

_verrou = asyncio.Lock()
_dernier_appel = 0.0


class DecpIndisponible(Exception):
    """L'API DECP est injoignable et aucun cache n'est disponible."""


def _maintenant() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Récupération (réseau + cache)
# --------------------------------------------------------------------------- #


async def _get_page(params: dict[str, Any]) -> dict[str, Any]:
    """Une requête polie (sérialisée, espacée) vers l'API tabulaire."""
    global _dernier_appel

    async with _verrou:
        attente = INTERVALLE_MIN_S - (time.monotonic() - _dernier_appel)
        if attente > 0:
            await asyncio.sleep(attente)

        async def envoyer() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": _UA, "Accept": "application/json"},
                follow_redirects=True,
            ) as client:
                return await client.get(settings.decp_url, params=params)

        try:
            r = await requeter_avec_retry(envoyer, nom="DECP")
        finally:
            _dernier_appel = time.monotonic()
    r.raise_for_status()
    return r.json()


def _reduire(ligne: dict[str, Any]) -> dict[str, Any]:
    return {
        "uid": ligne.get("uid"),
        "acheteur_id": ligne.get("acheteur_id"),
        "titulaire_id": ligne.get("titulaire_id"),
        "titulaire_nom": ligne.get("titulaire_nom"),
        "montant": ligne.get("montant"),
        "cpv": ligne.get("codeCPV"),
        "objet": (ligne.get("objet") or "")[:200] or None,
        "offres": ligne.get("offresRecues"),
        "date": ligne.get("dateNotification"),
    }


async def _requeter(
    filtres: dict[str, str], depuis: date
) -> tuple[list[dict[str, Any]], int | None]:
    """Pagine (plafonné) les marchés à jour notifiés depuis `depuis`.

    Renvoie (lignes brutes reçues, total réel annoncé par l'API : `meta.total`).
    """
    params: dict[str, Any] = {
        **filtres,
        "donneesActuelles__exact": "true",
        "dateNotification__greater": depuis.isoformat(),
        "dateNotification__sort": "desc",
        "columns": COLONNES,
        "page_size": TAILLE_PAGE,
    }
    lignes: list[dict[str, Any]] = []
    total: int | None = None
    for page in range(1, MAX_PAGES + 1):
        data = await _get_page({**params, "page": page})
        meta_total = (data.get("meta") or {}).get("total")
        if isinstance(meta_total, int):
            total = meta_total
        lot = data.get("data") or []
        lignes.extend(_reduire(x) for x in lot)
        if len(lot) < TAILLE_PAGE or not (data.get("links") or {}).get("next"):
            break
    return lignes, total


# Un verrou par clé de cache : la lecture du cache, l'appel réseau et l'écriture
# forment une section critique. Des requêtes simultanées (double effet React,
# plusieurs onglets) n'interrogent donc l'API qu'une fois et n'insèrent qu'une
# ligne (`cle` est UNIQUE).
_verrous_cles: dict[tuple[int, str], asyncio.Lock] = {}


def _lire_cache(ligne: CacheDecp) -> tuple[list[dict[str, Any]], int | None]:
    contenu = json.loads(ligne.marches)
    if isinstance(contenu, list):  # ancien format : liste seule
        return contenu, None
    return contenu.get("marches", []), contenu.get("total")


def _ecrire_cache(session: Session, cle: str, marches: list, total: int | None) -> CacheDecp:
    charge = json.dumps({"marches": marches, "total": total}, ensure_ascii=False)
    for _ in range(2):
        ligne = session.exec(select(CacheDecp).where(CacheDecp.cle == cle)).first()
        if ligne is None:
            ligne = CacheDecp(cle=cle, marches=charge)
        ligne.marches = charge
        ligne.recupere_le = _maintenant()
        session.add(ligne)
        try:
            session.commit()
            return ligne
        except IntegrityError:  # filet : insertion concurrente hors verrou
            session.rollback()
    raise DecpIndisponible("écriture du cache DECP impossible")


async def _marches_en_cache(
    session: Session, cle: str, filtres: dict[str, str], *, forcer: bool = False
) -> tuple[list[dict[str, Any]], int | None, datetime, bool]:
    """(marchés bruts, total réel, date de récupération, servi_depuis_le_cache).

    Cache frais → rendu tel quel. Sinon appel réseau puis mise en cache ; si
    l'appel échoue, le cache périmé est rendu (dégradation honnête) et, sans
    cache, `DecpIndisponible` est levée.
    """
    # (Clé aussi par boucle d'événements : un asyncio.Lock ne se partage pas entre boucles.)
    verrou = _verrous_cles.setdefault((id(asyncio.get_running_loop()), cle), asyncio.Lock())
    async with verrou:
        ligne = session.exec(select(CacheDecp).where(CacheDecp.cle == cle)).first()
        if ligne:
            session.refresh(ligne)
        if ligne and not forcer and _maintenant() - _aware(ligne.recupere_le) < TTL_CACHE:
            marches, total = _lire_cache(ligne)
            return marches, total, _aware(ligne.recupere_le), True

        depuis = (_maintenant() - timedelta(days=365 * FENETRE_ANNEES)).date()
        try:
            marches, total = await _requeter(filtres, depuis)
        except (httpx.HTTPError, ValueError) as exc:
            if ligne:
                marches, total = _lire_cache(ligne)
                return marches, total, _aware(ligne.recupere_le), True
            raise DecpIndisponible(str(exc) or exc.__class__.__name__) from exc

        ligne = _ecrire_cache(session, cle, marches, total)
        return marches, total, _aware(ligne.recupere_le), False


# --------------------------------------------------------------------------- #
# Analyse (pur, testable hors réseau)
# --------------------------------------------------------------------------- #


def _uniques(marches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Un marché par `uid` (un marché multi-titulaires occupe plusieurs lignes)."""
    vus: dict[str, dict[str, Any]] = {}
    for m in marches:
        vus.setdefault(m.get("uid") or f"{m.get('date')}|{m.get('titulaire_id')}", m)
    return list(vus.values())


def _montant(m: dict[str, Any]) -> float | None:
    v = m.get("montant")
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


def _median(valeurs: list[float]) -> float | None:
    return statistics.median(valeurs) if valeurs else None


def analyser(
    marches: list[dict[str, Any]],
    *,
    aujourdhui: date | None = None,
    debut_couvert: date | None = None,
) -> dict[str, Any]:
    """Titulaires récurrents, montant médian et tendance à partir des marchés.

    `debut_couvert` : date la plus ancienne réellement couverte quand
    l'échantillon est plafonné (None = fenêtre complète).
    """
    aujourdhui = aujourdhui or _maintenant().date()
    uniques = _uniques(marches)

    montants = [x for x in (_montant(m) for m in uniques) if x is not None]
    offres = [m["offres"] for m in uniques if isinstance(m.get("offres"), int) and m["offres"] > 0]

    # Titulaires : nombre de marchés distincts et montant cumulé par titulaire.
    stats: dict[str, dict[str, Any]] = {}
    for m in marches:
        nom = m.get("titulaire_nom")
        cle = m.get("titulaire_id") or nom
        if not cle:
            continue
        # Regroupement par SIREN : les établissements d'une même société ne
        # doivent pas apparaître comme des concurrents distincts.
        if str(cle).isdigit() and len(str(cle)) == 14:
            cle = str(cle)[:9]
        s = stats.setdefault(
            cle, {"nom": nom or cle, "siret": m.get("titulaire_id"), "uids": set(), "montant": 0.0}
        )
        uid = m.get("uid") or id(m)
        if uid not in s["uids"]:
            s["uids"].add(uid)
            s["montant"] += _montant(m) or 0.0
    total = len(uniques)
    titulaires = sorted(
        (
            {
                "nom": s["nom"],
                "siret": s["siret"],
                "nb_marches": len(s["uids"]),
                "montant_total": round(s["montant"], 2),
                "part": round(len(s["uids"]) / total, 3) if total else 0.0,
            }
            for s in stats.values()
        ),
        key=lambda t: (-t["nb_marches"], -t["montant_total"], t["nom"]),
    )[:10]

    return {
        "nb_marches": total,
        "montant_median": _median(montants),
        "montant_total": round(sum(montants), 2) if montants else None,
        "offres_moyennes": round(statistics.mean(offres), 1) if offres else None,
        "titulaires": titulaires,
        "tendance": _tendance(uniques, aujourdhui, debut_couvert),
        "marches_recents": [
            {
                "date": m.get("date"),
                "titulaire": m.get("titulaire_nom"),
                "montant": _montant(m),
                "objet": m.get("objet"),
                "offres": m.get("offres"),
            }
            for m in sorted(uniques, key=lambda m: m.get("date") or "", reverse=True)[:8]
        ],
    }


def _tendance(
    uniques: list[dict[str, Any]], aujourdhui: date, debut_couvert: date | None = None
) -> dict[str, Any]:
    """12 derniers mois vs les 12 mois précédents (volume et montant médian)."""
    borne_recente = aujourdhui - timedelta(days=365)
    borne_ancienne = aujourdhui - timedelta(days=730)
    recent: list[dict[str, Any]] = []
    precedent: list[dict[str, Any]] = []
    for m in uniques:
        try:
            d = date.fromisoformat(str(m.get("date"))[:10])
        except ValueError:
            continue
        if d > borne_recente:
            recent.append(m)
        elif d > borne_ancienne:
            precedent.append(m)

    med_r = _median([x for x in map(_montant, recent) if x is not None])
    med_p = _median([x for x in map(_montant, precedent) if x is not None])
    sens = "indeterminee"
    # Échantillon plafonné qui ne remonte pas jusqu'à la période précédente :
    # comparer à un « an précédent » vide serait trompeur.
    precedent_couvert = debut_couvert is None or debut_couvert <= borne_ancienne
    if precedent_couvert and med_r is not None and med_p:
        ecart = (med_r - med_p) / med_p
        if ecart > SEUIL_TENDANCE:
            sens = "hausse"
        elif ecart < -SEUIL_TENDANCE:
            sens = "baisse"
        else:
            sens = "stable"
    return {
        "sens": sens,
        "precedent_couvert": precedent_couvert,
        "nb_recent": len(recent),
        "nb_precedent": len(precedent),
        "montant_median_recent": med_r,
        "montant_median_precedent": med_p,
    }


# --------------------------------------------------------------------------- #
# Point d'entrée : concurrence d'un AO
# --------------------------------------------------------------------------- #


def _cpv_valide(cpv: str | None) -> str | None:
    return cpv if cpv and len(cpv) == 8 and cpv.isdigit() else None


async def concurrence(
    session: Session, *, siret: str | None, cpv: str | None, forcer: bool = False
) -> dict[str, Any]:
    """Analyse acheteur (SIRET) et secteur (CPV) ; blocs absents si non calculables.

    Lève `DecpIndisponible` seulement si *aucun* bloc n'a pu être obtenu.
    """
    resultat: dict[str, Any] = {"acheteur": None, "secteur": None, "maj_le": None,
                                "depuis_cache": True, "erreur": None}
    erreurs: list[str] = []

    demandes: list[tuple[str, str, dict[str, str], str | None]] = []
    if siret:
        demandes.append(("acheteur", f"acheteur:{siret}", {"acheteur_id__exact": siret}, None))
    cpv = _cpv_valide(cpv)
    if cpv:
        # Groupe CPV (4 premiers chiffres) : assez large pour avoir un échantillon,
        # assez étroit pour rester pertinent. `contains` côté API, préfixe côté client.
        prefixe = cpv[:4]
        demandes.append(("secteur", f"cpv:{prefixe}", {"codeCPV__contains": prefixe}, prefixe))

    for bloc, cle, filtres, prefixe in demandes:
        try:
            brut, total, maj, cache = await _marches_en_cache(
                session, cle, filtres, forcer=forcer
            )
        except DecpIndisponible as exc:
            erreurs.append(str(exc))
            continue
        # Plafond évalué sur les lignes BRUTES (avant filtre de préfixe CPV).
        plafonne = len(brut) >= TAILLE_PAGE * MAX_PAGES or (
            total is not None and total > len(brut)
        )
        dates = sorted(str(m["date"])[:10] for m in brut if m.get("date"))
        debut = date.fromisoformat(dates[0]) if plafonne and dates else None
        marches = brut
        if prefixe:
            marches = [m for m in brut if str(m.get("cpv") or "").startswith(prefixe)]
        analyse = analyser(marches, debut_couvert=debut)
        analyse["periode_annees"] = FENETRE_ANNEES
        analyse["echantillon_plafonne"] = plafonne
        analyse["total_reel"] = total
        analyse["periode_debut"] = dates[0] if plafonne and dates else None
        analyse["periode_fin"] = dates[-1] if plafonne and dates else None
        resultat[bloc] = analyse
        resultat["depuis_cache"] = resultat["depuis_cache"] and cache
        if resultat["maj_le"] is None or maj < resultat["maj_le"]:
            resultat["maj_le"] = maj

    if demandes and not any(resultat[b] for b in ("acheteur", "secteur")):
        raise DecpIndisponible("; ".join(erreurs) or "aucune donnée")
    if erreurs:
        resultat["erreur"] = "Certaines données DECP sont indisponibles : " + "; ".join(erreurs)
    return resultat


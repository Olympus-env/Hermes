"""Profils de capacités déclaratifs par portail ARGOS.

Décrit, pour chaque source officielle, ce que son API publique permet :
filtrage serveur, champs filtrables, champs retournés, pagination et liens
documents. C'est le contrat unique (priorité P1 de
``docs/api-ted-boamp-capabilities.md``) consommé par les scrapers, les tests et
— plus tard — l'UI Paramètres.

Pur déclaratif : aucune I/O, aucune dépendance réseau, lecture seule. Les listes
de champs (``select`` BOAMP, ``fields`` TED) vivent ici comme **source unique
versionnée** pour éviter qu'elles divergent entre scraper et profil.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Listes de champs versionnées (source unique)
# --------------------------------------------------------------------------- #

# BOAMP — champs Opendatasoft *validés en live* (smoke 2026-06-19). Toute valeur
# lue par le parseur `boamp._record_vers_ao` doit figurer ici, sinon `select`
# masquerait la donnée. `titre_marche`, lu en repli par le parseur, n'existe pas
# dans le dataset : volontairement absent (le `.get` renvoie None, comportement
# inchangé).
CHAMPS_BOAMP: tuple[str, ...] = (
    "objet",
    "nomacheteur",
    "idweb",
    "id",
    "contractfolderid",
    "url_avis",
    "dateparution",
    "datelimitereponse",
    "nature_libelle",
    "type_marche",
    "code_departement",
    "code_departement_prestation",
    "descripteur_code",
    "descripteur_libelle",
)

# TED — champs eForms demandés via `fields`. Identique à la liste historique du
# scraper (validée en live) ; centralisée ici sans changement de comportement.
CHAMPS_TED: tuple[str, ...] = (
    "publication-number",
    "notice-title",
    "publication-date",
    "deadline-receipt-tender-date-lot",
    "buyer-name",
    "place-of-performance",
    "classification-cpv",
    "links",
)


# --------------------------------------------------------------------------- #
# Profil de capacités
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProfilCapacites:
    """Capacités déclarées d'un portail ARGOS (lecture seule)."""

    portail: str
    filtrage_serveur: bool
    champs_filtrables: tuple[str, ...] = ()
    champs_retournes: tuple[str, ...] = ()
    pagination: bool = False
    liens_documents: bool = False


PROFIL_BOAMP = ProfilCapacites(
    portail="boamp",
    filtrage_serveur=True,
    # Le filtrage serveur cible le champ `objet` via `search()` (full-text par
    # mot) ; les autres champs servent à la normalisation, pas au filtre.
    champs_filtrables=("objet",),
    champs_retournes=CHAMPS_BOAMP,
    pagination=True,
    # L'API `records` n'expose pas de lien DCE direct exploitable : la détection
    # de documents publics BOAMP est traitée en Boucle 3.
    liens_documents=False,
)

PROFIL_TED = ProfilCapacites(
    portail="ted",
    filtrage_serveur=True,
    # Query expert eForms : lieu d'exécution + titre (acronymes exclus du
    # serveur, voir scraper). CPV/nature seront ajoutés en Boucle 2.
    champs_filtrables=("place-of-performance", "notice-title"),
    champs_retournes=CHAMPS_TED,
    pagination=True,
    # `links` expose HTML/PDF/XML directs (exploités en Boucle 3).
    liens_documents=True,
)


_PROFILS: dict[str, ProfilCapacites] = {
    PROFIL_BOAMP.portail: PROFIL_BOAMP,
    PROFIL_TED.portail: PROFIL_TED,
}


def profil_pour(portail: str) -> ProfilCapacites | None:
    """Renvoie le profil de capacités d'un portail, ou None si inconnu."""
    return _PROFILS.get(portail)


def tous_les_profils() -> list[ProfilCapacites]:
    """Renvoie tous les profils déclarés, triés par nom de portail."""
    return [_PROFILS[nom] for nom in sorted(_PROFILS)]

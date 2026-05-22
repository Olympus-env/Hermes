"""Suivi d'avancement des rédactions HERMION (issue #7).

La génération est synchrone et longue (plan + N sections via PYTHIA). Sans
retour, l'utilisateur ne sait pas si HERMION travaille, est bloqué ou a
échoué. Ce module tient un état d'avancement en mémoire, par appel d'offre,
que le writer met à jour à chaque étape et qu'un endpoint de polling expose.

In-memory volontairement : l'app est mono-process local ; l'historique
durable, lui, vit déjà dans `logs_agents` et `reponses_hermion`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

# Étapes ordonnées d'une rédaction.
ETAPE_PREPARATION = "preparation"
ETAPE_PLAN = "plan"
ETAPE_REDACTION = "redaction"
ETAPE_FINALISATION = "finalisation"
ETAPE_TERMINE = "termine"
ETAPE_ECHEC = "echec"

LIBELLES = {
    ETAPE_PREPARATION: "Préparation du contexte",
    ETAPE_PLAN: "Construction du plan de réponse",
    ETAPE_REDACTION: "Rédaction des sections",
    ETAPE_FINALISATION: "Finalisation du document",
    ETAPE_TERMINE: "Terminé",
    ETAPE_ECHEC: "Échec",
}


@dataclass
class EtatProgression:
    appel_offre_id: int
    etape: str = ETAPE_PREPARATION
    index: int = 0  # section courante (1-based) pendant la rédaction
    total: int = 0  # nombre de sections à rédiger
    message: str = ""
    erreur: str | None = None
    termine: bool = False
    reponse_id: int | None = None
    debut: float = field(default_factory=time.time)
    maj: float = field(default_factory=time.time)

    def en_dict(self) -> dict[str, object]:
        return {
            "appel_offre_id": self.appel_offre_id,
            "etape": self.etape,
            "libelle": LIBELLES.get(self.etape, self.etape),
            "index": self.index,
            "total": self.total,
            "message": self.message,
            "erreur": self.erreur,
            "termine": self.termine,
            "reponse_id": self.reponse_id,
            "secondes_ecoulees": round(self.maj - self.debut, 1),
        }


_etats: dict[int, EtatProgression] = {}
_verrou = Lock()


def demarrer(ao_id: int) -> None:
    with _verrou:
        _etats[ao_id] = EtatProgression(appel_offre_id=ao_id)


def maj(
    ao_id: int,
    etape: str,
    *,
    index: int = 0,
    total: int = 0,
    message: str = "",
) -> None:
    with _verrou:
        etat = _etats.get(ao_id)
        if etat is None:
            etat = EtatProgression(appel_offre_id=ao_id)
            _etats[ao_id] = etat
        etat.etape = etape
        if index:
            etat.index = index
        if total:
            etat.total = total
        etat.message = message
        etat.maj = time.time()


def terminer(ao_id: int, *, reponse_id: int | None = None) -> None:
    with _verrou:
        etat = _etats.get(ao_id)
        if etat is None:
            return
        etat.etape = ETAPE_TERMINE
        etat.termine = True
        etat.reponse_id = reponse_id
        etat.message = ""
        etat.maj = time.time()


def echec(ao_id: int, message: str) -> None:
    with _verrou:
        etat = _etats.get(ao_id)
        if etat is None:
            etat = EtatProgression(appel_offre_id=ao_id)
            _etats[ao_id] = etat
        etat.etape = ETAPE_ECHEC
        etat.termine = True
        etat.erreur = message
        etat.maj = time.time()


def lire(ao_id: int) -> EtatProgression | None:
    with _verrou:
        return _etats.get(ao_id)

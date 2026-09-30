"""KRINOS — calibration de Jev / PYTHIA / composite contre la décision humaine (#44).

Heuristique de « décision humaine » (documentée, lecture seule, aucune donnée ne sort) :
    - accepté  : l'AO est `repondu`, OU il a une réponse HERMION validée/exportée
      (`validee`/`exportee`, actions exclusivement humaines) ;
    - rejeté   : l'AO est `rejete` (prime sur une éventuelle réponse validée).
`a_repondre` et `en_redaction` ne comptent PAS : l'orchestrateur peut les poser sans
humain. Les autres statuts (`brut`, `analyse`, `expire`, `hors_filtre`) sont ignorés :
pas de décision avérée, donc rien à comparer. On s'appuie sur les statuts et les
réponses plutôt que sur `logs_agents`, qui ne trace pas ces transitions.

Pour chaque source (PYTHIA, Jev, composite) et chaque seuil de score testé, on
construit une matrice de confusion « la source aurait dit go » vs « l'humain a
accepté ». Jev et le composite ne comptent que les AO où Jev a réellement répondu.
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from hermes.agents.krinos.ponderation import (
    ConfigComposite,
    calculer_composite,
    charger_composite,
)
from hermes.db.models import AnalyseKrinos, AppelOffre, ReponseHermion, StatutAO, StatutReponse

STATUTS_REPONSE_HUMAINE = frozenset({StatutReponse.VALIDEE, StatutReponse.EXPORTEE})
SEUILS_TESTES = (40, 50, 60, 70, 80)

HEURISTIQUE = (
    "Décision humaine avérée : accepté = AO repondu ou réponse HERMION validée/exportée ; "
    "rejeté = rejete. a_repondre/en_redaction (posables par l'orchestrateur) et les autres "
    "statuts sont ignorés. Un score « go » signifie score >= seuil. Jev et composite ne "
    "portent que sur les AO où Jev a répondu."
)


def _moyenne(valeurs: list[float]) -> float | None:
    return round(sum(valeurs) / len(valeurs), 1) if valeurs else None


def _matrice(echantillon: list[tuple[float, bool]], seuil: float) -> dict[str, Any]:
    vp = sum(1 for s, ok in echantillon if s >= seuil and ok)
    fp = sum(1 for s, ok in echantillon if s >= seuil and not ok)
    vn = sum(1 for s, ok in echantillon if s < seuil and not ok)
    fn = sum(1 for s, ok in echantillon if s < seuil and ok)
    total = len(echantillon)
    return {
        "seuil": seuil,
        "vrais_positifs": vp,
        "faux_positifs": fp,
        "vrais_negatifs": vn,
        "faux_negatifs": fn,
        "taux_accord": round((vp + vn) / total, 3) if total else None,
    }


def _source(echantillon: list[tuple[float, bool]], seuil_courant: float) -> dict[str, Any]:
    return {
        "n": len(echantillon),
        "taux_accord": _matrice(echantillon, seuil_courant)["taux_accord"],
        "score_moyen_accepte": _moyenne([s for s, ok in echantillon if ok]),
        "score_moyen_rejete": _moyenne([s for s, ok in echantillon if not ok]),
        "matrice": [_matrice(echantillon, s) for s in SEUILS_TESTES],
    }


def calibrer(session: Session, config: ConfigComposite | None = None) -> dict[str, Any]:
    """Compare les scores stockés à la décision humaine ; aucune ré-inférence."""
    config = config or charger_composite(session)
    avec_reponse = set(
        session.exec(
            select(ReponseHermion.appel_offre_id).where(
                ReponseHermion.statut.in_(STATUTS_REPONSE_HUMAINE)  # type: ignore[attr-defined]
            )
        ).all()
    )
    lignes = session.exec(
        select(AnalyseKrinos, AppelOffre)
        .join(AppelOffre, AppelOffre.id == AnalyseKrinos.appel_offre_id)  # type: ignore[arg-type]
        .order_by(AnalyseKrinos.cree_le.desc())
    ).all()

    # Une seule analyse (la plus récente) par AO ; les analyses de secours sont exclues.
    vues: set[int] = set()
    pythia: list[tuple[float, bool]] = []
    jev_: list[tuple[float, bool]] = []
    composite: list[tuple[float, bool]] = []
    ecarts: list[float] = []
    acceptes = rejetes = 0
    for analyse, ao in lignes:
        if analyse.appel_offre_id in vues or analyse.degradee:
            continue
        if ao.statut == StatutAO.REJETE:
            accepte = False
        elif ao.statut == StatutAO.REPONDU or ao.id in avec_reponse:
            accepte = True
        else:
            continue  # pas de décision humaine avérée
        vues.add(analyse.appel_offre_id)
        acceptes += accepte
        rejetes += not accepte
        pythia.append((analyse.score, accepte))
        if analyse.score_jev is None:
            continue
        jev_.append((analyse.score_jev, accepte))
        ecarts.append(abs(analyse.score_jev - analyse.score))
        pertinence = None
        try:
            details = json.loads(analyse.details_jev) if analyse.details_jev else {}
            pertinence = details.get("pertinence") if isinstance(details, dict) else None
        except ValueError:
            pass
        valeur = calculer_composite(
            score_pythia=analyse.score,
            score_jev=analyse.score_jev,
            pertinence_jev=pertinence if isinstance(pertinence, int | float) else None,
            config=config,
        )
        if valeur is not None:
            composite.append((valeur, accepte))

    return {
        "echantillon": {
            "total": len(pythia),
            "acceptes": acceptes,
            "rejetes": rejetes,
            "avec_jev": len(jev_),
        },
        "ecart_moyen_jev_pythia": _moyenne(ecarts),
        "seuil_go": config.seuil_go,
        "sources": {
            "pythia": _source(pythia, config.seuil_go),
            "jev": _source(jev_, config.seuil_go),
            "composite": _source(composite, config.seuil_go),
        },
        "heuristique": HEURISTIQUE,
    }

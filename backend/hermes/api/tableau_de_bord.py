"""Route d'agrégats pour l'Accueil : compteurs, pipeline et activité des agents.

Une seule lecture légère de MNEMOSYNE (comptages SQL + dix entrées de journal)
évite au frontend de paginer toute la liste des AO pour afficher quatre chiffres.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from hermes.api._dates import DatetimeUTC
from hermes.api.appels_offre import _scores_recents
from hermes.db.models import (
    AppelOffre,
    LogAgent,
    NiveauLog,
    ReponseHermion,
    StatutAO,
    StatutReponse,
    _utcnow,
)
from hermes.db.session import get_session

router = APIRouter(prefix="/tableau-de-bord", tags=["tableau-de-bord"])
SessionDep = Annotated[Session, Depends(get_session)]

# AO encore « vivants » : ni rejetés, ni expirés, ni écartés par les filtres.
_STATUTS_ACTIFS = (
    StatutAO.BRUT,
    StatutAO.ANALYSE,
    StatutAO.A_REPONDRE,
    StatutAO.EN_REDACTION,
)
_SEUIL_SCORE_ELEVE = 70.0
_HORIZON_URGENT = timedelta(days=7)
_AGENTS_ACTIVITE = ("ARGOS", "KRINOS", "HERMION")


class ActiviteAgent(BaseModel):
    id: int
    agent: str
    niveau: NiveauLog
    message: str
    cree_le: DatetimeUTC


class TableauDeBord(BaseModel):
    genere_le: DatetimeUTC
    # Tous les AO hors « hors_filtre » (masqués par défaut dans la Veille).
    total_ao: int
    urgents: int
    score_eleve: int
    a_repondre: int
    # Nombre d'AO par StatutAO (toutes les valeurs de l'enum, 0 compris).
    par_statut: dict[str, int]
    # Dernière version de réponse de chaque AO, comptée par StatutReponse.
    reponses: dict[str, int]
    # ARGOS / KRINOS / HERMION, du plus récent au plus ancien.
    activite: list[ActiviteAgent]


@router.get("", response_model=TableauDeBord)
def lire_tableau_de_bord(
    session: SessionDep,
    limite_activite: int = Query(default=8, ge=1, le=50),
) -> TableauDeBord:
    maintenant = _utcnow()

    par_statut = {s.value: 0 for s in StatutAO}
    for statut, n in session.exec(
        select(AppelOffre.statut, func.count()).group_by(AppelOffre.statut)
    ).all():
        par_statut[StatutAO(statut).value] = int(n)
    total = sum(n for s, n in par_statut.items() if s != StatutAO.HORS_FILTRE.value)

    actifs = session.exec(
        select(AppelOffre.id, AppelOffre.date_limite).where(AppelOffre.statut.in_(_STATUTS_ACTIFS))
    ).all()
    urgents = sum(1 for _, d in actifs if _est_urgent(d, maintenant))
    scores = _scores_recents(session, [ao_id for ao_id, _ in actifs])
    score_eleve = sum(1 for s in scores.values() if s >= _SEUIL_SCORE_ELEVE)

    return TableauDeBord(
        genere_le=maintenant,
        total_ao=total,
        urgents=urgents,
        score_eleve=score_eleve,
        a_repondre=par_statut[StatutAO.A_REPONDRE.value],
        par_statut=par_statut,
        reponses=_reponses_par_statut(session),
        activite=_activite(session, limite_activite),
    )


def _est_urgent(date_limite: datetime | None, maintenant: datetime) -> bool:
    """Échéance à venir dans les 7 jours (une date passée n'est plus « urgente »)."""
    if date_limite is None:
        return False
    if date_limite.tzinfo is None:  # SQLite renvoie des datetimes naïfs (UTC)
        date_limite = date_limite.replace(tzinfo=maintenant.tzinfo)
    return maintenant <= date_limite <= maintenant + _HORIZON_URGENT


def _reponses_par_statut(session: Session) -> dict[str, int]:
    """Statut de la dernière version de réponse de chaque AO."""
    compte = {s.value: 0 for s in StatutReponse}
    derniere: dict[int, tuple[int, StatutReponse]] = {}
    for ao_id, version, statut in session.exec(
        select(ReponseHermion.appel_offre_id, ReponseHermion.version, ReponseHermion.statut)
    ).all():
        if ao_id not in derniere or version > derniere[ao_id][0]:
            derniere[ao_id] = (version, statut)
    for _, statut in derniere.values():
        compte[StatutReponse(statut).value] += 1
    return compte


def _activite(session: Session, limite: int) -> list[ActiviteAgent]:
    lignes = session.exec(
        select(LogAgent)
        .where(LogAgent.agent.in_(_AGENTS_ACTIVITE))
        .order_by(LogAgent.cree_le.desc(), LogAgent.id.desc())
        .limit(limite)
    ).all()
    return [
        ActiviteAgent(
            id=row.id,  # type: ignore[arg-type]
            agent=row.agent,
            niveau=row.niveau,
            message=row.message,
            cree_le=row.cree_le,
        )
        for row in lignes
    ]

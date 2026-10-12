"""Route d'agrégats pour l'Accueil : compteurs, pipeline et activité des agents.

Une seule lecture légère de MNEMOSYNE (comptages SQL + dix entrées de journal)
évite au frontend de paginer toute la liste des AO pour afficher quatre chiffres.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import aliased
from sqlmodel import Session, func, select

from hermes.api._dates import DatetimeUTC
from hermes.db.models import (
    AnalyseKrinos,
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
ReponseHermionAlias = aliased(ReponseHermion)  # sous-requête corrélée sur la même table


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

    urgents = _compter_urgents(session, maintenant)
    score_eleve = _compter_scores_eleves(session)

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


def _compter_urgents(session: Session, maintenant: datetime) -> int:
    """AO actifs dont l'échéance tombe dans [maintenant, maintenant + 7 jours].

    SQLite stocke les datetimes en texte UTC naïf (même format que les bornes liées ici) :
    la comparaison est faite en SQL, une date passée ou absente n'est pas « urgente ».
    """
    debut = maintenant.replace(tzinfo=None)
    return int(
        session.exec(
            select(func.count())
            .select_from(AppelOffre)
            .where(
                AppelOffre.statut.in_(_STATUTS_ACTIFS),
                AppelOffre.date_limite >= debut,
                AppelOffre.date_limite <= debut + _HORIZON_URGENT,
            )
        ).one()
    )


def _compter_scores_eleves(session: Session) -> int:
    """AO actifs dont la dernière analyse KRINOS atteint le seuil.

    Fenêtre (SQLite >= 3.25) : rang 1 = analyse la plus récente de chaque AO, départagée par
    id. Jointure, pas de liste d'ids en `IN` (limite de variables SQLite).
    """
    rang = (
        func.row_number()
        .over(
            partition_by=AnalyseKrinos.appel_offre_id,
            order_by=(AnalyseKrinos.cree_le.desc(), AnalyseKrinos.id.desc()),
        )
        .label("rang")
    )
    dernieres = (
        select(AnalyseKrinos.score.label("score"), rang)
        .join(AppelOffre, AppelOffre.id == AnalyseKrinos.appel_offre_id)
        .where(AppelOffre.statut.in_(_STATUTS_ACTIFS))
        .subquery()
    )
    return int(
        session.exec(
            select(func.count())
            .select_from(dernieres)
            .where(dernieres.c.rang == 1, dernieres.c.score >= _SEUIL_SCORE_ELEVE)
        ).one()
    )


def _reponses_par_statut(session: Session) -> dict[str, int]:
    """Statut de la dernière version de réponse de chaque AO, compté en SQL."""
    compte = {s.value: 0 for s in StatutReponse}
    # (appel_offre_id, version) est unique : la ligne de version maximale est donc unique.
    plus_recente = (
        select(func.max(ReponseHermion.version))
        .where(ReponseHermion.appel_offre_id == ReponseHermionAlias.appel_offre_id)
        .correlate(ReponseHermionAlias)
        .scalar_subquery()
    )
    for statut, n in session.exec(
        select(ReponseHermionAlias.statut, func.count())
        .where(ReponseHermionAlias.version == plus_recente)
        .group_by(ReponseHermionAlias.statut)
    ).all():
        compte[StatutReponse(statut).value] = int(n)
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

"""Planification quotidienne de la maintenance MNEMOSYNE (job `mnemosyne_maintenance`).

Planificateur dédié et minimal : indépendant d'`ArgosScheduler` (pause/reprise des
collectes ne doit pas suspendre la sauvegarde).
"""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlmodel import Session

from hermes.db.retention import maintenance_mnemosyne
from hermes.db.session import get_engine

JOB_ID = "mnemosyne_maintenance"


def _executer() -> None:
    with Session(get_engine()) as session:
        maintenance_mnemosyne(session)


async def _job() -> None:
    await asyncio.to_thread(_executer)


class PlanificateurMnemosyne:
    def __init__(self) -> None:
        self._sched: AsyncIOScheduler | None = None

    def demarrer(self) -> None:
        if self._sched is not None:
            return
        self._sched = AsyncIOScheduler(timezone="UTC")
        self._sched.add_job(
            _job,
            CronTrigger(hour=3, minute=17, timezone="UTC"),
            id=JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=6 * 3600,  # poste éteint à 03h17 : rattrape au démarrage
        )
        self._sched.start()
        logger.info("MNEMOSYNE : maintenance quotidienne planifiée (03:17 UTC)")

    def arreter(self) -> None:
        if self._sched is not None:
            self._sched.shutdown(wait=False)
            self._sched = None


planificateur_mnemosyne = PlanificateurMnemosyne()

"""Planification automatique des collectes ARGOS via APScheduler.

Convention : un job par portail actif, rythmé par `Portail.frequence_minutes`.
Le scheduler tourne en arrière-plan dans le process FastAPI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlmodel import Session, select

from hermes.agents.argos.registry import creer_scraper, scrapers_disponibles
from hermes.agents.argos.runner import executer_collecte
from hermes.db.models import Portail
from hermes.db.session import get_engine


class ArgosScheduler:
    """Wrapper léger autour d'APScheduler."""

    def __init__(self) -> None:
        self._sched: AsyncIOScheduler | None = None

    @property
    def en_marche(self) -> bool:
        return self._sched is not None and self._sched.running

    def demarrer(self) -> None:
        if self.en_marche:
            return
        self._sched = AsyncIOScheduler(timezone="UTC")
        self._sched.start()
        self.synchroniser_jobs()
        logger.info("ARGOS scheduler démarré")

    def arreter(self) -> None:
        if self._sched is not None:
            self._sched.shutdown(wait=False)
            self._sched = None
            logger.info("ARGOS scheduler arrêté")

    def synchroniser_jobs(self) -> None:
        """(Re)programme un job par portail actif dont le scraper existe."""
        if self._sched is None:
            return

        disponibles = set(scrapers_disponibles())

        with Session(get_engine()) as session:
            portails = session.exec(select(Portail).where(Portail.actif)).all()

        ids_a_garder: set[str] = set()
        for portail in portails:
            if portail.nom not in disponibles:
                continue
            job_id = f"argos.{portail.nom}"
            ids_a_garder.add(job_id)
            self._sched.add_job(
                func=_executer_job,
                kwargs={"nom_portail": portail.nom},
                trigger=IntervalTrigger(minutes=max(5, portail.frequence_minutes)),
                id=job_id,
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )

        for job in self._sched.get_jobs():
            if job.id not in ids_a_garder:
                self._sched.remove_job(job.id)

    def etat(self) -> dict[str, Any]:
        if self._sched is None:
            return {"en_marche": False, "jobs": []}
        return {
            "en_marche": self.en_marche,
            "jobs": [
                {
                    "id": j.id,
                    "prochaine_execution": j.next_run_time.isoformat()
                    if j.next_run_time
                    else None,
                }
                for j in self._sched.get_jobs()
            ],
        }


async def _executer_job(nom_portail: str) -> None:
    """Job APScheduler : ouvre une session BDD et lance la collecte."""
    scraper = creer_scraper(nom_portail)
    with Session(get_engine()) as session:
        try:
            await executer_collecte(scraper, session)
        except Exception:  # noqa: BLE001
            logger.exception("Échec job ARGOS %s", nom_portail)


scheduler_global = ArgosScheduler()

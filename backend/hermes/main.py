"""Point d'entrée FastAPI — backend HERMES.

À lancer :
    uvicorn hermes.main:app --host 127.0.0.1 --port 8000

Le binding sur 127.0.0.1 est volontaire : exigence sécurité du cahier des charges.
Aucun port ne doit être exposé à l'extérieur de la machine.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from hermes import __version__
from hermes.agents.argos.scheduler import scheduler_global
from hermes.api import (
    appels_offre,
    argos,
    health,
    hermion,
    krinos,
    logs,
    orchestration,
    pythia,
)
from hermes.config import settings
from hermes.db.models import LogAgent, NiveauLog
from hermes.db.session import get_engine, init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    init_db()
    # Marqueur de session uniquement en runtime réel (pas en debug/tests/reload) :
    # garantit qu'au lancement sur le poste utilisateur le journal reçoit une
    # entrée datée de la session réelle et expose la BDD résolue (issue #8).
    if not settings.debug or settings.scheduler_auto_start:
        _journaliser_demarrage()
        scheduler_global.demarrer()
    yield
    scheduler_global.arreter()


def _journaliser_demarrage() -> None:
    """Écrit une entrée `logs_agents` au démarrage du backend.

    Permet de distinguer un journal réellement vide d'un journal pointant sur
    une autre base, et prouve que la journalisation runtime fonctionne dès le
    lancement.
    """
    with Session(get_engine()) as session:
        session.add(
            LogAgent(
                agent="HERMES",
                niveau=NiveauLog.INFO,
                message=f"HERMES démarré (v{__version__}) — BDD : {settings.db_path}",
                contexte=datetime.now(UTC).isoformat(),
            )
        )
        session.commit()


app = FastAPI(
    title="HERMES — backend",
    description="API locale de l'application HERMES (veille AO).",
    version=__version__,
    lifespan=lifespan,
)

# Tauri sert le frontend depuis tauri://localhost ou http(s)://tauri.localhost
# selon le mode WebView, et Vite depuis localhost/127.0.0.1 en dev.
# On reste permissif uniquement sur localhost — aucun risque puisque le backend
# n'écoute que sur 127.0.0.1.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^(http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?|"
        r"tauri://localhost|https?://tauri\.localhost)$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(appels_offre.router)
app.include_router(argos.router)
app.include_router(krinos.router)
app.include_router(hermion.router)
app.include_router(orchestration.router)
app.include_router(logs.router)
app.include_router(pythia.router)


@app.get("/")
def root() -> dict:
    return {
        "app": "HERMES",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }

"""Point d'entrée FastAPI — backend HERMES.

À lancer :
    uvicorn hermes.main:app --host 127.0.0.1 --port 8000

Le binding sur 127.0.0.1 est volontaire : exigence sécurité du cahier des charges.
Aucun port ne doit être exposé à l'extérieur de la machine.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hermes import __version__
from hermes.agents.argos.scheduler import scheduler_global
from hermes.api import appels_offre, argos, health, hermion, krinos, pythia
from hermes.config import settings
from hermes.db.session import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    init_db()
    if not settings.debug or settings.scheduler_auto_start:
        scheduler_global.demarrer()
    yield
    scheduler_global.arreter()


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
app.include_router(pythia.router)


@app.get("/")
def root() -> dict:
    return {
        "app": "HERMES",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }

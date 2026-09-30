"""Point d'entrée FastAPI — backend HERMES.

À lancer :
    uvicorn hermes.main:app --host 127.0.0.1 --port 8000

Le binding sur 127.0.0.1 est volontaire : exigence sécurité du cahier des charges.
Aucun port ne doit être exposé à l'extérieur de la machine.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hermes import __version__, onboarding
from hermes.agents.argos.scheduler import scheduler_global
from hermes.api import (
    appels_offre,
    argos,
    concurrence,
    health,
    hermion,
    krinos,
    logs,
    orchestration,
    profil,
    pythia,
    tableau_de_bord,
)
from hermes.api import pythia as pythia_api
from hermes.config import settings
from hermes.db.models import LogAgent, NiveauLog
from hermes.db.session import get_engine, init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    init_db()
    _migrer_onboarding()
    with Session(get_engine()) as session:
        pythia_api.appliquer_modele_persiste(session)
    # Marqueur de session uniquement en runtime réel (pas en debug/tests/reload) :
    # garantit qu'au lancement sur le poste utilisateur le journal reçoit une
    # entrée datée de la session réelle et expose la BDD résolue (issue #8).
    if not settings.debug or settings.scheduler_auto_start:
        _journaliser_demarrage()
        scheduler_global.demarrer()
    yield
    scheduler_global.arreter()


def _migrer_onboarding() -> None:
    """Auto-répare le verrou d'onboarding pour les installs antérieures à 1.0.1.

    Sans ça, une mise à jour ferait croire que l'onboarding n'a jamais eu lieu
    et stopperait les collectes ARGOS.
    """
    with Session(get_engine()) as session:
        onboarding.backfill_si_deja_utilise(session)


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


@app.exception_handler(RequestValidationError)
async def _erreur_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    """422 sans l'écho de l'entrée : un NaN/Infinity reçu ne serait pas sérialisable
    en JSON (l'écho par défaut provoquerait alors un 500)."""
    detail = [{k: v for k, v in e.items() if k not in ("input", "ctx")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


# Ordre des middlewares : le dernier ajouté est le plus externe. CORS est donc
# outermost (il répond aux preflights OPTIONS), puis le contrôle du Host, puis
# la protection CSRF.

# CSRF : un POST sans corps ou en text/plain est une « simple request » que
# n'importe quel site peut émettre vers 127.0.0.1. Exiger un en-tête
# personnalisé sur toute méthode non sûre force un preflight CORS, que
# l'allowlist d'origines ci-dessous refuse aux sites tiers.
ENTETE_CLIENT = "X-Hermes-Client"
_METHODES_SURES = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def exiger_entete_client(request: Request, call_next):
    if request.method not in _METHODES_SURES and not request.headers.get(ENTETE_CLIENT):
        return JSONResponse(
            status_code=403,
            content={"detail": f"En-tête {ENTETE_CLIENT} requis (protection CSRF)"},
        )
    return await call_next(request)


# DNS rebinding : une page rebindée sur 127.0.0.1 envoie un Host étranger.
# On refuse (400) tout Host hors allowlist (`HERMES_HOTES_AUTORISES`).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hotes_autorises)

# Tauri sert le frontend depuis tauri://localhost ou http(s)://tauri.localhost
# selon le mode WebView, et Vite depuis localhost/127.0.0.1 en dev.
# Origines limitées à localhost ; pas de credentials (aucun cookie/session).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^(http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?|"
        r"tauri://localhost|https?://tauri\.localhost)$"
    ),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Content-Type", "Accept", ENTETE_CLIENT],
)

app.include_router(health.router)
app.include_router(appels_offre.router)
app.include_router(concurrence.router)
app.include_router(argos.router)
app.include_router(krinos.router)
app.include_router(hermion.router)
app.include_router(orchestration.router)
app.include_router(logs.router)
app.include_router(pythia.router)
app.include_router(profil.router)
app.include_router(tableau_de_bord.router)


@app.get("/")
def root() -> dict:
    return {
        "app": "HERMES",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }

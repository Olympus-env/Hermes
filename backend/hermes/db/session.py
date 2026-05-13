"""Gestion de la session SQLite et initialisation du schéma."""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from hermes.config import settings

# `check_same_thread` désactivé pour autoriser l'accès depuis les workers FastAPI ;
# SQLite en mode WAL gère bien la concurrence pour notre charge mono-utilisateur.
_engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Crée la BDD et toutes les tables si nécessaires + active WAL."""
    settings.ensure_dirs()
    SQLModel.metadata.create_all(_engine)
    with _engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def get_session() -> Iterator[Session]:
    """Dépendance FastAPI : fournit une session par requête."""
    with Session(_engine) as session:
        yield session


def get_engine():
    return _engine

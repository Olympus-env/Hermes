"""Gestion de la session SQLite et initialisation du schéma."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from hermes.config import settings

# `check_same_thread` désactivé pour autoriser l'accès depuis les workers FastAPI ;
# SQLite en mode WAL gère bien la concurrence pour notre charge mono-utilisateur.
_engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)


@event.listens_for(_engine, "connect")
def _configurer_connexion(dbapi_connection, _record) -> None:
    """Pragmas par connexion : SQLite les oublie à la fermeture de chaque connexion."""
    curseur = dbapi_connection.cursor()
    try:
        curseur.execute("PRAGMA foreign_keys=ON")
        curseur.execute("PRAGMA busy_timeout=5000")
        curseur.execute("PRAGMA journal_mode=WAL")
    finally:
        curseur.close()


def init_db() -> None:
    """Crée la BDD et toutes les tables si nécessaires + active WAL.

    Applique aussi les mini-migrations SQLite (ALTER TABLE ADD COLUMN) pour
    les colonnes ajoutées après la création initiale. SQLModel.create_all
    ne touche pas aux tables existantes — c'est notre filet.
    """
    settings.ensure_dirs()
    SQLModel.metadata.create_all(_engine)
    with _engine.connect() as conn:
        _migrer_colonnes(conn)
        _dedoublonner_appels_offre(conn)
        _migrer_versions_uniques(conn)
        conn.commit()


def _migrer_colonnes(conn) -> None:
    """ALTER TABLE ADD COLUMN pour les évolutions de schéma post-création."""
    migrations: list[tuple[str, str, str]] = [
        # (table, colonne, definition SQL)
        ("analyses_krinos", "scores_dimensions", "TEXT"),
        ("appels_offre", "liens_documents", "TEXT"),
    ]
    for table, colonne, definition in migrations:
        cols = {
            row[1]
            for row in conn.exec_driver_sql(f"PRAGMA table_info('{table}')").fetchall()
        }
        if colonne not in cols:
            conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {colonne} {definition}"
            )


def _dedoublonner_appels_offre(conn) -> None:
    """Dédoublonne (portail, référence) puis crée l'index unique (bases existantes).

    On garde l'AO le plus ancien de chaque groupe. Un doublon sans donnée liée
    (documents, analyses, réponses, échanges) est supprimé ; un doublon déjà
    exploité voit sa référence externe vidée (donnée conservée, contrainte
    satisfaite) plutôt que de casser des clés étrangères.
    """
    conn.exec_driver_sql(
        """
        CREATE TEMP TABLE _ao_doublons AS
        SELECT id FROM appels_offre a
        WHERE reference_externe IS NOT NULL AND id > (
            SELECT MIN(b.id) FROM appels_offre b
            WHERE b.portail_id IS a.portail_id
              AND b.reference_externe = a.reference_externe
        )
        """
    )
    lies = [
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if row[0] != "appels_offre"
        and any(
            fk[2] == "appels_offre"
            for fk in conn.exec_driver_sql(f"PRAGMA foreign_key_list('{row[0]}')").fetchall()
        )
    ]
    conn.exec_driver_sql("CREATE TEMP TABLE _ao_utilises (id INTEGER)")
    for table in lies:
        colonnes = [
            fk[3]
            for fk in conn.exec_driver_sql(f"PRAGMA foreign_key_list('{table}')").fetchall()
            if fk[2] == "appels_offre"
        ]
        for col in colonnes:
            conn.exec_driver_sql(
                f"INSERT INTO _ao_utilises SELECT {col} FROM {table} WHERE {col} IS NOT NULL"
            )
    conn.exec_driver_sql(
        "DELETE FROM appels_offre WHERE id IN (SELECT id FROM _ao_doublons) "
        "AND id NOT IN (SELECT id FROM _ao_utilises)"
    )
    conn.exec_driver_sql(
        "UPDATE appels_offre SET reference_externe = NULL "
        "WHERE id IN (SELECT id FROM _ao_doublons)"
    )
    conn.exec_driver_sql("DROP TABLE _ao_doublons")
    conn.exec_driver_sql("DROP TABLE _ao_utilises")
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_appels_offre_portail_reference "
        "ON appels_offre (portail_id, reference_externe)"
    )


def _migrer_versions_uniques(conn) -> None:
    """Contrainte unique (appel_offre_id, version) sur reponses_hermion.

    Une base créée avant la contrainte peut contenir des versions en double
    (deux /rediger simultanés) : on renumérote les doublons (le plus ancien
    garde son numéro) avant de poser l'index unique.
    """
    doublons = conn.exec_driver_sql(
        "SELECT appel_offre_id FROM reponses_hermion "
        "GROUP BY appel_offre_id, version HAVING COUNT(*) > 1"
    ).fetchall()
    for ao_id in {row[0] for row in doublons}:
        lignes = conn.exec_driver_sql(
            "SELECT id, version FROM reponses_hermion "
            "WHERE appel_offre_id = ? ORDER BY version, id",
            (ao_id,),
        ).fetchall()
        vues: set[int] = set()
        a_renumeroter: list[int] = []
        for rep_id, version in lignes:
            if version in vues:
                a_renumeroter.append(rep_id)
            else:
                vues.add(version)
        prochaine = max(vues) + 1
        for rep_id in a_renumeroter:
            conn.exec_driver_sql(
                "UPDATE reponses_hermion SET version = ? WHERE id = ?",
                (prochaine, rep_id),
            )
            prochaine += 1
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_reponses_hermion_ao_version "
        "ON reponses_hermion (appel_offre_id, version)"
    )


def get_session() -> Iterator[Session]:
    """Dépendance FastAPI : fournit une session par requête."""
    with Session(_engine) as session:
        yield session


def get_engine():
    return _engine

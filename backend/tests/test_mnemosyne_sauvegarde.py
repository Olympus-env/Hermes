"""MNEMOSYNE — sauvegarde WAL, rotation, rétention (issue #85)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hermes.config import settings
from hermes.db import retention
from hermes.db.models import (
    AppelOffre,
    Document,
    LogAgent,
    Parametre,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)
from hermes.db.sauvegarde import appliquer_rotation, lister_sauvegardes, sauvegarder_base
from hermes.db.session import get_engine
from hermes.main import app

MAINTENANT = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _ao(session: Session, ref: str, statut: StatutAO, age_jours: int = 0) -> AppelOffre:
    ao = AppelOffre(
        reference_externe=ref, url_source="http://x", titre=ref, statut=statut,
        maj_le=MAINTENANT - timedelta(days=age_jours),
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    return ao


def _integre(chemin) -> None:
    con = sqlite3.connect(chemin)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def test_sauvegarde_wal_pendant_ecritures(tmp_path):
    """Base WAL réelle avec un écrivain concurrent : copie lisible et intègre."""
    source = tmp_path / "vive.db"
    ecrivain = sqlite3.connect(source, check_same_thread=False, timeout=30)
    ecrivain.execute("PRAGMA journal_mode=WAL")
    ecrivain.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    ecrivain.commit()
    arret = threading.Event()
    demarre = threading.Event()

    def boucle():
        i = 0
        while not arret.is_set():
            ecrivain.execute("INSERT INTO t (v) VALUES (?)", ("x" * 200,))
            ecrivain.commit()
            i += 1
            if i == 50:
                demarre.set()

    fil = threading.Thread(target=boucle)
    fil.start()
    assert demarre.wait(10)
    try:
        res = sauvegarder_base(tmp_path / "sauv", conservees=7, source=source,
                               maintenant=MAINTENANT)
    finally:
        arret.set()
        fil.join()
        ecrivain.close()
    assert res.chemin.name == "hermes-20261012.db"
    _integre(res.chemin)
    con = sqlite3.connect(res.chemin)
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] > 0
    con.close()
    assert not list((tmp_path / "sauv").glob("*.tmp"))


def test_sauvegarde_base_hermes(tmp_path):
    with Session(get_engine()) as s:
        _ao(s, "A", StatutAO.BRUT)
    res = sauvegarder_base(tmp_path, conservees=7)
    _integre(res.chemin)
    con = sqlite3.connect(res.chemin)
    assert con.execute("SELECT count(*) FROM appels_offre").fetchone()[0] == 1
    con.close()


def test_rotation_garde_les_n_dernieres(tmp_path):
    for jour in range(1, 11):
        sauvegarder_base(tmp_path, conservees=3, maintenant=MAINTENANT.replace(day=jour))
    noms = [p.name for p in lister_sauvegardes(tmp_path)]
    assert noms == ["hermes-20261010.db", "hermes-20261009.db", "hermes-20261008.db"]
    (tmp_path / "autre.txt").write_text("à garder")
    assert appliquer_rotation(tmp_path, 1) == ["hermes-20261009.db", "hermes-20261008.db"]
    assert (tmp_path / "autre.txt").exists()


def test_purge_logs_30_jours():
    with Session(get_engine()) as s:
        s.add(LogAgent(agent="ARGOS", message="vieux", cree_le=MAINTENANT - timedelta(days=31)))
        s.add(LogAgent(agent="ARGOS", message="récent", cree_le=MAINTENANT - timedelta(days=29)))
        s.commit()
        assert retention.purger_logs(s, maintenant=MAINTENANT) == 1
        assert [log.message for log in s.exec(select(LogAgent)).all()] == ["récent"]


def test_archivage_rejetes_90_jours():
    with Session(get_engine()) as s:
        vieux = _ao(s, "vieux", StatutAO.REJETE, 91)
        recent = _ao(s, "recent", StatutAO.REJETE, 89)
        autre = _ao(s, "autre", StatutAO.EXPIRE, 400)
        assert retention.archiver_ao_rejetes(s, maintenant=MAINTENANT) == 1
        s.refresh(vieux), s.refresh(recent), s.refresh(autre)
        assert (vieux.archive, recent.archive, autre.archive) == (True, False, False)


def test_archivage_epargne_ao_avec_reponse_validee():
    with Session(get_engine()) as s:
        ao = _ao(s, "valide", StatutAO.REJETE, 200)
        s.add(ReponseHermion(appel_offre_id=ao.id, contenu="c", statut=StatutReponse.VALIDEE))
        s.commit()
        assert retention.archiver_ao_rejetes(s, maintenant=MAINTENANT) == 0
        assert s.exec(select(ReponseHermion)).all()


def test_liste_masque_archives_par_defaut():
    with Session(get_engine()) as s:
        ao = _ao(s, "arch", StatutAO.REJETE, 100)
        ao.archive = True
        s.add(ao)
        _ao(s, "vis", StatutAO.BRUT)
        s.commit()
    c = TestClient(app)
    assert [i["titre"] for i in c.get("/appels-offre").json()["items"]] == ["vis"]
    tout = c.get("/appels-offre?inclure_archives=true").json()
    assert tout["total"] == 2


def test_purge_documents_api():
    with Session(get_engine()) as s:
        ao = _ao(s, "rej", StatutAO.REJETE)
        actif = _ao(s, "actif", StatutAO.A_REPONDRE)
        protege = _ao(s, "prot", StatutAO.REPONDU)
        s.add(ReponseHermion(appel_offre_id=protege.id, contenu="c", statut=StatutReponse.EXPORTEE))
        fichier = settings.storage_path / "appels_offre" / str(ao.id) / "a.pdf"
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_bytes(b"12345")
        s.add(Document(appel_offre_id=ao.id, nom_fichier="a.pdf",
                       chemin_local=f"appels_offre/{ao.id}/a.pdf", taille_octets=5,
                       checksum_sha256="abc"))
        s.commit()
        ids = (ao.id, actif.id, protege.id)
    c = TestClient(app)
    r = c.post(f"/appels-offre/{ids[0]}/purger-documents")
    assert r.status_code == 200 and r.json() == {"fichiers_supprimes": 1, "octets_liberes": 5}
    assert not fichier.exists()
    with Session(get_engine()) as s:
        doc = s.exec(select(Document)).one()
        assert doc.checksum_sha256 == "abc" and doc.purge_le is not None
    assert c.post(f"/appels-offre/{ids[1]}/purger-documents").status_code == 409
    assert c.post(f"/appels-offre/{ids[2]}/purger-documents").status_code == 409
    assert c.post("/appels-offre/9999/purger-documents").status_code == 404


def test_route_sauvegarder_et_parametres(tmp_path):
    dossier = tmp_path / "mes-sauvegardes"
    with Session(get_engine()) as s:
        s.add(Parametre(cle="mnemosyne.dossier_sauvegarde", valeur=str(dossier)))
        s.add(Parametre(cle="mnemosyne.sauvegardes_conservees", valeur="2"))
        s.commit()
    c = TestClient(app)
    r = c.post("/systeme/sauvegarder")
    assert r.status_code == 200
    assert r.json()["chemin"].startswith(str(dossier))
    _integre(r.json()["chemin"])
    assert len(lister_sauvegardes(dossier)) == 1


def test_maintenance_complete(tmp_path):
    with Session(get_engine()) as s:
        s.add(Parametre(cle="mnemosyne.dossier_sauvegarde", valeur=str(tmp_path)))
        s.add(LogAgent(agent="X", message="vieux",
                       cree_le=datetime.now(UTC) - timedelta(days=40)))
        _ao(s, "r", StatutAO.REJETE, 0)
        s.commit()
        bilan = retention.maintenance_mnemosyne(s)
    assert bilan["sauvegarde"] and bilan["logs_purges"] == 1 and bilan["ao_archives"] == 0


def test_migration_colonnes_base_existante():
    """Une base antérieure (sans `archive`/`purge_le`) reçoit les colonnes au démarrage."""
    from hermes.db.session import init_db

    with get_engine().connect() as conn:
        conn.exec_driver_sql("ALTER TABLE appels_offre DROP COLUMN archive")
        conn.exec_driver_sql("ALTER TABLE documents DROP COLUMN purge_le")
        conn.commit()
    init_db()
    with get_engine().connect() as conn:
        for table, col in (("appels_offre", "archive"), ("documents", "purge_le")):
            cols = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info('{table}')")}
            assert col in cols

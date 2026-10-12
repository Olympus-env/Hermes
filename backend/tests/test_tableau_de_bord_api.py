"""Tests de GET /tableau-de-bord (agrégats de l'Accueil)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlmodel import Session, select

from hermes.db.models import (
    AnalyseKrinos,
    AppelOffre,
    LogAgent,
    ReponseHermion,
    StatutAO,
    StatutReponse,
)
from hermes.db.session import get_engine


def _ao(session: Session, n: int, statut: StatutAO, jours: float | None = None) -> AppelOffre:
    limite = datetime.now(UTC) + timedelta(days=jours) if jours is not None else None
    ao = AppelOffre(
        url_source=f"https://example.test/ao/{n}",
        reference_externe=f"REF-{n}",
        titre=f"AO {n}",
        statut=statut,
        date_limite=limite,
    )
    session.add(ao)
    session.commit()
    session.refresh(ao)
    return ao


def test_base_vide_renvoie_des_zeros():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/tableau-de-bord")
    assert r.status_code == 200
    d = r.json()
    assert (d["total_ao"], d["urgents"], d["score_eleve"], d["a_repondre"]) == (0, 0, 0, 0)
    assert d["par_statut"]["brut"] == 0 and len(d["par_statut"]) == len(StatutAO)
    assert d["reponses"]["en_attente"] == 0
    assert d["activite"] == []
    assert d["genere_le"].endswith("+00:00")


def test_compteurs_pipeline_et_reponses():
    from hermes.main import app

    with Session(get_engine()) as s:
        a = _ao(s, 1, StatutAO.ANALYSE, jours=3)  # urgent, score élevé
        b = _ao(s, 2, StatutAO.A_REPONDRE, jours=30)
        _ao(s, 3, StatutAO.BRUT, jours=-2)  # échéance passée : pas urgent
        _ao(s, 4, StatutAO.REJETE, jours=2)  # inactif : pas urgent
        _ao(s, 5, StatutAO.HORS_FILTRE)  # exclu du total
        s.add_all(
            [
                AnalyseKrinos(appel_offre_id=a.id, resume="r", score=40, justification_score="j"),
                AnalyseKrinos(
                    appel_offre_id=a.id,
                    resume="r",
                    score=82,
                    justification_score="j",
                    cree_le=datetime.now(UTC) + timedelta(seconds=5),
                ),
                AnalyseKrinos(appel_offre_id=b.id, resume="r", score=69, justification_score="j"),
                # v1 rejetée puis v2 en attente : seule la dernière compte.
                ReponseHermion(
                    appel_offre_id=a.id, version=1, contenu="x", statut=StatutReponse.REJETEE
                ),
                ReponseHermion(
                    appel_offre_id=a.id, version=2, contenu="x", statut=StatutReponse.EN_ATTENTE
                ),
                ReponseHermion(
                    appel_offre_id=b.id, version=1, contenu="x", statut=StatutReponse.VALIDEE
                ),
            ]
        )
        s.commit()

    with TestClient(app) as client:
        d = client.get("/tableau-de-bord").json()
    assert d["total_ao"] == 4
    assert d["urgents"] == 1
    assert d["score_eleve"] == 1  # 82 (dernière analyse) ; 69 < 70
    assert d["a_repondre"] == 1
    assert d["par_statut"]["hors_filtre"] == 1 and d["par_statut"]["rejete"] == 1
    assert d["reponses"]["en_attente"] == 1
    assert d["reponses"]["validee"] == 1
    assert d["reponses"]["rejetee"] == 0


def test_activite_agents_ordre_inverse_et_filtre():
    from hermes.main import app

    base = datetime.now(UTC)
    with Session(get_engine()) as s:
        s.add_all(
            [
                LogAgent(agent="ARGOS", message="a1", cree_le=base),
                LogAgent(agent="HERMES", message="démarrage", cree_le=base + timedelta(seconds=1)),
                LogAgent(agent="KRINOS", message="k1", cree_le=base + timedelta(seconds=2)),
                LogAgent(agent="HERMION", message="h1", cree_le=base + timedelta(seconds=3)),
            ]
        )
        s.commit()

    with TestClient(app) as client:
        d = client.get("/tableau-de-bord?limite_activite=2").json()
        assert [x["message"] for x in d["activite"]] == ["h1", "k1"]
        tous = client.get("/tableau-de-bord").json()["activite"]
        assert [x["agent"] for x in tous] == ["HERMION", "KRINOS", "ARGOS"]
        assert client.get("/tableau-de-bord?limite_activite=0").status_code == 422


def test_beaucoup_d_ao_actifs_et_sans_echeance():
    """Plus de 32 000 ids ne doivent pas casser la requête ; sans date_limite = non urgent."""
    from hermes.main import app

    with Session(get_engine()) as s:
        s.add_all(
            AppelOffre(url_source=f"https://example.test/{i}", reference_externe=f"B{i}",
                       titre=f"AO {i}", statut=StatutAO.ANALYSE)
            for i in range(33_000)
        )
        s.commit()
        ao = _ao(s, 999_999, StatutAO.BRUT)  # sans échéance
        s.add(AnalyseKrinos(appel_offre_id=ao.id, resume="r", score=90, justification_score="j"))
        s.commit()

    with TestClient(app) as client:
        d = client.get("/tableau-de-bord").json()
    assert d["total_ao"] == 33_001
    assert d["urgents"] == 0
    assert d["score_eleve"] == 1


# --- Parité avec l'ancienne implémentation (agrégats calculés en Python) ------------------


def _reference_python(session: Session, maintenant: datetime) -> dict:
    """Ancienne implémentation, conservée telle quelle comme référence de parité."""
    actifs = (StatutAO.BRUT, StatutAO.ANALYSE, StatutAO.A_REPONDRE, StatutAO.EN_REDACTION)

    def est_urgent(d: datetime | None) -> bool:
        if d is None:
            return False
        if d.tzinfo is None:
            d = d.replace(tzinfo=maintenant.tzinfo)
        return maintenant <= d <= maintenant + timedelta(days=7)

    echeances = session.exec(select(AppelOffre.date_limite).where(AppelOffre.statut.in_(actifs)))
    urgents = sum(1 for d in echeances.all() if est_urgent(d))

    lignes = session.exec(
        select(AnalyseKrinos.appel_offre_id, AnalyseKrinos.score)
        .join(AppelOffre, AppelOffre.id == AnalyseKrinos.appel_offre_id)
        .where(AppelOffre.statut.in_(actifs))
        .order_by(AnalyseKrinos.cree_le.desc(), AnalyseKrinos.id.desc())
    ).all()
    dernier: dict[int, float] = {}
    for ao_id, score in lignes:
        dernier.setdefault(ao_id, score)
    score_eleve = sum(1 for sc in dernier.values() if sc >= 70.0)

    reponses = {s.value: 0 for s in StatutReponse}
    derniere: dict[int, tuple[int, StatutReponse]] = {}
    for ao_id, version, statut in session.exec(
        select(ReponseHermion.appel_offre_id, ReponseHermion.version, ReponseHermion.statut)
    ).all():
        if ao_id not in derniere or version > derniere[ao_id][0]:
            derniere[ao_id] = (version, statut)
    for _, statut in derniere.values():
        reponses[StatutReponse(statut).value] += 1
    return {"urgents": urgents, "score_eleve": score_eleve, "reponses": reponses}


def _seeder_varie(session: Session, nb_ao: int, graine: int = 76) -> None:
    """Base variée : tous statuts, échéances autour des bornes, analyses/versions multiples."""
    import random

    alea = random.Random(graine)
    statuts = list(StatutAO)
    base = datetime.now(UTC)
    for i in range(nb_ao):
        jours = alea.choice([None, -3, -0.01, 0.5, 3, 6.99, 7.01, 30])
        ao = AppelOffre(
            url_source=f"https://example.test/p/{i}",
            reference_externe=f"P{i}",
            titre=f"AO {i}",
            statut=alea.choice(statuts),
            date_limite=base + timedelta(days=jours) if jours is not None else None,
        )
        session.add(ao)
        session.flush()
        for _ in range(alea.choice([0, 0, 1, 2, 3, 5])):
            # Horodatages volontairement répétés : départage par id décroissant.
            session.add(
                AnalyseKrinos(
                    appel_offre_id=ao.id,
                    resume="r",
                    score=alea.choice([0, 40, 69.9, 70, 70.1, 95, 100]),
                    justification_score="j",
                    cree_le=base + timedelta(seconds=alea.randint(0, 3)),
                )
            )
        versions = alea.sample(range(1, 8), alea.choice([0, 0, 1, 2, 4]))  # ordre d'insertion mêlé
        for v in versions:
            session.add(
                ReponseHermion(
                    appel_offre_id=ao.id,
                    version=v,
                    contenu="x",
                    statut=alea.choice(list(StatutReponse)),
                )
            )
    session.commit()


def test_parite_avec_implementation_python():
    from hermes.main import app

    with Session(get_engine()) as s:
        _seeder_varie(s, 600)
    with TestClient(app) as client:
        d = client.get("/tableau-de-bord").json()
    with Session(get_engine()) as s:
        ref = _reference_python(s, datetime.fromisoformat(d["genere_le"]))
    assert d["urgents"] == ref["urgents"] > 0
    assert d["score_eleve"] == ref["score_eleve"] > 0
    assert d["reponses"] == ref["reponses"]
    assert sum(d["reponses"].values()) > 0


@pytest.mark.skipif(not os.environ.get("HERMES_TEST_PERF"), reason="mesure manuelle (lente)")
def test_perf_50000_ao_trois_analyses(capsys):
    """HERMES_TEST_PERF=1 pytest -s tests/test_tableau_de_bord_api.py -k perf"""
    import time

    from hermes.main import app

    n = 50_000
    base = datetime.now(UTC)
    with Session(get_engine()) as s:
        s.execute(
            insert(AppelOffre),
            [
                {
                    "url_source": f"https://example.test/perf/{i}",
                    "reference_externe": f"F{i}",
                    "titre": f"AO {i}",
                    "statut": StatutAO.ANALYSE if i % 5 else StatutAO.REJETE,
                    "date_limite": base + timedelta(days=i % 20),
                    "cree_le": base,
                    "maj_le": base,
                }
                for i in range(n)
            ],
        )
        s.execute(
            insert(AnalyseKrinos),
            [
                {
                    "appel_offre_id": i + 1,
                    "resume": "r",
                    "score": (i * 7 + k * 13) % 100,
                    "justification_score": "j",
                    "cree_le": base + timedelta(seconds=k),
                }
                for i in range(n)
                for k in range(3)
            ],
        )
        s.execute(
            insert(ReponseHermion),
            [
                {
                    "appel_offre_id": i + 1,
                    "version": v,
                    "contenu": "x",
                    "statut": StatutReponse.EN_ATTENTE,
                    "cree_le": base,
                    "maj_le": base,
                }
                for i in range(0, n, 2)
                for v in (1, 2)
            ],
        )
        s.commit()
    with TestClient(app) as client:
        client.get("/tableau-de-bord")  # chauffe
        durees = []
        for _ in range(5):
            t0 = time.perf_counter()
            r = client.get("/tableau-de-bord")
            durees.append(time.perf_counter() - t0)
    assert r.status_code == 200
    with capsys.disabled():
        print(f"\nPERF tableau-de-bord : médiane {sorted(durees)[2] * 1000:.0f} ms")

"""Non-régression issue #12 : avis ouverts uniquement, pannes signalées, doublons.

Aucun appel réseau réel : tous les clients httpx sont factices.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from hermes.agents.argos import boamp, ted
from hermes.agents.argos.base import AOCollecte, CriteresAvances, Scraper
from hermes.agents.argos.boamp import BoampScraper, _construire_where, _page_anterieure
from hermes.agents.argos.runner import executer_collecte
from hermes.agents.argos.ted import TedScraper
from hermes.agents.argos.ted import _construire_query as construire_query_ted
from hermes.db.models import AppelOffre, LogAgent, NiveauLog, Portail
from hermes.db.session import _dedoublonner_appels_offre, get_engine


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client_boamp(reponses):
    """Client factice : `reponses` = callable(params) -> payload ou lève."""

    class _C:
        appels: list[dict] = []

        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url, params=None):
            type(self).appels.append(dict(params or {}))
            return _Resp(reponses(params or {}))

    return _C


def _recs(n, date, prefixe="a"):
    return [
        {"objet": "SMS", "idweb": f"{prefixe}{date}-{i}", "url_avis": f"https://x/{prefixe}{i}",
         "dateparution": date, "nature": "APPEL_OFFRE", "etat": "INITIAL"}
        for i in range(n)
    ]


# --------------------------------------------------------------------------- #
# Avis ouverts uniquement
# --------------------------------------------------------------------------- #


def test_boamp_requete_sans_filtre_restreinte_aux_appels_initiaux(monkeypatch):
    c = _client_boamp(lambda _p: {"results": _recs(1, "2026-09-01")})
    monkeypatch.setattr(boamp.httpx, "AsyncClient", c)

    asyncio.run(BoampScraper().collecter())

    assert c.appels[0]["where"] == 'nature = "APPEL_OFFRE" AND etat = "INITIAL"'
    assert c.appels[0]["order_by"] == "dateparution desc, idweb desc"  # tri stable
    assert "nature" in c.appels[0]["select"] and "etat" in c.appels[0]["select"]


def test_boamp_le_repli_garde_la_restriction(monkeypatch):
    def reponses(p):
        if "search(" in p.get("where", ""):
            raise httpx.HTTPError("400")
        return {"results": _recs(1, "2026-09-01")}

    c = _client_boamp(reponses)
    monkeypatch.setattr(boamp.httpx, "AsyncClient", c)
    s = BoampScraper()
    s.filtre_inclus = ("SMS",)

    assert len(asyncio.run(s.collecter())) == 1
    assert 'nature = "APPEL_OFFRE"' in c.appels[-1]["where"]


def test_boamp_ecarte_attributions_et_rectificatifs_cote_client(monkeypatch):
    lot = _recs(1, "2026-09-01") + [
        {**_recs(1, "2026-09-01", "b")[0], "nature": "ATTRIBUTION"},
        {**_recs(1, "2026-09-01", "c")[0], "nature": "RECTIFICATIF", "etat": "RECTIFICATIF"},
        {**_recs(1, "2026-09-01", "d")[0], "etat": "ANNULATION"},
    ]
    monkeypatch.setattr(boamp.httpx, "AsyncClient", _client_boamp(lambda _p: {"results": lot}))

    items = asyncio.run(BoampScraper().collecter())

    assert [i.reference_externe for i in items] == ["a2026-09-01-0"]


def test_ted_query_exclut_les_avis_d_attribution():
    q = construire_query_ted(("sms",))
    assert "notice-type NOT IN (can-standard can-social can-desg can-modif veat)" in q


def test_ted_ecarte_les_notices_can_cote_client(monkeypatch):
    notices = [
        {"publication-number": "1-2026", "notice-title": "SMS", "notice-type": "cn-standard"},
        {"publication-number": "2-2026", "notice-title": "SMS", "notice-type": "can-standard"},
    ]

    class _C(_ClientTed):
        lots = [notices]

    monkeypatch.setattr(ted.httpx, "AsyncClient", _C)
    items = asyncio.run(TedScraper().collecter())
    assert [i.reference_externe for i in items] == ["1-2026"]


class _ClientTed:
    lots: list = []
    echec_page: int | None = None

    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def post(self, _url, json=None):
        page = (json or {}).get("page", 1)
        if type(self).echec_page == page:
            raise httpx.HTTPError("panne")
        idx = page - 1
        return _Resp({"notices": self.lots[idx] if idx < len(self.lots) else []})


# --------------------------------------------------------------------------- #
# Pannes = erreurs, pas des succès silencieux
# --------------------------------------------------------------------------- #


def test_boamp_panne_sans_filtre_leve(monkeypatch):
    def panne(_p):
        raise httpx.HTTPError("503")

    monkeypatch.setattr(boamp.httpx, "AsyncClient", _client_boamp(panne))
    with pytest.raises(httpx.HTTPError):
        asyncio.run(BoampScraper().collecter())


def test_boamp_panne_du_repli_leve(monkeypatch):
    def panne(_p):
        raise httpx.HTTPError("503")

    monkeypatch.setattr(boamp.httpx, "AsyncClient", _client_boamp(panne))
    s = BoampScraper()
    s.filtre_inclus = ("SMS",)
    with pytest.raises(httpx.HTTPError):
        asyncio.run(s.collecter())


def test_boamp_pagination_partielle_est_signalee(monkeypatch):
    def reponses(p):
        if p["offset"] >= 100:
            raise httpx.HTTPError("timeout")
        return {"results": _recs(100, "2026-09-01")}

    monkeypatch.setattr(boamp.httpx, "AsyncClient", _client_boamp(reponses))
    s = BoampScraper()
    s.filtre_inclus = ("SMS",)

    items = asyncio.run(s.collecter())

    assert len(items) == 100
    assert s.collecte_partielle is True


def test_ted_pagination_partielle_est_signalee(monkeypatch):
    class _C(_ClientTed):
        lots = [
            [{"publication-number": f"{i}-2026", "notice-title": "SMS",
              "publication-date": "2026-09-01"} for i in range(100)]
        ]
        echec_page = 2

    monkeypatch.setattr(ted.httpx, "AsyncClient", _C)
    s = TedScraper()

    items = asyncio.run(s.collecter())

    assert len(items) == 100
    assert s.collecte_partielle is True


def test_ted_dedoublonne_les_notices_entre_pages(monkeypatch):
    page = [{"publication-number": f"{i}-2026", "notice-title": "SMS",
             "publication-date": "2026-09-01"} for i in range(100)]

    class _C(_ClientTed):
        lots = [page, page[:10]]  # la page 2 rejoue 10 notices de la page 1

    monkeypatch.setattr(ted.httpx, "AsyncClient", _C)
    assert len(asyncio.run(TedScraper().collecter())) == 100


class _ScraperPartiel(Scraper):
    nom = "fake-partiel"
    url_base = "https://example.test"

    def __init__(self, partiel: bool):
        self._partiel = partiel

    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        self.collecte_partielle = self._partiel
        return [AOCollecte(titre="AO", url_source="https://example.test/1", reference_externe="R1")]


class _ScraperEnPanne(Scraper):
    nom = "fake-panne"
    url_base = "https://example.test"

    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        raise httpx.HTTPError("panne")


def _derniere_collecte(nom: str):
    with Session(get_engine()) as s:
        return s.exec(select(Portail).where(Portail.nom == nom)).one().derniere_collecte


@pytest.mark.asyncio
async def test_runner_panne_remonte_en_erreur_sans_avancer_la_fenetre():
    with Session(get_engine()) as s:
        res = await executer_collecte(_ScraperEnPanne(), s)
        logs = s.exec(select(LogAgent).where(LogAgent.niveau == NiveauLog.ERROR)).all()
    assert not res.succes
    assert logs
    assert _derniere_collecte("fake-panne") is None


@pytest.mark.asyncio
async def test_runner_collecte_partielle_n_avance_pas_derniere_collecte():
    with Session(get_engine()) as s:
        res = await executer_collecte(_ScraperPartiel(True), s)
    assert res.partielle and res.ao_nouveaux == 1  # avis conservés
    assert _derniere_collecte("fake-partiel") is None


@pytest.mark.asyncio
async def test_runner_collecte_complete_avance_derniere_collecte():
    with Session(get_engine()) as s:
        await executer_collecte(_ScraperPartiel(False), s)
    assert _derniere_collecte("fake-partiel") is not None


# --------------------------------------------------------------------------- #
# Doublons : index unique + migration
# --------------------------------------------------------------------------- #


def _ao(portail_id, ref, url):
    return AppelOffre(portail_id=portail_id, reference_externe=ref, url_source=url, titre="t")


def test_index_unique_portail_reference():
    with Session(get_engine()) as s:
        p = Portail(nom="p", url_base="https://p")
        s.add(p)
        s.commit()
        s.add(_ao(p.id, "R1", "https://a"))
        s.commit()
        s.add(_ao(p.id, "R1", "https://b"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        # NULL non contraint
        s.add(_ao(p.id, None, "https://c"))
        s.add(_ao(p.id, None, "https://d"))
        s.commit()


@pytest.mark.asyncio
async def test_runner_ignore_un_doublon_rejete_par_l_index(monkeypatch):
    from hermes.agents.argos import runner

    with Session(get_engine()) as s:
        p = Portail(nom="fake-partiel", url_base="https://example.test")
        s.add(p)
        s.commit()
        s.add(_ao(p.id, "R1", "https://autre-url"))
        s.commit()
        # `_existe` ne voit pas le doublon (collecte concurrente) → l'index tranche.
        monkeypatch.setattr(runner, "_existe", lambda *_a, **_k: False)
        res = await executer_collecte(_ScraperPartiel(False), s)
        assert res.succes and res.ao_nouveaux == 0 and res.ao_dedoublonnes == 1
        assert len(s.exec(select(AppelOffre)).all()) == 1


def test_migration_dedoublonne_les_bases_existantes():
    engine = get_engine()
    with Session(engine) as s:
        p = Portail(nom="p", url_base="https://p")
        s.add(p)
        s.commit()
        pid = p.id
    with engine.connect() as conn:
        conn.exec_driver_sql("DROP INDEX uq_appels_offre_portail_reference")
        for ref, url in (
            [("R1", "u1"), ("R1", "u2"), ("R1", "u3"), ("R2", "u4"), (None, "u5")]
        ):
            conn.exec_driver_sql(
                "INSERT INTO appels_offre (portail_id, reference_externe, url_source, titre, "
                "devise, statut, cree_le, maj_le) VALUES (?, ?, ?, 't', 'EUR', 'BRUT',"
                "'2026-01-01', '2026-01-01')",
                (pid, ref, url),
            )
        # Le 2e doublon porte des données liées : il doit être conservé (réf. vidée).
        conn.exec_driver_sql(
            "INSERT INTO documents (appel_offre_id, nom_fichier, chemin_local, type, "
            "taille_octets, checksum_sha256, cree_le) SELECT id, 'f', '/f', 'autre', 1, 'x', "
            "'2026-01-01' FROM appels_offre WHERE url_source = 'u2'"
        )
        conn.commit()

    with engine.connect() as conn:
        _dedoublonner_appels_offre(conn)
        conn.commit()

    with Session(engine) as s:
        refs = sorted(
            (a.url_source, a.reference_externe) for a in s.exec(select(AppelOffre)).all()
        )
    # u3 (doublon nu) supprimé ; u2 (avec document) conservé mais sans référence.
    assert refs == [("u1", "R1"), ("u2", None), ("u4", "R2"), ("u5", None)]


# --------------------------------------------------------------------------- #
# Pagination sans date, échappement, validation
# --------------------------------------------------------------------------- #


def test_page_anterieure_sans_date_ne_boucle_pas():
    borne = datetime(2026, 9, 1, tzinfo=UTC)
    assert _page_anterieure([{"idweb": "1"}, {"idweb": "2"}], borne) is True
    # date manquante en fin de page : on juge sur le dernier enregistrement daté
    assert _page_anterieure(
        [{"dateparution": "2026-09-10"}, {"idweb": "2"}], borne
    ) is False


def test_ted_page_anterieure_sans_date():
    borne = datetime(2026, 9, 1, tzinfo=UTC)
    assert ted._page_anterieure([{"publication-number": "1"}], borne) is True


def test_where_boamp_echappe_l_antislash():
    where = _construire_where(("a\\b",), ())
    assert where == '(search(objet, "a\\\\b"))'


def test_where_boamp_ignore_departements_invalides():
    c = CriteresAvances(departements=('75" OR 1=1 --', "2A", "75"))
    where = _construire_where((), (), c)
    assert where == '(code_departement = "2A" OR code_departement = "75")'


def test_query_ted_ignore_pays_invalides():
    q = construire_query_ted((), CriteresAvances(pays=("FRA", "F) OR (x", "fr")))
    assert q.startswith("place-of-performance IN (FRA) AND")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


def test_api_limite_bornee():
    from hermes.main import app

    with TestClient(app) as client:
        assert client.post("/argos/collecter/boamp?limite=0").status_code == 422
        assert client.post("/argos/collecter/boamp?limite=101").status_code == 422
        assert client.post("/argos/collecter?limite=1000").status_code == 422


def test_api_filtre_rejette_pays_et_departement_invalides():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.put("/argos/filtre", json={"avance": {"pays": ["FRANCE"]}})
        assert r.status_code == 422
        r = client.put("/argos/filtre", json={"avance": {"departements": ['75"']}})
        assert r.status_code == 422
        r = client.put("/argos/filtre", json={"avance": {"pays": ["fra"], "departements": ["2a"]}})
        assert r.status_code == 200
        assert r.json()["avance"]["pays"] == ["FRA"]
        assert r.json()["avance"]["departements"] == ["2A"]


def test_api_put_portail_partiel_ne_reactive_pas():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.put(
            "/argos/portails/boamp",
            json={"url_base": "https://www.boamp.fr", "actif": False, "frequence_minutes": 60},
        )
        assert r.status_code == 200 and r.json()["actif"] is False
        r = client.put("/argos/portails/boamp", json={"url_base": "https://www.boamp.fr"})
        assert r.status_code == 200
        assert r.json()["actif"] is False  # champ omis : inchangé
        assert r.json()["frequence_minutes"] == 60

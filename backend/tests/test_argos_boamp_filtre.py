"""Tests du filtrage côté serveur BOAMP (requête ODSQL + repli)."""

from __future__ import annotations

import asyncio

import httpx

from hermes.agents.argos import boamp
from hermes.agents.argos.boamp import BoampScraper, _construire_where


def test_where_inclus_seuls():
    where = _construire_where(("SMS", "RCS"), ())
    assert where == '("SMS" OR "RCS")'


def test_where_inclus_et_exclus():
    where = _construire_where(("SMS",), ("nettoyage", "voirie"))
    assert where == '("SMS") AND NOT ("nettoyage" OR "voirie")'


def test_where_sans_inclus_est_none():
    assert _construire_where((), ("nettoyage",)) is None


def test_where_echappe_les_guillemets():
    where = _construire_where(('SMS "premium"',), ())
    assert '"' not in where.replace('("', "").replace('")', "")  # plus de guillemets internes
    assert "premium" in where


def _record(objet: str = "Marché d'envoi de SMS de notification"):
    return {"objet": objet, "idweb": "ABC123", "url_avis": "https://boamp.fr/x"}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _ClientReposFiltre:
    """Simule une API qui REJETTE la requête filtrée mais accepte la requête nue."""

    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def get(self, _url, params=None):
        if params and "where" in params:
            raise httpx.HTTPError("400 — clause where rejetée")
        return _Resp({"results": [_record()]})


def test_collecte_filtree_replie_sur_collecte_nue(monkeypatch):
    monkeypatch.setattr(boamp.httpx, "AsyncClient", _ClientReposFiltre)
    scraper = BoampScraper()
    scraper.filtre_inclus = ("SMS", "RCS")

    items = asyncio.run(scraper.collecter(limite=20))

    # Le filtre a échoué côté API mais le repli a ramené des avis.
    assert len(items) == 1
    assert "SMS" in items[0].titre


class _ClientOk:
    captured: dict = {}

    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def get(self, _url, params=None):
        type(self).captured = dict(params or {})
        return _Resp({"results": [_record()]})


def test_collecte_avec_filtre_envoie_le_where(monkeypatch):
    monkeypatch.setattr(boamp.httpx, "AsyncClient", _ClientOk)
    scraper = BoampScraper()
    scraper.filtre_inclus = ("SMS",)
    scraper.filtre_exclus = ("nettoyage",)

    asyncio.run(scraper.collecter(limite=20))

    assert _ClientOk.captured.get("where") == '("SMS") AND NOT ("nettoyage")'

"""Tests de la pagination incrémentale des collectes ARGOS (BOAMP, TED)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from hermes.agents.argos import boamp, ted
from hermes.agents.argos.base import MARGE_INCREMENTALE, borne_incrementale
from hermes.agents.argos.boamp import BoampScraper
from hermes.agents.argos.ted import TedScraper

# --------------------------------------------------------------------------- #
# Borne incrémentale
# --------------------------------------------------------------------------- #


def test_borne_none_a_la_premiere_collecte():
    assert borne_incrementale(None) is None


def test_borne_applique_la_marge():
    depuis = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)
    assert borne_incrementale(depuis) == depuis - MARGE_INCREMENTALE


# --------------------------------------------------------------------------- #
# Réponse factice + mock httpx paginé
# --------------------------------------------------------------------------- #


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _boamp_records(n: int, date: str) -> list[dict]:
    return [
        {"objet": "SMS", "idweb": f"{date}-{i}", "url_avis": f"https://x/{date}/{i}",
         "dateparution": date}
        for i in range(n)
    ]


def _ted_notices(n: int, date: str) -> list[dict]:
    return [
        {"publication-number": f"{date}-{i}", "notice-title": "SMS",
         "publication-date": date}
        for i in range(n)
    ]


class _ClientBoampPages:
    """Sert des lots BOAMP selon l'offset ; enregistre les offsets demandés."""

    lots: list[list[dict]] = []
    offsets: list[int] = []

    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def get(self, _url, params=None):
        offset = (params or {}).get("offset", 0)
        type(self).offsets.append(offset)
        idx = offset // 100
        lot = self.lots[idx] if idx < len(self.lots) else []
        return _Resp({"results": lot})


def test_boamp_pagine_jusqua_page_partielle(monkeypatch):
    _ClientBoampPages.lots = [
        _boamp_records(100, "2026-06-18"),
        _boamp_records(100, "2026-06-17"),
        _boamp_records(5, "2026-06-16"),
    ]
    _ClientBoampPages.offsets = []
    monkeypatch.setattr(boamp.httpx, "AsyncClient", _ClientBoampPages)

    scraper = BoampScraper()
    scraper.filtre_inclus = ("SMS",)  # active la pagination
    scraper.depuis = None  # première collecte → pas de borne

    items = asyncio.run(scraper.collecter())

    assert len(items) == 205  # 100 + 100 + 5
    assert _ClientBoampPages.offsets == [0, 100, 200]  # arrêt sur page partielle


def test_boamp_sarrete_sur_la_borne_incrementale(monkeypatch):
    # Page 0 récente (>= borne), page 1 ancienne (< borne) → on ne demande pas
    # la page 2 même si elle existe.
    _ClientBoampPages.lots = [
        _boamp_records(100, "2026-06-18"),
        _boamp_records(100, "2026-06-01"),
        _boamp_records(100, "2026-05-20"),
    ]
    _ClientBoampPages.offsets = []
    monkeypatch.setattr(boamp.httpx, "AsyncClient", _ClientBoampPages)

    scraper = BoampScraper()
    scraper.filtre_inclus = ("SMS",)
    scraper.depuis = datetime(2026, 6, 17, tzinfo=UTC)  # borne = 2026-06-15

    items = asyncio.run(scraper.collecter())

    assert _ClientBoampPages.offsets == [0, 100]  # page 2 jamais demandée
    assert len(items) == 200


class _ClientTedPages:
    lots: list[list[dict]] = []
    pages: list[int] = []

    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def post(self, _url, json=None):
        page = (json or {}).get("page", 1)
        type(self).pages.append(page)
        idx = page - 1
        lot = self.lots[idx] if idx < len(self.lots) else []
        return _Resp({"notices": lot})


def test_ted_sarrete_sur_la_borne_incrementale(monkeypatch):
    _ClientTedPages.lots = [
        _ted_notices(100, "2026-06-18"),
        _ted_notices(100, "2026-06-01"),
        _ted_notices(100, "2026-05-20"),
    ]
    _ClientTedPages.pages = []
    monkeypatch.setattr(ted.httpx, "AsyncClient", _ClientTedPages)

    scraper = TedScraper()
    scraper.filtre_inclus = ("SMS",)
    scraper.depuis = datetime.now(UTC) - timedelta(days=1)

    items = asyncio.run(scraper.collecter())

    assert _ClientTedPages.pages == [1, 2]  # page 3 jamais demandée
    assert len(items) == 200

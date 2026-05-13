"""Tests du runner ARGOS (persistance MNEMOSYNE, dédoublonnage).

Utilise un scraper « fake » qui renvoie une liste statique d'AOCollecte —
pas d'appel réseau ni de Playwright.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from hermes.agents.argos.base import AOCollecte, Scraper
from hermes.agents.argos.runner import executer_collecte
from hermes.db.models import AppelOffre, LogAgent, Portail, StatutAO
from hermes.db.session import get_engine, init_db
from hermes.securite.credentials import chiffrer_credentials


class FakeScraper(Scraper):
    nom = "fake-portail"
    url_base = "https://example.test"

    def __init__(self, items: list[AOCollecte]):
        self._items = items

    async def collecter(self, limite: int = 20) -> list[AOCollecte]:
        return self._items[:limite]


def _exemple_items() -> list[AOCollecte]:
    return [
        AOCollecte(
            titre="Marché test 1",
            url_source="https://example.test/avis/1",
            reference_externe="TST-001",
            emetteur="Ville fictive",
            date_limite=datetime(2026, 9, 1, tzinfo=timezone.utc),
        ),
        AOCollecte(
            titre="Marché test 2",
            url_source="https://example.test/avis/2",
            reference_externe="TST-002",
            emetteur="Région fictive",
        ),
    ]


@pytest.mark.asyncio
async def test_collecte_insere_nouveaux():
    init_db()
    scraper = FakeScraper(_exemple_items())
    with Session(get_engine()) as s:
        res = await executer_collecte(scraper, s)

    assert res.succes
    assert res.ao_trouves == 2
    assert res.ao_nouveaux == 2
    assert res.ao_dedoublonnes == 0
    assert res.duree_ms >= 0

    with Session(get_engine()) as s:
        aos = s.exec(
            select(AppelOffre).where(AppelOffre.reference_externe.in_(["TST-001", "TST-002"]))
        ).all()
        assert len(aos) == 2
        assert all(ao.statut == StatutAO.BRUT for ao in aos)


@pytest.mark.asyncio
async def test_collecte_dedoublonne():
    init_db()
    scraper = FakeScraper(_exemple_items())

    with Session(get_engine()) as s:
        await executer_collecte(scraper, s)
    with Session(get_engine()) as s:
        res2 = await executer_collecte(scraper, s)

    assert res2.ao_nouveaux == 0
    assert res2.ao_dedoublonnes == 2


@pytest.mark.asyncio
async def test_portail_cree_automatiquement():
    init_db()
    scraper = FakeScraper(_exemple_items())
    with Session(get_engine()) as s:
        await executer_collecte(scraper, s)

    with Session(get_engine()) as s:
        portail = s.exec(select(Portail).where(Portail.nom == "fake-portail")).first()
        assert portail is not None
        assert portail.actif is True
        assert portail.derniere_collecte is not None


@pytest.mark.asyncio
async def test_erreur_journalisee():
    init_db()

    class ScraperKO(Scraper):
        nom = "scraper-ko"
        url_base = "https://ko.test"

        async def collecter(self, limite: int = 20) -> list[AOCollecte]:
            raise RuntimeError("boom")

    with Session(get_engine()) as s:
        res = await executer_collecte(ScraperKO(), s)

    assert not res.succes
    assert "boom" in res.erreurs[0]

    with Session(get_engine()) as s:
        logs = s.exec(
            select(LogAgent).where(LogAgent.agent == "ARGOS").order_by(LogAgent.id.desc())
        ).all()
        assert logs and "boom" in logs[0].message


@pytest.mark.asyncio
async def test_collecte_injecte_credentials_chiffres():
    init_db()

    class ScraperPrive(FakeScraper):
        nom = "portail-prive"

        def __init__(self):
            super().__init__(_exemple_items())
            self.credentials: dict[str, str] = {}

        async def collecter(self, limite: int = 20) -> list[AOCollecte]:
            assert self.credentials == {"login": "demo", "password": "secret"}
            return await super().collecter(limite)

    with Session(get_engine()) as s:
        portail = Portail(
            nom="portail-prive",
            url_base="https://prive.example.test",
            credentials_chiffres=chiffrer_credentials({"login": "demo", "password": "secret"}),
        )
        s.add(portail)
        s.commit()

        res = await executer_collecte(ScraperPrive(), s)

    assert res.succes
    assert res.ao_nouveaux == 2

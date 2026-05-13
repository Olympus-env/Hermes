"""Socle ARGOS pour portails privés nécessitant une session Playwright."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from hermes.agents.argos.base import Scraper


class ScraperPlaywrightAuthentifie(Scraper):
    """Base réutilisable pour les portails privés avec authentification.

    Les scrapers concrets reçoivent leurs credentials au constructeur. Ils
    implémentent `se_connecter` avec les sélecteurs propres au portail, puis
    utilisent `page_connectee` pour collecter les AO.
    """

    def __init__(self, credentials: dict[str, str] | None = None, headless: bool = True):
        self.credentials = credentials or {}
        self.headless = headless

    @abstractmethod
    async def se_connecter(self, page: Page) -> None:
        """Effectue le login sur le portail cible."""
        raise NotImplementedError

    @asynccontextmanager
    async def page_connectee(self) -> AsyncIterator[Page]:
        """Ouvre Chromium, crée une page, lance le login, puis nettoie."""
        async with async_playwright() as p:
            browser: Browser = await p.chromium.launch(headless=self.headless)
            context: BrowserContext = await browser.new_context()
            page = await context.new_page()
            try:
                await self.se_connecter(page)
                yield page
            finally:
                await context.close()
                await browser.close()

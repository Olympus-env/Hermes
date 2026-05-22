"""Test de la sérialisation des inférences PYTHIA (issue #4).

Ollama traite les requêtes une à une ; le module doit garantir qu'au plus
`pythia_concurrence_max` inférences sont en vol simultanément, même quand
plusieurs analyses KRINOS/HERMION sont lancées en parallèle.
"""

from __future__ import annotations

import asyncio

import pytest

from hermes.agents import pythia


class _FauxReponse:
    def raise_for_status(self) -> None:  # noqa: D401
        return None

    def json(self) -> dict:
        return {"response": "ok", "total_duration": 1_000_000}


class _ClientConcurrenceTraquee:
    """Faux httpx.AsyncClient mesurant le pic de requêtes simultanées."""

    en_vol = 0
    pic = 0

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self) -> _ClientConcurrenceTraquee:
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def post(self, *_args, **_kwargs) -> _FauxReponse:
        type(self).en_vol += 1
        type(self).pic = max(type(self).pic, type(self).en_vol)
        try:
            await asyncio.sleep(0.02)
            return _FauxReponse()
        finally:
            type(self).en_vol -= 1


@pytest.mark.asyncio
async def test_inferences_serialisees(monkeypatch):
    monkeypatch.setattr(pythia.httpx, "AsyncClient", _ClientConcurrenceTraquee)
    # Réinitialise le verrou pour la boucle courante afin de prendre la valeur
    # de concurrence par défaut (1).
    pythia._verrous.clear()
    _ClientConcurrenceTraquee.pic = 0
    _ClientConcurrenceTraquee.en_vol = 0

    await asyncio.gather(*(pythia.generer(f"prompt {i}") for i in range(8)))

    assert _ClientConcurrenceTraquee.pic == 1

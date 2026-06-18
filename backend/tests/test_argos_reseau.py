"""Tests du helper réseau partagé ARGOS (retry/backoff, Retry-After)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from hermes.agents.argos import reseau
from hermes.agents.argos.reseau import (
    _delai_backoff,
    _delai_retry_after,
    requeter_avec_retry,
)


@pytest.fixture(autouse=True)
def _pas_de_vraie_pause(monkeypatch):
    """Neutralise les pauses : on capture les délais sans dormir."""
    delais: list[float] = []

    async def _fake(delai: float) -> None:
        delais.append(delai)

    monkeypatch.setattr(reseau, "_attendre", _fake)
    return delais


def _reponse(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code=status, headers=headers or {})


def _envoyeur(sequence):
    """Factory `envoyer` qui débite une séquence d'éléments.

    Un élément `Exception` est levé, sinon il est renvoyé comme réponse.
    """
    it = iter(sequence)

    async def envoyer() -> httpx.Response:
        element = next(it)
        if isinstance(element, Exception):
            raise element
        return element

    return envoyer


def test_succes_immediat_aucune_pause(_pas_de_vraie_pause):
    envoyer = _envoyeur([_reponse(200)])
    r = asyncio.run(requeter_avec_retry(envoyer, base_delai=0.01))
    assert r.status_code == 200
    assert _pas_de_vraie_pause == []  # aucun retry


def test_retry_sur_503_puis_succes(_pas_de_vraie_pause):
    envoyer = _envoyeur([_reponse(503), _reponse(200)])
    r = asyncio.run(requeter_avec_retry(envoyer, base_delai=0.01))
    assert r.status_code == 200
    assert len(_pas_de_vraie_pause) == 1  # une seule pause avant le succès


def test_retry_sur_timeout_puis_succes(_pas_de_vraie_pause):
    envoyer = _envoyeur([httpx.ConnectTimeout("timeout"), _reponse(200)])
    r = asyncio.run(requeter_avec_retry(envoyer, base_delai=0.01))
    assert r.status_code == 200
    assert len(_pas_de_vraie_pause) == 1


def test_epuisement_releve_la_derniere_exception():
    envoyer = _envoyeur(
        [httpx.ConnectError("x"), httpx.ConnectError("y"), httpx.ConnectError("z")]
    )
    with pytest.raises(httpx.ConnectError):
        asyncio.run(requeter_avec_retry(envoyer, max_tentatives=3, base_delai=0.01))


def test_4xx_definitif_ne_declenche_pas_de_retry(_pas_de_vraie_pause):
    # 400 : requête malformée — inutile d'insister, on rend la réponse telle quelle.
    envoyer = _envoyeur([_reponse(400)])
    r = asyncio.run(requeter_avec_retry(envoyer, base_delai=0.01))
    assert r.status_code == 400
    assert _pas_de_vraie_pause == []


def test_503_persistant_rend_la_derniere_reponse(_pas_de_vraie_pause):
    # Après épuisement sur un code transitoire, on renvoie la dernière réponse
    # (l'appelant fera raise_for_status / repli).
    envoyer = _envoyeur([_reponse(503), _reponse(503), _reponse(503)])
    r = asyncio.run(requeter_avec_retry(envoyer, max_tentatives=3, base_delai=0.01))
    assert r.status_code == 503
    assert len(_pas_de_vraie_pause) == 2  # 2 pauses pour 3 tentatives


def test_retry_after_secondes_prioritaire_sur_backoff(_pas_de_vraie_pause):
    envoyer = _envoyeur([_reponse(429, {"Retry-After": "5"}), _reponse(200)])
    asyncio.run(requeter_avec_retry(envoyer, base_delai=0.01))
    assert _pas_de_vraie_pause == [5.0]


def test_delai_retry_after_secondes():
    assert _delai_retry_after(_reponse(429, {"Retry-After": "12"})) == 12.0


def test_delai_retry_after_plafonne():
    # 9999 s serait absurde pour une collecte : on plafonne.
    assert _delai_retry_after(_reponse(429, {"Retry-After": "9999"})) == 60.0


def test_delai_retry_after_absent_ou_invalide():
    assert _delai_retry_after(_reponse(429)) is None
    assert _delai_retry_after(_reponse(429, {"Retry-After": "soon"})) is None


def test_delai_backoff_borne_et_croissant():
    plafond = 30.0
    for tentative in range(1, 6):
        d = _delai_backoff(tentative, base=1.0, plafond=plafond)
        assert 0.0 <= d <= plafond

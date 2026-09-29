"""Tests issue #30 — PYTHIA : moteurs LLM interchangeables (ollama / openai_compatible)."""

from __future__ import annotations

import asyncio

import pytest

from hermes.agents import pythia
from hermes.config import settings


class _FauxClient:
    """Faux httpx.AsyncClient : capture (url, payload) et renvoie `reponse`."""

    appels: list[tuple[str, dict | None]] = []
    reponse: dict = {}

    def __init__(self, *_a, **_k) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def post(self, url, json=None, **_k):  # noqa: A002
        type(self).appels.append((url, json))
        outer = type(self)

        class _R:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return outer.reponse

        return _R()

    async def get(self, url, **_k):
        type(self).appels.append((url, None))
        outer = type(self)

        class _R:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return outer.reponse

        return _R()


@pytest.fixture
def faux(monkeypatch):
    _FauxClient.appels = []
    _FauxClient.reponse = {}
    monkeypatch.setattr(pythia.httpx, "AsyncClient", _FauxClient)
    return _FauxClient


@pytest.fixture
def openai(monkeypatch, faux):
    monkeypatch.setattr(settings, "pythia_moteur", "openai_compatible")
    monkeypatch.setattr(settings, "pythia_url", "http://127.0.0.1:8080/v1")
    faux.reponse = {
        "choices": [{"message": {"content": '{"a": 1}'}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5},
    }
    return faux


SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


def test_parametres_neutres_traduits_pour_ollama(faux):
    faux.reponse = {"response": "ok", "total_duration": 1_000_000}
    asyncio.run(
        pythia.generer("p", format_schema=SCHEMA, max_tokens=900, contexte=4096, raisonnement=True)
    )
    url, payload = faux.appels[0]
    assert url.endswith("/api/generate")
    assert payload["options"]["num_predict"] == 900
    assert payload["options"]["num_ctx"] == 4096
    assert payload["think"] is True
    assert payload["format"] == SCHEMA


def test_alias_deprecies_options_et_think_toujours_acceptes(faux):
    faux.reponse = {"response": "ok"}
    asyncio.run(pythia.generer("p", think=False, options={"num_predict": 300, "top_k": 5}))
    payload = faux.appels[0][1]
    assert payload["options"]["num_predict"] == 300
    assert payload["options"]["top_k"] == 5
    assert payload["think"] is False


def test_ollama_expose_tokens_et_debit(faux):
    faux.reponse = {
        "response": "ok",
        "total_duration": 3_000_000_000,
        "eval_count": 100,
        "prompt_eval_count": 40,
        "eval_duration": 2_000_000_000,
    }
    rep = asyncio.run(pythia.generer("p"))
    assert (rep.tokens_entree, rep.tokens_sortie) == (40, 100)
    assert rep.tokens_par_seconde == 50.0


def test_openai_compatible_payload_json_schema(openai):
    rep = asyncio.run(
        pythia.generer(
            "question", system="sys", format_schema=SCHEMA, max_tokens=200, contexte=8192
        )
    )
    url, payload = openai.appels[0]
    assert url == "http://127.0.0.1:8080/v1/chat/completions"
    assert payload["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "question"},
    ]
    assert payload["max_tokens"] == 200
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] == SCHEMA
    # Aucune option spécifique Ollama ne fuit vers le serveur openai_compatible.
    for cle in ("options", "num_ctx", "num_predict", "keep_alive", "think", "prompt"):
        assert cle not in payload
    # JSON par défaut sans raisonnement (pythia_think_json=False).
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert rep.texte == '{"a": 1}'
    assert (rep.tokens_entree, rep.tokens_sortie) == (11, 5)


def test_openai_compatible_json_libre_et_texte(openai):
    asyncio.run(pythia.generer("p", format_json=True))
    assert openai.appels[0][1]["response_format"] == {"type": "json_object"}
    asyncio.run(pythia.generer("p"))
    payload = openai.appels[1][1]
    assert "response_format" not in payload
    assert "chat_template_kwargs" not in payload


def test_openai_compatible_retire_le_raisonnement(openai):
    openai.reponse = {"choices": [{"message": {"content": "<think>hmm</think>Bonjour"}}]}
    assert asyncio.run(pythia.generer("p")).texte == "Bonjour"


def test_openai_compatible_reponse_invalide(openai):
    openai.reponse = {"choices": []}
    with pytest.raises(pythia.ErreurPythia, match="invalide"):
        asyncio.run(pythia.generer("p"))


def test_openai_compatible_embeddings_et_modeles(openai):
    openai.reponse = {"data": [{"embedding": [0.5, 1]}]}
    assert asyncio.run(pythia.embeddings("t")) == [0.5, 1.0]
    assert openai.appels[0][0].endswith("/v1/embeddings")
    openai.reponse = {"data": [{"id": "hf.co/org/repo:Q4_K_M"}]}
    assert asyncio.run(pythia.modele_installe("hf.co/org/repo:Q4_K_M")) is True
    assert asyncio.run(pythia.modele_installe("hf.co/org/repo:Q8_0")) is False


def test_modele_hf_via_ollama(faux):
    faux.reponse = {"models": [{"name": "hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M"}]}
    assert asyncio.run(pythia.modele_installe("hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M")) is True
    assert asyncio.run(pythia.modele_installe("hf.co/unsloth/Qwen3-8B-GGUF:Q8_0")) is False


@pytest.mark.parametrize(
    "url", ["http://192.168.1.5:8080/v1", "https://api.exemple.fr/v1", "http://0.0.0.0:8080/v1"]
)
def test_url_non_loopback_refusee(monkeypatch, faux, url):
    monkeypatch.setattr(settings, "pythia_moteur", "openai_compatible")
    monkeypatch.setattr(settings, "pythia_url", url)
    with pytest.raises(pythia.ErreurPythia, match="local"):
        asyncio.run(pythia.generer("p"))
    assert faux.appels == []  # aucune requête n'est partie
    assert asyncio.run(pythia.est_disponible()) is False


def test_moteur_inconnu_erreur_explicite(monkeypatch, faux):
    monkeypatch.setattr(settings, "pythia_moteur", "cloud")
    with pytest.raises(pythia.ErreurPythia, match="inconnu"):
        asyncio.run(pythia.generer("p"))
    assert faux.appels == []


def test_telechargement_reserve_a_ollama(monkeypatch, faux):
    monkeypatch.setattr(settings, "pythia_moteur", "openai_compatible")

    async def _consommer():
        async for _ in pythia.telecharger_modele("x"):
            pass

    with pytest.raises(pythia.ErreurPythia, match="ollama"):
        asyncio.run(_consommer())


def test_moteurs_respectent_le_protocole():
    for moteur in (pythia.MoteurOllama(), pythia.MoteurOpenAICompatible()):
        for methode in ("generer", "embeddings", "est_disponible", "lister_modeles"):
            assert callable(getattr(moteur, methode))
        assert moteur.nom in pythia.MOTEURS

"""PYTHIA — client HTTP local pour le LLM (Ollama).

PYTHIA est le nom mythologique du moteur LLM utilisé par KRINOS (analyse) et
HERMION (rédaction). Le service Ollama tourne en local sur `127.0.0.1:11434` et
sert un modèle Mistral 7B Instruct quantisé Q4_K_M (et `nomic-embed-text` pour
les embeddings).

Ce module n'introduit volontairement aucune dépendance lourde : on parle à
Ollama avec `httpx` directement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from hermes.config import settings


class ErreurPythia(RuntimeError):
    """Erreur contrôlée lors d'un appel à PYTHIA / Ollama."""


@dataclass(frozen=True)
class ReponsePythia:
    texte: str
    modele: str
    duree_ms: int


def _options() -> dict[str, Any]:
    return {
        "temperature": settings.pythia_temperature,
        # Réduit la verbosité / le « bavardage » du modèle.
        "top_p": 0.9,
        "repeat_penalty": 1.1,
    }


async def generer(
    prompt: str,
    *,
    system: str | None = None,
    format_json: bool = False,
    modele: str | None = None,
    timeout: float | None = None,
) -> ReponsePythia:
    """Appelle `/api/generate` d'Ollama et renvoie la sortie textuelle.

    Si `format_json` est vrai, Ollama force le modèle à produire du JSON valide
    (mode "format": "json" supporté nativement par Ollama).
    """
    modele_utilise = modele or settings.pythia_modele
    payload: dict[str, Any] = {
        "model": modele_utilise,
        "prompt": prompt,
        "stream": False,
        "options": _options(),
    }
    if system:
        payload["system"] = system
    if format_json:
        payload["format"] = "json"

    url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
    try:
        async with httpx.AsyncClient(timeout=timeout or settings.pythia_timeout_secondes) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as exc:
        raise ErreurPythia(f"Appel PYTHIA impossible : {exc}") from exc
    except ValueError as exc:
        raise ErreurPythia(f"Réponse PYTHIA non-JSON : {exc}") from exc

    texte = data.get("response")
    if not isinstance(texte, str):
        raise ErreurPythia("Réponse PYTHIA invalide : champ 'response' manquant")

    duree_ns = int(data.get("total_duration") or 0)
    return ReponsePythia(
        texte=texte.strip(),
        modele=modele_utilise,
        duree_ms=duree_ns // 1_000_000,
    )


async def embeddings(
    texte: str,
    *,
    modele: str | None = None,
    timeout: float | None = None,
) -> list[float]:
    """Calcule l'embedding d'un texte via Ollama."""
    modele_utilise = modele or settings.pythia_modele_embeddings
    url = f"{settings.ollama_base_url.rstrip('/')}/api/embeddings"
    payload = {"model": modele_utilise, "prompt": texte}
    try:
        async with httpx.AsyncClient(timeout=timeout or settings.pythia_timeout_secondes) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as exc:
        raise ErreurPythia(f"Appel embeddings PYTHIA impossible : {exc}") from exc

    vecteur = data.get("embedding")
    if not isinstance(vecteur, list) or not vecteur:
        raise ErreurPythia("Réponse embeddings PYTHIA invalide")
    return [float(x) for x in vecteur]


async def est_disponible(timeout: float = 3.0) -> bool:
    """Vérifie qu'Ollama répond sur le tag endpoint (pour les health-checks)."""
    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            return r.status_code == 200
    except httpx.HTTPError:
        return False


def parser_json_sortie(texte: str) -> dict[str, Any]:
    """Parse une sortie LLM censée contenir du JSON, tolérant aux entourages.

    Mistral renvoie parfois le JSON encadré de ```json …``` ou précédé d'un
    préambule. On tente plusieurs stratégies avant d'abandonner.
    """
    candidat = texte.strip()
    if candidat.startswith("```"):
        # Retire l'éventuel fence ```json … ```
        candidat = candidat.strip("`")
        if candidat.lower().startswith("json"):
            candidat = candidat[4:]
        candidat = candidat.strip()

    try:
        return json.loads(candidat)
    except json.JSONDecodeError:
        pass

    debut = candidat.find("{")
    fin = candidat.rfind("}")
    if debut != -1 and fin != -1 and fin > debut:
        try:
            return json.loads(candidat[debut : fin + 1])
        except json.JSONDecodeError as exc:
            raise ErreurPythia(f"Sortie PYTHIA non-JSON : {exc}") from exc

    raise ErreurPythia("Sortie PYTHIA non-JSON")

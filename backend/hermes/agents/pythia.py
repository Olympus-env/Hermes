"""PYTHIA — client HTTP local pour le LLM (moteurs interchangeables).

PYTHIA est le nom mythologique du moteur LLM utilisé par KRINOS (analyse) et
HERMION (rédaction). Deux moteurs sont disponibles, choisis par
`HERMES_PYTHIA_MOTEUR` :

- `ollama` (défaut) : service Ollama local sur `127.0.0.1:11434`, Qwen3 8B q4 par
  défaut (et `nomic-embed-text` pour les embeddings) ;
- `openai_compatible` : tout serveur local parlant `/v1/chat/completions`
  (llama.cpp `llama-server`, LM Studio, vLLM, Ollama `/v1`…), URL dans
  `HERMES_PYTHIA_URL`.

Dans les deux cas l'URL doit être une adresse loopback (invariant local-first).
Les appelants n'utilisent que des paramètres neutres (`max_tokens`, `contexte`,
`raisonnement`) ; chaque moteur les traduit dans son dialecte. Un modèle
Hugging Face GGUF se désigne, côté Ollama, par `hf.co/<org>/<repo>:<quant>`.

Ce module n'introduit volontairement aucune dépendance lourde : on parle aux
moteurs avec `httpx` directement.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from hermes.config import settings


class ErreurPythia(RuntimeError):
    """Erreur contrôlée lors d'un appel à PYTHIA / au moteur LLM."""


# Verrou de concurrence des inférences LLM, par boucle d'événements (issue #4).
# Ollama sert les requêtes séquentiellement ; sans ce garde-fou, des collectes
# ARGOS enchaînant le pipeline KRINOS/HERMION lancent plusieurs inférences en
# parallèle qui s'empilent, allongent les temps de réponse et déclenchent des
# timeouts. On les sérialise (concurrence configurable, 1 par défaut).
_verrous: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def _verrou_inference() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    verrou = _verrous.get(loop)
    if verrou is None:
        verrou = asyncio.Semaphore(max(1, settings.pythia_concurrence_max))
        _verrous[loop] = verrou
    return verrou


@dataclass(frozen=True)
class ReponsePythia:
    texte: str
    modele: str
    duree_ms: int
    # Mesures optionnelles (banc d'essai) : None quand le moteur ne les fournit pas.
    tokens_entree: int | None = None
    tokens_sortie: int | None = None
    duree_generation_ms: int | None = None

    @property
    def tokens_par_seconde(self) -> float | None:
        if not self.tokens_sortie:
            return None
        duree = self.duree_generation_ms or self.duree_ms
        return round(self.tokens_sortie / (duree / 1000), 1) if duree > 0 else None


# Qwen3 « réfléchit » avant de répondre ; selon la version d'Ollama, le raisonnement
# arrive dans un champ `thinking` séparé ou en tête de `response` entre balises.
_RE_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def retirer_raisonnement(texte: str) -> str:
    """Retire les blocs `<think>…</think>` (et un bloc non refermé en tête)."""
    texte = _RE_THINK.sub("", texte)
    # Bloc tronqué (num_predict atteint pendant la réflexion) ou balise orpheline.
    if "</think>" in texte:
        texte = texte.rsplit("</think>", 1)[1]
    elif texte.lstrip().lower().startswith("<think>"):
        texte = ""
    return texte.strip()


MOTEURS = ("ollama", "openai_compatible")


@dataclass
class RequetePythia:
    """Requête de génération neutre, traduite ensuite par chaque moteur."""

    prompt: str
    system: str | None = None
    format_json: bool = False
    format_schema: dict[str, Any] | None = None
    modele: str = ""
    max_tokens: int | None = None
    contexte: int | None = None
    raisonnement: bool | None = None
    temperature: float | None = None
    # Options propres à Ollama (top_k, seed…) : ignorées par les autres moteurs.
    options_ollama: dict[str, Any] = field(default_factory=dict)
    timeout: float = 0.0


class MoteurLLM(Protocol):
    """Contrat d'un moteur d'inférence local derrière PYTHIA."""

    nom: str

    async def generer(self, requete: RequetePythia) -> ReponsePythia: ...

    async def embeddings(self, texte: str, modele: str, timeout: float) -> list[float]: ...

    async def est_disponible(self, timeout: float) -> bool: ...

    async def lister_modeles(self) -> list[str]: ...


def _timeout_effectif(timeout: float | None) -> float:
    return settings.pythia_timeout_secondes if timeout is None else timeout


async def _post_json(url: str, payload: dict[str, Any], timeout: float, libelle: str) -> Any:
    """POST JSON sérialisé par le verrou d'inférence, erreurs normalisées en ErreurPythia."""
    try:
        async with _verrou_inference(), httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            return r.json()
    except httpx.TimeoutException as exc:
        raise ErreurPythia(
            f"Timeout {libelle} après {timeout:.0f}s ({type(exc).__name__})"
        ) from exc
    except httpx.HTTPStatusError as exc:
        # Le corps de l'erreur (ex. « modèle introuvable ») est le détail utile.
        corps = exc.response.text.strip()[:300]
        raise ErreurPythia(
            f"Appel {libelle} impossible : {exc}{' — ' + corps if corps else ''}"
        ) from exc
    except httpx.HTTPError as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise ErreurPythia(f"Appel {libelle} impossible : {detail}") from exc
    except ValueError as exc:
        raise ErreurPythia(f"Réponse {libelle} non-JSON : {exc}") from exc


class MoteurOllama:
    """Moteur Ollama natif (`/api/generate`, `/api/embeddings`, `/api/tags`)."""

    nom = "ollama"

    def _base(self) -> str:
        return settings.ollama_base_url.rstrip("/")

    def _options(self, r: RequetePythia) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": settings.pythia_temperature if r.temperature is None else r.temperature,
            # Sans num_ctx, Ollama applique son défaut (2-4k tokens) et tronque
            # silencieusement le prompt KRINOS (issue #16).
            "num_ctx": r.contexte or settings.pythia_num_ctx,
            # Réduit la verbosité / le « bavardage » du modèle.
            "top_p": 0.9,
            "repeat_penalty": 1.1,
        }
        if r.max_tokens is not None:
            options["num_predict"] = r.max_tokens
        options.update(r.options_ollama)
        return options

    def construire_payload(self, r: RequetePythia) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": r.modele,
            "prompt": r.prompt,
            "stream": False,
            "options": self._options(r),
        }
        if r.system:
            payload["system"] = r.system
        if r.format_schema is not None:
            payload["format"] = r.format_schema
        elif r.format_json:
            payload["format"] = "json"
        if r.raisonnement is not None:
            payload["think"] = r.raisonnement
        if settings.pythia_keep_alive:
            payload["keep_alive"] = settings.pythia_keep_alive
        return payload

    async def generer(self, requete: RequetePythia) -> ReponsePythia:
        data = await _post_json(
            f"{self._base()}/api/generate",
            self.construire_payload(requete),
            requete.timeout,
            "Ollama",
        )
        texte = data.get("response") if isinstance(data, dict) else None
        if not isinstance(texte, str):
            raise ErreurPythia("Réponse PYTHIA invalide : champ 'response' manquant")
        eval_ns = int(data.get("eval_duration") or 0)
        return ReponsePythia(
            texte=retirer_raisonnement(texte),
            modele=requete.modele,
            duree_ms=int(data.get("total_duration") or 0) // 1_000_000,
            tokens_entree=data.get("prompt_eval_count"),
            tokens_sortie=data.get("eval_count"),
            duree_generation_ms=eval_ns // 1_000_000 or None,
        )

    async def embeddings(self, texte: str, modele: str, timeout: float) -> list[float]:
        data = await _post_json(
            f"{self._base()}/api/embeddings",
            {"model": modele, "prompt": texte},
            timeout,
            "embeddings PYTHIA",
        )
        vecteur = data.get("embedding") if isinstance(data, dict) else None
        if not isinstance(vecteur, list) or not vecteur:
            raise ErreurPythia("Réponse embeddings PYTHIA invalide")
        return [float(x) for x in vecteur]

    async def est_disponible(self, timeout: float) -> bool:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{self._base()}/api/tags")
                return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def lister_modeles(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self._base()}/api/tags")
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            raise ErreurPythia(f"Ollama indisponible : {exc}") from exc

        modeles = data.get("models", [])
        if not isinstance(modeles, list):
            return []
        return [str(m.get("name") or m.get("model") or "") for m in modeles if isinstance(m, dict)]


class MoteurOpenAICompatible:
    """Serveur local `/v1/chat/completions` (llama-server, LM Studio, vLLM, Ollama `/v1`).

    Le contexte (`contexte`) n'est pas transmis : ces serveurs le fixent au
    lancement du modèle (`llama-server -c …`). Le raisonnement est demandé via
    `chat_template_kwargs.enable_thinking` (llama.cpp, vLLM) ; les serveurs qui
    ne le connaissent pas l'ignorent.
    """

    nom = "openai_compatible"

    def _base(self) -> str:
        return verifier_url_ollama_locale(settings.pythia_url).rstrip("/")

    def construire_payload(self, r: RequetePythia) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if r.system:
            messages.append({"role": "system", "content": r.system})
        messages.append({"role": "user", "content": r.prompt})
        payload: dict[str, Any] = {
            "model": r.modele,
            "messages": messages,
            "stream": False,
            "temperature": settings.pythia_temperature if r.temperature is None else r.temperature,
            "top_p": 0.9,
        }
        if r.max_tokens is not None:
            payload["max_tokens"] = r.max_tokens
        if r.format_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "sortie", "strict": True, "schema": r.format_schema},
            }
        elif r.format_json:
            payload["response_format"] = {"type": "json_object"}
        if r.raisonnement is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": r.raisonnement}
        return payload

    async def generer(self, requete: RequetePythia) -> ReponsePythia:
        url = f"{self._base()}/chat/completions"
        debut = time.perf_counter()
        data = await _post_json(
            url, self.construire_payload(requete), requete.timeout, "serveur openai_compatible"
        )
        duree_ms = int((time.perf_counter() - debut) * 1000)
        try:
            texte = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            texte = None
        if not isinstance(texte, str):
            raise ErreurPythia("Réponse PYTHIA invalide : 'choices[0].message.content' manquant")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ReponsePythia(
            texte=retirer_raisonnement(texte),
            modele=requete.modele,
            duree_ms=duree_ms,
            tokens_entree=usage.get("prompt_tokens"),
            tokens_sortie=usage.get("completion_tokens"),
            duree_generation_ms=duree_ms,
        )

    async def embeddings(self, texte: str, modele: str, timeout: float) -> list[float]:
        data = await _post_json(
            f"{self._base()}/embeddings",
            {"model": modele, "input": texte},
            timeout,
            "embeddings openai_compatible",
        )
        try:
            vecteur = data["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError):
            vecteur = None
        if not isinstance(vecteur, list) or not vecteur:
            raise ErreurPythia("Réponse embeddings PYTHIA invalide")
        return [float(x) for x in vecteur]

    async def est_disponible(self, timeout: float) -> bool:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{self._base()}/models")
                return r.status_code == 200
        except (httpx.HTTPError, ErreurPythia):
            return False

    async def lister_modeles(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self._base()}/models")
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            raise ErreurPythia(f"Serveur openai_compatible indisponible : {exc}") from exc
        modeles = data.get("data", []) if isinstance(data, dict) else []
        return [str(m.get("id") or "") for m in modeles if isinstance(m, dict)]


def moteur_actif() -> MoteurLLM:
    """Moteur choisi par `HERMES_PYTHIA_MOTEUR` (erreur explicite si inconnu)."""
    nom = (settings.pythia_moteur or "ollama").strip().lower()
    if nom == "ollama":
        return MoteurOllama()
    if nom == "openai_compatible":
        return MoteurOpenAICompatible()
    raise ErreurPythia(
        f"Moteur PYTHIA inconnu : {settings.pythia_moteur!r} (attendu : {', '.join(MOTEURS)})"
    )


async def generer(
    prompt: str,
    *,
    system: str | None = None,
    format_json: bool = False,
    format_schema: dict[str, Any] | None = None,
    raisonnement: bool | None = None,
    max_tokens: int | None = None,
    contexte: int | None = None,
    temperature: float | None = None,
    modele: str | None = None,
    timeout: float | None = None,
    think: bool | None = None,
    options: dict[str, Any] | None = None,
) -> ReponsePythia:
    """Génère une réponse via le moteur actif et renvoie la sortie textuelle.

    Si `format_json` est vrai, le moteur force du JSON valide ; `format_schema`
    (JSON Schema, ex. Pydantic `model_json_schema()`) contraint en plus la
    structure (sorties structurées).

    Paramètres neutres, traduits par moteur : `max_tokens` (longueur maximale de
    sortie), `contexte` (fenêtre en tokens, défaut `pythia_num_ctx`),
    `raisonnement` (Qwen3 & co. : coupé par défaut pour les appels JSON, cf.
    `pythia_think_json`, laissé au modèle pour le texte libre). Les blocs
    `<think>…</think>` sont retirés de la sortie.

    `think` (alias de `raisonnement`) et `options` (`num_predict`, `num_ctx` et
    `temperature` traduits vers les paramètres neutres, le reste réservé à
    Ollama) sont DÉPRÉCIÉS : ils subsistent le temps de migrer les appelants.
    """
    options_ollama = dict(options or {})
    num_predict = options_ollama.pop("num_predict", None)
    num_ctx = options_ollama.pop("num_ctx", None)
    temp_options = options_ollama.pop("temperature", None)
    if max_tokens is None:
        max_tokens = num_predict
    if contexte is None:
        contexte = num_ctx
    if temperature is None:
        temperature = temp_options
    if raisonnement is None:
        raisonnement = think
    if raisonnement is None and (format_json or format_schema is not None):
        raisonnement = settings.pythia_think_json

    requete = RequetePythia(
        prompt=prompt,
        system=system,
        format_json=format_json,
        format_schema=format_schema,
        modele=modele or settings.pythia_modele,
        max_tokens=max_tokens,
        contexte=contexte,
        raisonnement=raisonnement,
        temperature=temperature,
        options_ollama=options_ollama,
        timeout=_timeout_effectif(timeout),
    )
    return await moteur_actif().generer(requete)


async def embeddings(
    texte: str,
    *,
    modele: str | None = None,
    timeout: float | None = None,
) -> list[float]:
    """Calcule l'embedding d'un texte via le moteur actif."""
    return await moteur_actif().embeddings(
        texte, modele or settings.pythia_modele_embeddings, _timeout_effectif(timeout)
    )


async def est_disponible(timeout: float = 3.0) -> bool:
    """Vérifie que le moteur répond (pour les health-checks)."""
    try:
        return await moteur_actif().est_disponible(timeout)
    except ErreurPythia:
        return False


async def lister_modeles() -> list[str]:
    """Retourne la liste des modèles servis par le moteur actif."""
    return await moteur_actif().lister_modeles()


async def modele_installe(nom: str | None = None) -> bool:
    """Vérifie qu'un modèle est installé localement."""
    cible = nom or settings.pythia_modele
    try:
        modeles = await lister_modeles()
    except ErreurPythia:
        return False
    # Ollama renvoie parfois "nom" pour "nom:latest". Pour les autres tags
    # explicites (ex. qwen3:8b, hf.co/org/repo:Q4_K_M), on exige le tag exact afin
    # de ne pas accepter qwen3:4b.
    if cible.endswith(":latest"):
        cible_sans_latest = cible.removesuffix(":latest")
        return any(m == cible or m == cible_sans_latest for m in modeles)
    if ":" in cible:
        return any(m == cible for m in modeles)
    return any(m == cible or m == f"{cible}:latest" for m in modeles)


async def telecharger_modele(
    nom: str | None = None,
):
    """Stream le téléchargement d'un modèle via `POST /api/pull` d'Ollama.

    Itère sur les lignes NDJSON renvoyées par Ollama. Chaque ligne est un dict
    contenant typiquement {"status": "...", "completed": N, "total": M} pendant
    le téléchargement, puis {"status": "success"} à la fin. Propre au moteur
    ollama : les serveurs openai_compatible chargent leurs modèles eux-mêmes.
    """
    if (settings.pythia_moteur or "ollama").strip().lower() != "ollama":
        raise ErreurPythia("Le téléchargement de modèle n'existe que pour le moteur ollama.")
    cible = nom or settings.pythia_modele
    url = f"{settings.ollama_base_url.rstrip('/')}/api/pull"
    payload = {"model": cible, "stream": True}

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=payload) as r:
                r.raise_for_status()
                async for ligne in r.aiter_lines():
                    if not ligne.strip():
                        continue
                    try:
                        evenement = json.loads(ligne)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(evenement, dict) and evenement.get("error"):
                        raise ErreurPythia(str(evenement["error"]))
                    yield evenement
    except httpx.HTTPError as exc:
        raise ErreurPythia(f"Téléchargement modèle {cible} : {exc}") from exc


def verifier_url_ollama_locale(url: str) -> str:
    """Retourne l'URL si elle cible une adresse loopback, sinon lève une erreur."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ErreurPythia(
            "HERMES impose un moteur PYTHIA local (127.0.0.1, localhost ou ::1)."
        )
    return url


def parser_json_sortie(texte: str) -> dict[str, Any]:
    """Parse une sortie LLM censée contenir du JSON, tolérant aux entourages.

    Le LLM renvoie parfois le JSON encadré de ```json …``` ou précédé d'un
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

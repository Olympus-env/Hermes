"""KRINOS — moteur d'inférence de Laya (ONNX Runtime + `tokenizers`, sans PyTorch).

Laya (Convai Innovations, Apache-2.0) est un modèle de décision « System 1 » :
un encodeur bidirectionnel (mmBERT-base multilingue) + une tête qui note chaque
option d'une question typée. Une séquence par question :

    [CLS] "{type} question: {instructions}" [SEP] [MASK] opt0 [MASK] opt1 … [SEP] état [SEP]

et un logit par marqueur [MASK]. `construire_sequence` reprend à l'identique la
`build_sequence` de référence (`rl_common.py`, convaiinnovations/laya, Apache-2.0),
en Python pur : le tokenizer est injecté (`Encodeur`), ce qui permet de la tester
avec un faux tokenizer, sans modèle.

Tout est local : aucun appel réseau ici. Le téléchargement (consenti) des poids
est dans `laya_modele.py`.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

TYPES_QUESTION = {"choice": 0, "score": 1, "noul": 2}
# Défauts du texte des options `noul` (comme la référence).
NOUL_FAUX_DEFAUT = "no, the statement does not hold"
NOUL_VRAI_DEFAUT = "yes, the statement holds"

# Bornes de la température de calibration (config.json du modèle : [0.5, 5.0]).
TEMPERATURE_MIN = 0.5
TEMPERATURE_MAX = 5.0

Encodeur = Callable[[str], list[int]]  # texte -> ids, SANS jetons spéciaux


class ErreurLaya(RuntimeError):
    """Laya indisponible ou inexploitable — l'analyse locale (PYTHIA) reste valable."""


class ModeleLayaAbsent(ErreurLaya):
    """Les fichiers du modèle ne sont pas (ou plus) sur le disque."""


class ModeleLayaAltere(ErreurLaya):
    """Un fichier du modèle ne correspond plus à l'empreinte épinglée : chargement refusé,
    réinstallation (avec consentement) nécessaire."""

    def __init__(self, fichiers: list[str]) -> None:
        super().__init__(
            "modèle Laya altéré, à réinstaller (empreinte SHA-256 invalide : "
            + ", ".join(fichiers)
            + ")"
        )
        self.fichiers = fichiers


@dataclass(frozen=True)
class QuestionLaya:
    """Question typée. `criteres` : choice → {clé: description} ; score → liste de
    niveaux (du pire au meilleur) ; noul → {"false": …, "true": …} (optionnel)."""

    type: str
    instructions: str
    criteres: Any = None


@dataclass(frozen=True)
class Jetons:
    """Jetons spéciaux du tokenizer (mmBERT : <bos>=CLS, <eos>=SEP, <mask>, <pad>)."""

    cls: int
    sep: int
    mask: int
    pad: int
    mask_texte: str = "<mask>"


@dataclass(frozen=True)
class SortieLaya:
    """Sortie brute (avant température) pour une question."""

    logits: list[float]  # un par option
    act_probabilite: float
    tokens: int


class MoteurLaya(Protocol):
    """Contrat du moteur : c'est ce que les tests simulent (aucun modèle en CI)."""

    def evaluer(self, etat: str, questions: dict[str, QuestionLaya]) -> dict[str, SortieLaya]: ...


# --------------------------------------------------------------------------- #
# Construction de la séquence (port de `rl_common.build_sequence`)
# --------------------------------------------------------------------------- #


def rendre_options(question: QuestionLaya) -> list[str]:
    """Textes des options dans l'ordre des indices. `noul` est toujours [faux, vrai],
    de sorte que p[1] = probabilité de « vrai »."""
    crit = question.criteres
    if question.type == "choice":
        if isinstance(crit, list):
            crit = {c: None for c in crit}
        return [k if not v else f"{k}: {v}" for k, v in (crit or {}).items()]
    if question.type == "score":
        return [f"level {i}: {c}" for i, c in enumerate(crit or [])]
    crit = crit or {}
    return [
        "false: " + (crit.get("false") or NOUL_FAUX_DEFAUT),
        "true: " + (crit.get("true") or NOUL_VRAI_DEFAUT),
    ]


def construire_sequence(
    encoder: Encodeur,
    jetons: Jetons,
    etat: str,
    question: QuestionLaya,
    max_len: int,
    head_max_len: int,
    max_option_tokens: int = 48,
) -> tuple[list[int], list[int]]:
    """Retourne (ids, positions des marqueurs [MASK] par option).

    Tête (consigne + options) bornée à `head_max_len` tokens, chaque option à
    `max_option_tokens` ; l'état prend le reste, tronqué en fin, le tout borné à
    `max_len`. Le texte « <mask> » présent dans les données est neutralisé.
    """
    masque = jetons.mask_texte
    options = rendre_options(question)
    ins = str(question.instructions).replace(masque, " ")
    tete = encoder(f"{question.type} question: {ins}")
    ids_options = [
        [jetons.mask] + encoder(" " + o.replace(masque, " "))[:max_option_tokens] for o in options
    ]
    budget = head_max_len - sum(len(o) for o in ids_options)
    if budget < 16:  # trop d'options ou trop longues : on rabote chacune à parts égales
        par_option = max(4, (head_max_len - 16) // max(1, len(ids_options)))
        ids_options = [o[:par_option] for o in ids_options]
        budget = head_max_len - sum(len(o) for o in ids_options)
    tete = tete[: max(8, budget)]
    ids = [jetons.cls] + tete + [jetons.sep]
    marqueurs: list[int] = []
    for o in ids_options:
        marqueurs.append(len(ids))
        ids.extend(o)
    ids.append(jetons.sep)
    place = max(0, max_len - len(ids) - 1)
    ids_etat = encoder(etat.replace(masque, " "))[:place]
    ids = ids + ids_etat + [jetons.sep]
    return ids[:max_len], [m for m in marqueurs if m < max_len]


# --------------------------------------------------------------------------- #
# Post-traitement (probabilités, confiance) — pur, sans numpy
# --------------------------------------------------------------------------- #


def borner_temperature(valeur: float) -> float:
    return max(TEMPERATURE_MIN, min(TEMPERATURE_MAX, float(valeur)))


def softmax(logits: list[float], temperature: float = 1.0) -> list[float]:
    t = borner_temperature(temperature)
    z = [x / t for x in logits]
    m = max(z)
    e = [math.exp(x - m) for x in z]
    s = sum(e)
    return [x / s for x in e]


def confiance(probas: list[float]) -> float:
    """Confiance « façon Jev » : 1 - entropie normalisée de la distribution."""
    k = len(probas)
    if k < 2:
        return 1.0
    ent = -sum(p * math.log(max(p, 1e-12)) for p in probas)
    return max(0.0, min(1.0, 1 - ent / math.log(k)))


# --------------------------------------------------------------------------- #
# Moteur ONNX Runtime
# --------------------------------------------------------------------------- #


class MoteurOnnx:
    """Encodeur + tête de décision en un seul graphe ONNX, exécuté sur CPU."""

    def __init__(self, dossier: Path, precision: str, *, max_len: int = 1024) -> None:
        import json

        from hermes.agents.krinos.laya_modele import fichiers_requis

        for f in fichiers_requis(precision):
            if not (dossier / f.chemin).is_file():
                raise ModeleLayaAbsent(f"fichier du modèle Laya manquant : {f.chemin}")
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover — dépendances du paquet
            raise ErreurLaya(f"dépendance manquante ({exc.name})") from exc

        cfg = json.loads((dossier / "config.json").read_text(encoding="utf-8")).get("laya", {})
        self.max_len = max(64, min(int(max_len), 8192))
        self.head_max_len = int(cfg.get("head_max_len", 256))
        self.max_option_tokens = int(cfg.get("max_option_tokens", 48))
        self._tok = Tokenizer.from_file(str(dossier / "tokenizer.json"))
        self.jetons = Jetons(
            cls=self._id("<bos>"),
            sep=self._id("<eos>"),
            mask=self._id("<mask>"),
            pad=self._id("<pad>"),
        )
        nom = "model_fp16.onnx" if precision == "fp16" else "model.onnx"
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(dossier / "onnx" / nom), options, providers=["CPUExecutionProvider"]
        )
        self._verrou = threading.Lock()  # une inférence à la fois : CPU partagé avec PYTHIA

    def _id(self, jeton: str) -> int:
        i = self._tok.token_to_id(jeton)
        if i is None:
            raise ErreurLaya(f"tokenizer Laya inattendu (jeton {jeton} absent)")
        return i

    def _encoder(self, texte: str) -> list[int]:
        return self._tok.encode(texte, add_special_tokens=False).ids

    def evaluer(self, etat: str, questions: dict[str, QuestionLaya]) -> dict[str, SortieLaya]:
        import numpy as np

        sorties: dict[str, SortieLaya] = {}
        for nom, q in questions.items():
            ids, marqueurs = construire_sequence(
                self._encoder, self.jetons, etat, q, self.max_len, self.head_max_len,
                self.max_option_tokens,
            )
            if len(marqueurs) != len(rendre_options(q)):
                raise ErreurLaya(f"question {nom!r} : options hors budget de tête")
            entrees = {
                "input_ids": np.asarray([ids], dtype=np.int64),
                "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
                "marker_pos": np.asarray([marqueurs], dtype=np.int64),
                "marker_mask": np.ones((1, len(marqueurs)), dtype=np.bool_),
                "qtype": np.asarray([TYPES_QUESTION[q.type]], dtype=np.int64),
            }
            with self._verrou:
                logits, act = self._session.run(["logits", "act_logits"], entrees)
            a = act[0].astype("float64")
            a = np.exp(a - a.max())
            sorties[nom] = SortieLaya(
                logits=[float(x) for x in logits[0][: len(marqueurs)]],
                act_probabilite=float(a[0] / a.sum()),
                tokens=len(ids),
            )
        return sorties


_moteurs: dict[tuple[str, str, int], MoteurOnnx] = {}
_verrou_cache = threading.Lock()


def moteur_onnx(dossier: Path, precision: str, max_len: int) -> MoteurOnnx:
    """Moteur ONNX en cache (chargement paresseux : rien au démarrage de HERMES)."""
    cle = (str(dossier), precision, max_len)
    with _verrou_cache:
        moteur = _moteurs.get(cle)
        if moteur is None:
            # Premier chargement dans ce process : SHA-256 complet de chaque fichier
            # (streaming, mis en cache par chemin + taille + mtime). Un échec refuse le
            # chargement ; rien n'est retéléchargé sans nouveau consentement.
            from hermes.agents.krinos.laya_modele import alteres, verifier_integrite

            verifier_integrite(precision, dossier)
            corrompus = alteres(precision, dossier)
            if corrompus:
                raise ModeleLayaAltere(corrompus)
            moteur = _moteurs[cle] = MoteurOnnx(dossier, precision, max_len=max_len)
        return moteur


def liberer_moteurs() -> None:
    """Décharge les sessions ONNX (ex. avant de supprimer les fichiers du modèle)."""
    with _verrou_cache:
        _moteurs.clear()

"""Tests du moteur Laya : construction de la séquence (parité avec le code de référence),
post-traitement des logits. Faux tokenizer : aucun modèle requis."""

from __future__ import annotations

import math
import random
import zlib
from typing import Dict, List, Optional  # noqa: UP035 — copie fidèle de la référence

import pytest

from hermes.agents.krinos.laya_moteur import (
    Jetons,
    QuestionLaya,
    borner_temperature,
    confiance,
    construire_sequence,
    rendre_options,
    softmax,
)

CLS, SEP, MASK, PAD = 2, 1, 4, 0
JETONS = Jetons(cls=CLS, sep=SEP, mask=MASK, pad=PAD)


def _ids_mot(mot: str) -> int:
    return 10 + zlib.crc32(mot.encode()) % 5000


class FauxTokenizer:
    """Un « token » par mot (blancs ignorés), plus `<mask>` reconnu comme jeton spécial.

    Se comporte comme le tokenizer de référence (objet appelable renvoyant un dict
    `input_ids`, attributs `mask_token*`, `cls_token_id`, `sep_token_id`)."""

    mask_token = "<mask>"
    mask_token_id = MASK
    cls_token_id = CLS
    sep_token_id = SEP

    def encoder(self, texte: str) -> list[int]:
        return [MASK if m == "<mask>" else _ids_mot(m) for m in texte.split()]

    def __call__(self, texte: str, add_special_tokens: bool = False) -> dict:
        assert add_special_tokens is False
        return {"input_ids": self.encoder(texte)}


# --- Copie fidèle de la référence : convaiinnovations/laya, rl_common.py (Apache-2.0) ---


def _ref_render_options(q: Dict) -> List[str]:  # noqa: UP006
    t, crit = q["t"], q.get("crit")
    if t == "choice":
        if isinstance(crit, list):
            crit = {c: None for c in crit}
        return [k if not v else "%s: %s" % (k, v) for k, v in crit.items()]  # noqa: UP031
    if t == "score":
        return ["level %d: %s" % (i, c) for i, c in enumerate(crit)]  # noqa: UP031
    crit = crit or {}
    return ["false: " + (crit.get("false") or "no, the statement does not hold"),
            "true: " + (crit.get("true") or "yes, the statement holds")]


def _ref_build_sequence(tok, state, q: Dict, max_len: int, head_max_len: int,  # noqa: UP006
                        option_order: Optional[List[int]] = None):  # noqa: UP006, UP045
    mask_tok = tok.mask_token
    opts = _ref_render_options(q)
    order = option_order if option_order is not None else list(range(len(opts)))
    ins = str(q["ins"]).replace(mask_tok, " ")
    head_ids = tok("%s question: %s" % (q["t"], ins), add_special_tokens=False)["input_ids"]  # noqa: UP031
    opt_ids = []
    for i in order:
        opt_ids.append([tok.mask_token_id] + tok(
            " " + opts[i].replace(mask_tok, " "), add_special_tokens=False)["input_ids"][:48])
    opt_budget = head_max_len - sum(len(o) for o in opt_ids)
    if opt_budget < 16:
        per = max(4, (head_max_len - 16) // max(1, len(opt_ids)))
        opt_ids = [o[:per] for o in opt_ids]
        opt_budget = head_max_len - sum(len(o) for o in opt_ids)
    head_ids = head_ids[:max(8, opt_budget)]
    ids = [tok.cls_token_id] + head_ids + [tok.sep_token_id]
    markers = []
    for o in opt_ids:
        markers.append(len(ids))
        ids.extend(o)
    ids.append(tok.sep_token_id)
    room = max(0, max_len - len(ids) - 1)
    st = tok(state.replace(mask_tok, " "), add_special_tokens=False)["input_ids"]
    st = st[:room]
    ids = ids + st + [tok.sep_token_id]
    return ids[:max_len], [m for m in markers if m < max_len]


# --- Tests ---------------------------------------------------------------------------


def _q(t: str, ins: str, crit) -> QuestionLaya:
    return QuestionLaya(t, ins, crit)


def test_structure_de_la_sequence():
    tok = FauxTokenizer()
    q = _q("choice", "Quel service ?", {"a": "facturation", "b": ""})
    ids, marqueurs = construire_sequence(tok.encoder, JETONS, "etat un deux", q, 1024, 256)
    tete = tok.encoder("choice question: Quel service ?")
    assert ids[0] == CLS
    assert ids[1 : 1 + len(tete)] == tete and ids[1 + len(tete)] == SEP
    assert len(marqueurs) == 2
    assert all(ids[m] == MASK for m in marqueurs)
    assert ids[marqueurs[0] + 1 : marqueurs[1]] == tok.encoder("a: facturation")
    assert ids[marqueurs[1] + 1] == _ids_mot("b")  # option sans description : la clé seule
    assert ids[-1] == SEP and ids[-4:-1] == tok.encoder("etat un deux")


def test_options_noul_et_score():
    assert rendre_options(_q("noul", "?", None)) == [
        "false: no, the statement does not hold",
        "true: yes, the statement holds",
    ]
    assert rendre_options(_q("noul", "?", {"true": "oui", "false": "non"})) == [
        "false: non",
        "true: oui",
    ]
    assert rendre_options(_q("score", "?", ["nul", "bon"])) == ["level 0: nul", "level 1: bon"]
    assert rendre_options(_q("choice", "?", ["x", "y"])) == ["x", "y"]  # liste de clés


def test_le_jeton_mask_des_donnees_est_neutralise():
    tok = FauxTokenizer()
    q = _q("choice", "Pick <mask> one", {"a": "un <mask> deux", "b": "x"})
    ids, marqueurs = construire_sequence(tok.encoder, JETONS, "avant <mask> après", q, 1024, 256)
    assert ids.count(MASK) == 2  # seuls les marqueurs d'options
    assert [ids[m] for m in marqueurs] == [MASK, MASK]


def test_troncature_a_max_len_et_marqueurs_hors_borne_ecartes():
    tok = FauxTokenizer()
    q = _q("noul", "Pertinent ?", None)
    ids, marqueurs = construire_sequence(tok.encoder, JETONS, "mot " * 5000, q, 64, 256)
    assert len(ids) == 64 and len(marqueurs) == 2
    # max_len minuscule : le second marqueur sort de la séquence.
    ids, marqueurs = construire_sequence(tok.encoder, JETONS, "mot", q, 14, 256)
    assert len(ids) == 14 and len(marqueurs) == 1


def test_options_trop_nombreuses_sont_rabotees():
    tok = FauxTokenizer()
    crit = {f"t{i}": "une description assez longue du sujet " * 3 for i in range(14)}
    q = _q("choice", "Lequel ? " * 8, crit)
    ids, marqueurs = construire_sequence(tok.encoder, JETONS, "etat", q, 1024, 256)
    assert len(marqueurs) == 14
    assert marqueurs[-1] < 256 + 2  # la tête reste dans son budget


@pytest.mark.parametrize("graine", range(30))
def test_parite_avec_le_code_de_reference(graine):
    """Même séquence et mêmes marqueurs que `build_sequence` de référence, sur des
    cas tirés au hasard (types, tailles d'options, longueurs d'état, max_len)."""
    rnd = random.Random(graine)
    tok = FauxTokenizer()

    def texte(n: int) -> str:
        mots = ["prix", "critère", "<mask>", "délai", "SMS", "émoji🎉", "lot", "2026", "a"]
        return " ".join(rnd.choice(mots) for _ in range(n))

    t = rnd.choice(["choice", "score", "noul"])
    if t == "choice":
        crit = {f"k{i}": texte(rnd.randint(0, 70)) for i in range(rnd.randint(2, 16))}
    elif t == "score":
        crit = [texte(rnd.randint(1, 60)) for _ in range(rnd.randint(2, 8))]
    else:
        crit = rnd.choice([None, {"true": texte(30), "false": texte(80)}])
    ins = texte(rnd.randint(1, 300))
    etat = texte(rnd.choice([0, 5, 400, 3000]))
    max_len = rnd.choice([64, 300, 1024, 2048])
    ref = _ref_build_sequence(tok, etat, {"t": t, "ins": ins, "crit": crit}, max_len, 256)
    moi = construire_sequence(tok.encoder, JETONS, etat, _q(t, ins, crit), max_len, 256)
    assert moi == ref


# --- Post-traitement ------------------------------------------------------------------


def test_softmax_et_temperature():
    p = softmax([0.0, 2.0])
    assert sum(p) == pytest.approx(1.0) and p[1] == pytest.approx(1 / (1 + math.exp(-2)))
    chaud = softmax([0.0, 2.0], 4.0)
    assert 0.5 < chaud[1] < p[1]  # T > 1 aplatit sans inverser
    assert softmax([0.0, 2.0], 0.5)[1] > p[1]  # T < 1 durcit
    assert softmax([1000.0, 0.0])[0] == pytest.approx(1.0)  # stable numériquement
    assert borner_temperature(100) == 5.0 and borner_temperature(0) == 0.5


def test_confiance_entropie_normalisee():
    assert confiance([0.5, 0.5]) == pytest.approx(0.0)
    assert confiance([1.0, 0.0]) == pytest.approx(1.0)
    assert confiance([0.25] * 4) == pytest.approx(0.0)
    assert 0.0 < confiance([0.7, 0.2, 0.1]) < 1.0
    assert confiance([1.0]) == 1.0

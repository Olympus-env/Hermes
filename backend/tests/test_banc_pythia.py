"""Tests issue #30 — banc d'essai PYTHIA (métriques, fixtures, rapport)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "banc_pythia.py"
_spec = importlib.util.spec_from_file_location("banc_pythia", _SCRIPT)
banc = importlib.util.module_from_spec(_spec)
sys.modules["banc_pythia"] = banc  # requis par @dataclass
_spec.loader.exec_module(banc)


def test_ecart_score():
    assert banc.ecart_score(70, 60, 80) == 0
    assert banc.ecart_score(50, 60, 80) == 10
    assert banc.ecart_score(95, 60, 80) == 15


def test_rappel_tags_insensible_aux_accents_et_sous_chaines():
    obtenus = ["Développement web", "SÉCURITÉ"]
    assert banc.rappel_tags(obtenus, ["developpement", "securite", "cloud"]) == pytest.approx(2 / 3)
    assert banc.rappel_tags([], []) is None


def test_rappel_mots_cles():
    texte = "Prix 30 % ; valeur technique 50 %"
    assert banc.rappel_mots_cles(texte, ["prix", "TECHNIQUE", "délai"]) == pytest.approx(2 / 3)
    assert banc.rappel_mots_cles("", []) is None


def test_fixtures_valides_et_anonymes():
    fixtures = banc.charger_fixtures(banc.DOSSIER_FIXTURES)
    assert len(fixtures) >= 3
    ids = [f["id"] for f in fixtures]
    assert len(set(ids)) == len(ids)
    for f in fixtures:
        att = f["attendus"]
        assert 0 <= att["score_min"] <= att["score_max"] <= 100
        assert f["ao"]["titre"] and isinstance(f["documents"], list)
        assert "(fictif" in f["ao"]["emetteur"]  # émetteurs explicitement fictifs


def test_rapport_markdown():
    fixtures = [{"id": "a", "attendus": {"score_min": 10, "score_max": 20}}]
    mesures = [
        banc.Mesure(
            modele="m1", fixture="a", ok=True, conforme_premier_essai=True, tentatives=1,
            score=15, ecart_score=0, rappel_tags=1.0, latence_s=2.0,
            tokens_sortie=100, duree_generation_s=4.0,
        ),
        banc.Mesure(modele="m1", fixture="a", ok=False, erreur="timeout"),
    ]
    rapport = banc.rendre_rapport(
        mesures, moteur="ollama", ignores={"m2": "absent"}, fixtures=fixtures
    )
    assert "| `m1` | 1/2 | 50 %" in rapport
    assert "25.0" in rapport  # tokens/s
    assert "ÉCHEC : timeout" in rapport
    assert "`m2` | ignoré : absent" in rapport

"""Banc d'essai Laya — métriques pures et constitution du corpus (sans modèle ni réseau)."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "banc_laya.py"
_spec = importlib.util.spec_from_file_location("banc_laya", _SCRIPT)
banc = importlib.util.module_from_spec(_spec)
sys.modules["banc_laya"] = banc  # requis par @dataclass
_spec.loader.exec_module(banc)


def test_auroc():
    assert banc.auroc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert banc.auroc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0
    assert banc.auroc([0.5, 0.5], [True, False]) == 0.5  # ex æquo à demi
    assert banc.auroc([0.5, 0.6], [True, True]) is None  # une seule classe


def test_taux_percentile_meilleur_seuil():
    assert banc.taux([True, False, True, True]) == 0.75 and banc.taux([]) is None
    assert banc.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert banc.percentile([5.0], 0.95) == 5.0 and math.isnan(banc.percentile([], 0.5))
    seuil, exact = banc.meilleur_seuil([0.1, 0.4, 0.6, 0.9], [False, False, True, True])
    assert (seuil, exact) == (0.6, 1.0)
    assert banc.meilleur_seuil([], []) is None


def test_fixtures_du_banc_pythia_reutilisees():
    cas = banc.construire_cas_fixtures()
    assert len(cas) == 4
    voirie = next(c for c in cas if "voirie" in c.id)
    portail = next(c for c in cas if "refonte_portail" in c.id)
    assert voirie.attendu_pertinent is False and portail.attendu_pertinent is True
    assert portail.score_attendu[0] >= 65 and portail.documents


def test_pieges_5_formulations_3_positions_dans_un_dce_long():
    hote = next(c for c in banc.construire_cas_fixtures() if "refonte_portail" in c.id)
    pieges = banc.construire_cas_pieges(hote)
    assert len(pieges) == 15 and all(c.attendu_manipulation for c in pieges)
    for c in pieges:
        phrase = banc.PHRASES_PIEGEES[c.extra["phrase"] - 1]
        assert phrase in c.documents and len(c.documents) > 12_000
        pos = c.documents.index(phrase) / len(c.documents)
        assert {"debut": pos < 0.05, "milieu": 0.3 < pos < 0.7, "fin": pos > 0.95}[
            c.extra["position"]
        ]


def test_etat_du_cas_borne_comme_en_production():
    from hermes.agents.krinos import laya

    hote = next(c for c in banc.construire_cas_fixtures() if "refonte_portail" in c.id)
    for c in banc.construire_cas_pieges(hote)[:3]:
        assert len(banc.etat_du_cas(c)) <= laya.max_caracteres_state()


def test_corpus_reel_versionne():
    reels = banc.charger_corpus_reel()
    assert len(reels) >= 10  # critère de l'issue : au moins 10 AO réels
    assert {c.groupe for c in reels} == {"reel_pertinent", "reel_hors_profil"}
    assert all(c.avis["titre"] and c.attendu_pertinent is not None for c in reels)
    assert all(c.groupe == ("reel_pertinent" if c.attendu_pertinent else "reel_hors_profil")
               for c in reels)
    assert len({c.id for c in reels}) == len(reels)


def test_sains_longs_sans_phrase_piegee():
    fixtures = banc.construire_cas_fixtures()
    sains = banc.construire_cas_sains_longs(fixtures)
    assert len(sains) == 3 and all(len(c.documents) > 12_000 for c in sains)
    assert not any(p in c.documents for c in sains for p in banc.PHRASES_PIEGEES)


def test_rapport_sans_pythia_l_indique():
    def ligne(groupe, manip, phrase=False):
        return {
            "id": groupe, "groupe": groupe, "tokens": 700, "caracteres_etat": 2000,
            "t_complet_s": 5.0, "t_pretri_s": 1.0, "attendu_pertinent": True,
            "attendu_manipulation": groupe == "piege", "score_attendu": None,
            "phrase_dans_etat": phrase,
            "libelles_fr": {"pertinence": 0.8, "manipulation": manip},
            "choice_neutre": {"pertinence": 0.8, "manipulation": manip},
            "produit": {t: {"pertinence": 0.9, "manipulation": manip, "confiance": 0.5,
                            "score": 60.0} for t in ("1.0", "1.5", "2.0", "3.0")},
        }

    lignes = [ligne("piege", 0.9, True), ligne("sain_long", 0.1), ligne("reel_pertinent", 0.1)]
    meta = {"date": "d", "cpu": "4 vCPU", "ort": "1", "max_len": 1024, "n_fixtures": 0,
            "n_sains_longs": 1, "n_pieges": 1, "n_reels": 1, "n_reels_pertinents": 1,
            "n_reels_hors": 0}
    texte = banc.rediger_rapport(
        [{"precision": "fp16", "chargement_s": 2.0, "lignes": lignes}], None, meta
    )
    assert "Précision fp16" in texte and "Indisponible" in texte
    assert "pièges à phrase visible 1/1" in texte  # détecté
    assert "DCE sains 0/1" in texte  # aucun faux positif


@pytest.mark.parametrize("n", [10, 5000])
def test_remplissage_atteint_la_taille_demandee(n):
    assert len(banc._remplissage(n)) >= n

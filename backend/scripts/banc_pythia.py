"""Banc d'essai PYTHIA — compare des modèles LLM locaux sur des AO de référence.

Pour chaque modèle demandé, exécute KRINOS (`analyser_ao`) sur les fixtures de
`scripts/banc_fixtures/*.json` (AO fictifs + attendus) et mesure :

- la conformité au schéma de sortie (première réponse valide, sans relance) ;
- l'écart du score aux attendus (fourchette), le rappel des tags et des critères ;
- la latence par AO et le débit (tokens/s) ;
puis écrit un rapport Markdown.

Sécurité et périmètre :
- AUCUN téléchargement de modèle : un modèle absent du moteur est signalé et
  ignoré (`ollama pull` reste une action manuelle, cf. README) ;
- moteur loopback uniquement (invariant local-first) ;
- base SQLite jetable dans un dossier temporaire : `./data` n'est jamais touché.

Usage (depuis `backend/`) :
    .venv/bin/python scripts/banc_pythia.py --modeles qwen3:8b,gemma2:9b
    .venv/bin/python scripts/banc_pythia.py --moteur openai_compatible \\
        --url http://127.0.0.1:8080/v1 --modeles mon-modele --sortie rapport.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DOSSIER_FIXTURES = Path(__file__).resolve().parent / "banc_fixtures"


# --- Métriques pures (sans dépendance à HERMES : testables isolément) -----------


def normaliser(texte: str) -> str:
    """Minuscules sans accents, pour comparer des libellés de façon tolérante."""
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def ecart_score(score: float, score_min: float, score_max: float) -> float:
    """Distance du score à la fourchette attendue (0 = dans la fourchette)."""
    if score < score_min:
        return round(score_min - score, 1)
    if score > score_max:
        return round(score - score_max, 1)
    return 0.0


def rappel_tags(tags: list[str], attendus: list[str]) -> float | None:
    """Part des tags attendus retrouvés (correspondance par sous-chaîne, sans accents)."""
    if not attendus:
        return None
    obtenus = [normaliser(t) for t in tags]
    trouves = sum(
        1 for a in attendus if any(normaliser(a) in t or t in normaliser(a) for t in obtenus)
    )
    return trouves / len(attendus)


def rappel_mots_cles(texte: str, mots: list[str]) -> float | None:
    """Part des mots-clés attendus présents dans le texte des critères extraits."""
    if not mots:
        return None
    corps = normaliser(texte or "")
    return sum(1 for m in mots if normaliser(m) in corps) / len(mots)


@dataclass
class Mesure:
    modele: str
    fixture: str
    ok: bool = False  # l'analyse a abouti (aucune exception)
    erreur: str = ""
    conforme_premier_essai: bool = False
    tentatives: int = 0
    degradee: bool = False
    score: float | None = None
    ecart_score: float | None = None
    rappel_tags: float | None = None
    rappel_criteres: float | None = None
    latence_s: float = 0.0
    tokens_sortie: int = 0
    duree_generation_s: float = 0.0

    @property
    def tokens_par_seconde(self) -> float | None:
        if not self.tokens_sortie or self.duree_generation_s <= 0:
            return None
        return self.tokens_sortie / self.duree_generation_s


def _moyenne(valeurs: list[float | None]) -> float | None:
    v = [x for x in valeurs if x is not None]
    return statistics.fmean(v) if v else None


def _fmt(valeur: float | None, unite: str = "", decimales: int = 1) -> str:
    return "n/a" if valeur is None else f"{valeur:.{decimales}f}{unite}"


def _pct(valeur: float | None) -> str:
    return "n/a" if valeur is None else f"{valeur * 100:.0f} %"


def rendre_rapport(
    mesures: list[Mesure],
    *,
    moteur: str,
    ignores: dict[str, str],
    fixtures: list[dict[str, Any]],
    maintenant: datetime | None = None,
) -> str:
    """Rapport Markdown : synthèse par modèle, puis détail par AO."""
    maintenant = maintenant or datetime.now().astimezone()
    lignes = [
        "# Banc d'essai PYTHIA",
        "",
        f"- Date : {maintenant:%Y-%m-%d %H:%M %Z}",
        f"- Moteur : `{moteur}`",
        f"- Fixtures : {len(fixtures)} AO fictifs (`scripts/banc_fixtures/`)",
        "",
        "## Synthèse par modèle",
        "",
        "| Modèle | Analyses OK | Conformité schéma (1er essai) | Dégradées | Écart score moy. | "
        "Rappel tags | Rappel critères | Latence moy. | Tokens/s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    modeles = list(dict.fromkeys(m.modele for m in mesures))
    for modele in modeles:
        ms = [m for m in mesures if m.modele == modele]
        abouties = [m for m in ms if m.ok]
        tps = _moyenne([m.tokens_par_seconde for m in abouties])
        lignes.append(
            f"| `{modele}` | {len(abouties)}/{len(ms)} "
            f"| {_pct(sum(m.conforme_premier_essai for m in ms) / len(ms))} "
            f"| {sum(m.degradee for m in abouties)} "
            f"| {_fmt(_moyenne([m.ecart_score for m in abouties]))} "
            f"| {_pct(_moyenne([m.rappel_tags for m in abouties]))} "
            f"| {_pct(_moyenne([m.rappel_criteres for m in abouties]))} "
            f"| {_fmt(_moyenne([m.latence_s for m in abouties]), ' s')} "
            f"| {_fmt(tps)} |"
        )
    for modele, raison in ignores.items():
        lignes.append(f"| `{modele}` | ignoré : {raison} | | | | | | | |")

    lignes += [
        "",
        "## Détail par AO",
        "",
        "| Modèle | AO | Statut | Conforme 1er essai | Tentatives | Score (attendu) | Écart | "
        "Tags | Critères | Latence | Tokens/s |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    attendus = {f["id"]: f["attendus"] for f in fixtures}
    for m in mesures:
        att = attendus.get(m.fixture, {})
        fourchette = f"{att.get('score_min', '?')}-{att.get('score_max', '?')}"
        if not m.ok:
            statut = f"ÉCHEC : {m.erreur}"
        elif m.degradee:
            statut = "dégradée (secours local)"
        else:
            statut = "ok"
        score = "n/a" if m.score is None else f"{m.score:.0f} ({fourchette})"
        lignes.append(
            f"| `{m.modele}` | {m.fixture} | {statut} "
            f"| {'oui' if m.conforme_premier_essai else 'non'} | {m.tentatives} "
            f"| {score} | {_fmt(m.ecart_score, decimales=0)} "
            f"| {_pct(m.rappel_tags)} | {_pct(m.rappel_criteres)} "
            f"| {m.latence_s:.1f} s | {_fmt(m.tokens_par_seconde)} |"
        )
    lignes += [
        "",
        "Lecture : « conforme 1er essai » = la première sortie du modèle respecte le schéma "
        "JSON de KRINOS sans relance ; « écart » = distance du score à la fourchette "
        "attendue (0 = dans la fourchette) ; les rappels comparent tags et critères "
        "extraits aux attendus de la fixture.",
        "",
    ]
    return "\n".join(lignes)


# --- Exécution (nécessite HERMES) ----------------------------------------------


def charger_fixtures(dossier: Path) -> list[dict[str, Any]]:
    fixtures = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(dossier.glob("*.json"))]
    if not fixtures:
        raise SystemExit(f"Aucune fixture JSON dans {dossier}")
    return fixtures


def _isoler_environnement() -> tempfile.TemporaryDirectory:
    """Redirige les données HERMES vers un dossier jetable AVANT l'import de hermes."""
    tmp = tempfile.TemporaryDirectory(prefix="banc-pythia-")
    racine = Path(tmp.name)
    os.environ["HERMES_DB_PATH"] = str(racine / "banc.db")
    os.environ["HERMES_STORAGE_PATH"] = str(racine / "storage")
    os.environ["HERMES_LOG_PATH"] = str(racine / "logs")
    os.environ["HERMES_MASTER_KEY_PATH"] = str(racine / "master.key")
    return tmp


@dataclass
class _Capture:
    """Réponses PYTHIA et durées capturées pendant une analyse KRINOS."""

    textes: list[str] = field(default_factory=list)
    tokens_sortie: int = 0
    generation_ms: int = 0


async def _mesurer(modele: str, fixture: dict[str, Any]) -> Mesure:
    import hashlib
    import time

    from sqlmodel import Session

    from hermes.agents import pythia
    from hermes.agents.krinos import analyzer
    from hermes.db.models import AppelOffre, Document
    from hermes.db.session import get_engine

    mesure = Mesure(modele=modele, fixture=fixture["id"])
    ao_data = dict(fixture["ao"])
    if ao_data.get("date_limite"):
        ao_data["date_limite"] = datetime.fromisoformat(ao_data["date_limite"])

    capture = _Capture()
    generer_reel = pythia.generer

    async def generer_capture(*args: Any, **kwargs: Any):
        reponse = await generer_reel(*args, **kwargs)
        capture.textes.append(reponse.texte)
        capture.tokens_sortie += reponse.tokens_sortie or 0
        capture.generation_ms += reponse.duree_generation_ms or reponse.duree_ms
        return reponse

    with Session(get_engine()) as session:
        ao = AppelOffre(
            reference_externe=f"banc-{fixture['id']}-{time.monotonic_ns()}",
            url_source=f"https://exemple.invalid/banc/{fixture['id']}",
            **ao_data,
        )
        session.add(ao)
        session.commit()
        session.refresh(ao)
        for doc in fixture.get("documents", []):
            contenu = doc["contenu"]
            session.add(
                Document(
                    appel_offre_id=ao.id,
                    nom_fichier=doc["nom"],
                    chemin_local=f"banc/{doc['nom']}",
                    taille_octets=len(contenu.encode()),
                    checksum_sha256=hashlib.sha256(contenu.encode()).hexdigest(),
                    contenu_extrait=contenu,
                )
            )
        session.commit()

        pythia.generer = generer_capture  # type: ignore[assignment]
        debut = time.perf_counter()
        try:
            resultat = await analyzer.analyser_ao(session, ao, forcer=True)
        except Exception as exc:  # noqa: BLE001 — le banc consigne l'échec et continue
            mesure.erreur = str(exc)[:120]
            mesure.latence_s = time.perf_counter() - debut
            return mesure
        finally:
            pythia.generer = generer_reel  # type: ignore[assignment]
        mesure.latence_s = time.perf_counter() - debut

        analyse = resultat.analyse
        att = fixture["attendus"]
        tags = json.loads(analyse.tags) if analyse.tags else []
        mesure.ok = True
        mesure.degradee = analyse.degradee
        mesure.tentatives = len(capture.textes)
        mesure.score = analyse.score
        mesure.ecart_score = ecart_score(analyse.score, att["score_min"], att["score_max"])
        mesure.rappel_tags = rappel_tags(tags, att.get("tags", []))
        mesure.rappel_criteres = rappel_mots_cles(
            analyse.criteres_extraits or "", att.get("criteres_mots_cles", [])
        )
        mesure.tokens_sortie = capture.tokens_sortie
        mesure.duree_generation_s = capture.generation_ms / 1000

        schema = getattr(analyzer, "SortieAnalyseKrinos", None)
        if capture.textes and schema is not None:
            try:
                schema.model_validate(pythia.parser_json_sortie(capture.textes[0]))
                mesure.conforme_premier_essai = True
            except Exception:  # noqa: BLE001 — non conforme : JSON invalide ou champs manquants
                mesure.conforme_premier_essai = False
    return mesure


async def executer(args: argparse.Namespace) -> str:
    from hermes.agents import pythia
    from hermes.config import settings
    from hermes.db.session import init_db

    settings.pythia_moteur = args.moteur
    if args.url:
        # Même garde-fou que l'application : loopback uniquement.
        if args.moteur == "openai_compatible":
            settings.pythia_url = pythia.verifier_url_ollama_locale(args.url)
        else:
            settings.ollama_base_url = pythia.verifier_url_ollama_locale(args.url)
    if args.timeout:
        settings.pythia_timeout_secondes = args.timeout
    init_db()

    fixtures = charger_fixtures(Path(args.fixtures))
    if not await pythia.est_disponible():
        raise SystemExit(f"Moteur PYTHIA `{args.moteur}` injoignable (loopback).")

    mesures: list[Mesure] = []
    ignores: dict[str, str] = {}
    for modele in args.modeles:
        if not await pythia.modele_installe(modele):
            ignores[modele] = "modèle absent du moteur (aucun téléchargement par le banc)"
            print(f"[banc] {modele} : absent, ignoré", file=sys.stderr)
            continue
        settings.pythia_modele = modele
        for fixture in fixtures:
            for _ in range(args.repetitions):
                print(f"[banc] {modele} × {fixture['id']} …", file=sys.stderr, flush=True)
                mesures.append(await _mesurer(modele, fixture))
    return rendre_rapport(mesures, moteur=args.moteur, ignores=ignores, fixtures=fixtures)


def analyser_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Banc d'essai PYTHIA (KRINOS sur AO de référence).")
    p.add_argument("--modeles", required=True, help="Modèles séparés par des virgules.")
    p.add_argument("--moteur", choices=("ollama", "openai_compatible"), default="ollama")
    p.add_argument("--url", help="URL loopback du moteur (Ollama : racine ; sinon : avec /v1).")
    p.add_argument("--fixtures", default=str(DOSSIER_FIXTURES))
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--timeout", type=float, help="Timeout par appel PYTHIA (secondes).")
    p.add_argument("--sortie", help="Fichier Markdown de sortie (défaut : stdout).")
    args = p.parse_args(argv)
    args.modeles = [m.strip() for m in args.modeles.split(",") if m.strip()]
    return args


def main(argv: list[str] | None = None) -> None:
    args = analyser_arguments(argv)
    # Le dossier `backend/` doit être importable (`hermes`) même hors `pip install -e`.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    tmp = _isoler_environnement()
    try:
        rapport = asyncio.run(executer(args))
    finally:
        tmp.cleanup()
    if args.sortie:
        Path(args.sortie).write_text(rapport, encoding="utf-8")
        print(f"[banc] rapport écrit dans {args.sortie}", file=sys.stderr)
    else:
        print(rapport)


if __name__ == "__main__":
    main()

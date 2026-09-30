"""KRINOS — fichiers du modèle Laya : emplacement, intégrité, téléchargement consenti.

Même règle que PYTHIA (#33) : **rien n'est téléchargé sans consentement explicite**
(l'API exige `confirme: true`), jamais au démarrage. Le seul hôte contacté est
Hugging Face, sur des URL épinglées à une révision précise ; chaque fichier est
vérifié par SHA-256 avant d'être rendu visible, un fichier corrompu est rejeté.

Portage ONNX communautaire (Apache-2.0) `onnx-community/laya-multilingual-ONNX`
d'après `convaiinnovations/laya-multilingual` ; parité mesurée par son auteur :
écart max des logits 3e-5 (fp32) et 0,035 en probabilité (fp16), sans changement de
décision.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from hermes.agents.krinos.laya_moteur import ErreurLaya
from hermes.config import settings

DEPOT = "onnx-community/laya-multilingual-ONNX"
REVISION = "46b77bbf5642fec5f14e540570228a8cbe8ab81f"
URL_BASE = f"https://huggingface.co/{DEPOT}/resolve/{REVISION}/"
PRECISIONS = ("fp16", "fp32")
PRECISION_DEFAUT = "fp16"
FICHIER_VERIFIE = "verifie.json"
TAILLE_BLOC = 1024 * 1024

# Seam de test : transport httpx simulé (jamais de réseau réel en pytest).
_transport: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class FichierModele:
    chemin: str  # relatif au dossier du modèle (et à l'URL de base)
    sha256: str
    taille: int


TOKENIZER = FichierModele(
    "tokenizer.json",
    "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f",
    34_363_188,
)
CONFIG = FichierModele(
    "config.json",
    "cc32109b1fded91ec6734127ffb1827f80cdcf8ffdd4eeda75a1b0f4d3687dcc",
    2_859,
)
FICHIERS_PAR_PRECISION: dict[str, tuple[FichierModele, ...]] = {
    "fp16": (
        FichierModele(
            "onnx/model_fp16.onnx",
            "81f641e21289ddb2cd8ac774c1cddebfdb0fa7e4b183e49ad476d2faee46d98a",
            3_572_287,
        ),
        FichierModele(
            "onnx/model_fp16.onnx_data",
            "3c9eb52f5f795f76d7a681197228131fac7e92c3e5a4c90b68ec4065699ee4cf",
            643_817_472,
        ),
    ),
    "fp32": (
        FichierModele(
            "onnx/model.onnx",
            "22461d988f675dd6c2b89ff8feb9ed7ffcf7e37854e5ed512f8b275178cf2f9f",
            3_553_251,
        ),
        FichierModele(
            "onnx/model.onnx_data",
            "f01238e183ace77661282e4eb2dd9b872c7044cb9678f904cf409e6cc1146d09",
            1_287_635_968,
        ),
    ),
}


def fichiers_requis(precision: str) -> tuple[FichierModele, ...]:
    if precision not in FICHIERS_PAR_PRECISION:
        raise ErreurLaya(f"précision Laya inconnue : {precision!r} (fp16 ou fp32)")
    return (TOKENIZER, CONFIG, *FICHIERS_PAR_PRECISION[precision])


def taille_totale(precision: str) -> int:
    return sum(f.taille for f in fichiers_requis(precision))


def dossier_modele() -> Path:
    """Dossier de données HERMES (`%LocalAppData%\\HERMES` en prod, `./data` en dev),
    sous-dossier `modeles/laya`. Surchargeable par `HERMES_LAYA_DOSSIER`."""
    return settings.laya_dossier or (settings.db_path.parent / "modeles" / "laya")


# --------------------------------------------------------------------------- #
# Intégrité
# --------------------------------------------------------------------------- #


def _lire_verifies(dossier: Path) -> dict[str, str]:
    try:
        data = json.loads((dossier / FICHIER_VERIFIE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _marquer_verifie(dossier: Path, fichier: FichierModele) -> None:
    verifies = _lire_verifies(dossier)
    verifies[fichier.chemin] = fichier.sha256
    tmp = dossier / (FICHIER_VERIFIE + ".tmp")
    tmp.write_text(json.dumps(verifies), encoding="utf-8")
    tmp.replace(dossier / FICHIER_VERIFIE)


# Empreintes déjà calculées dans ce process : (chemin, taille, mtime_ns) -> SHA-256. Un
# fichier inchangé n'est donc haché qu'une fois ; toute modification (taille ou mtime)
# invalide l'entrée. Volontairement non persisté : un nouveau process revérifie.
_empreintes: dict[tuple[str, int, int], str] = {}
# Fichiers dont l'empreinte ne correspond pas : (dossier, chemin relatif). Le modèle est
# alors « à réinstaller » ; `fichier_valide` les refuse tant qu'ils n'ont pas été
# re-téléchargés (avec consentement), sinon le téléchargement les croirait sains.
_alteres: set[tuple[str, str]] = set()
_verrou_empreintes = threading.Lock()


def fichier_valide(dossier: Path, fichier: FichierModele) -> bool:
    """Présent, de la bonne taille, déjà vérifié par SHA-256 (test peu coûteux) et pas
    signalé altéré. Le hachage complet est refait au premier chargement du moteur du
    process, cf. `verifier_integrite`."""
    if (str(dossier), fichier.chemin) in _alteres:
        return False
    chemin = dossier / fichier.chemin
    try:
        if chemin.stat().st_size != fichier.taille:
            return False
    except OSError:
        return False
    return _lire_verifies(dossier).get(fichier.chemin) == fichier.sha256


def sha256_fichier(chemin: Path) -> str:
    """SHA-256 en streaming (blocs de 1 Mo) : jamais 650 Mo en mémoire."""
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        while bloc := f.read(TAILLE_BLOC):
            h.update(bloc)
    return h.hexdigest()


def _sha256_en_cache(chemin: Path) -> str:
    st = chemin.stat()
    cle = (str(chemin), st.st_size, st.st_mtime_ns)
    with _verrou_empreintes:
        connue = _empreintes.get(cle)
    if connue is None:
        connue = sha256_fichier(chemin)
        with _verrou_empreintes:
            _empreintes[cle] = connue
    return connue


def verifier_integrite(precision: str, dossier: Path | None = None) -> list[str]:
    """Hachage SHA-256 complet (mis en cache par process) ; retourne les chemins invalides
    (liste vide = intact). Met à jour l'état « à réinstaller » du dossier."""
    dossier = dossier or dossier_modele()
    invalides = []
    for f in fichiers_requis(precision):
        chemin = dossier / f.chemin
        try:
            ok = chemin.is_file() and _sha256_en_cache(chemin) == f.sha256
        except OSError:
            ok = False
        cle = (str(dossier), f.chemin)
        if ok:
            _alteres.discard(cle)
        else:
            invalides.append(f.chemin)
            if chemin.is_file():  # présent mais altéré ; un fichier absent est « manquant »
                _alteres.add(cle)
    return invalides


def alteres(precision: str, dossier: Path | None = None) -> list[str]:
    """Fichiers signalés altérés par une vérification d'intégrité (modèle à réinstaller)."""
    dossier = dossier or dossier_modele()
    return [f.chemin for f in fichiers_requis(precision) if (str(dossier), f.chemin) in _alteres]


def oublier_verifications() -> None:
    """Remet à zéro le cache d'empreintes et l'état « altéré » (tests, réinstallation)."""
    with _verrou_empreintes:
        _empreintes.clear()
        _alteres.clear()


@dataclass(frozen=True)
class StatutModele:
    precision: str
    installe: bool
    manquants: list[str]
    a_reinstaller: list[str]  # présents mais dont le SHA-256 ne correspond plus
    taille_octets: int  # à télécharger au total pour cette précision (indicatif)
    dossier: str


def statut_modele(precision: str = PRECISION_DEFAUT) -> StatutModele:
    dossier = dossier_modele()
    manquants = [f.chemin for f in fichiers_requis(precision) if not fichier_valide(dossier, f)]
    return StatutModele(
        precision=precision,
        installe=not manquants,
        manquants=manquants,
        a_reinstaller=alteres(precision, dossier),
        taille_octets=taille_totale(precision),
        dossier=str(dossier),
    )


# --------------------------------------------------------------------------- #
# Téléchargement (état partagé en mémoire, suivi par polling comme PYTHIA)
# --------------------------------------------------------------------------- #


@dataclass
class EtatTelechargement:
    precision: str = ""
    en_cours: bool = False
    statut: str = ""
    fichier: str = ""
    octets_telecharges: int = 0
    octets_total: int = 0
    erreur: str | None = None
    termine_le: float | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _tache: asyncio.Task | None = None


_etat = EtatTelechargement()


def etat_global() -> EtatTelechargement:
    return _etat


async def _telecharger_fichier(
    client: httpx.AsyncClient,
    dossier: Path,
    fichier: FichierModele,
    etat: EtatTelechargement,
) -> None:
    """Télécharge un fichier (reprise sur `.part` possible), vérifie taille et SHA-256."""
    cible = dossier / fichier.chemin
    cible.parent.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_name(cible.name + ".part")
    hachage = hashlib.sha256()
    deja = 0
    if partiel.exists():
        if partiel.stat().st_size <= fichier.taille:
            with partiel.open("rb") as f:
                while bloc := f.read(TAILLE_BLOC):
                    hachage.update(bloc)
                    deja += len(bloc)
        else:
            partiel.unlink()
    etat.fichier = fichier.chemin
    base = etat.octets_telecharges

    entetes = {"Range": f"bytes={deja}-"} if 0 < deja < fichier.taille else {}
    if deja < fichier.taille:
        async with client.stream("GET", URL_BASE + fichier.chemin, headers=entetes) as reponse:
            if reponse.status_code == 200 and deja:
                # Le serveur ignore Range : on repart de zéro.
                hachage, deja = hashlib.sha256(), 0
                partiel.unlink(missing_ok=True)
            elif reponse.status_code not in (200, 206):
                raise ErreurLaya(f"HTTP {reponse.status_code} pour {fichier.chemin}")
            with partiel.open("ab") as sortie:
                async for bloc in reponse.aiter_bytes(TAILLE_BLOC):
                    sortie.write(bloc)
                    hachage.update(bloc)
                    deja += len(bloc)
                    if deja > fichier.taille:
                        raise ErreurLaya(f"{fichier.chemin} : plus gros qu'attendu")
                    etat.octets_telecharges = base + deja
    if deja != fichier.taille or hachage.hexdigest() != fichier.sha256:
        partiel.unlink(missing_ok=True)  # jamais de reprise sur un contenu corrompu
        raise ErreurLaya(f"{fichier.chemin} : empreinte SHA-256 invalide (fichier rejeté)")
    partiel.replace(cible)
    _marquer_verifie(dossier, fichier)
    _alteres.discard((str(dossier), fichier.chemin))


async def executer_telechargement(etat: EtatTelechargement, precision: str) -> None:
    """Tâche de fond : télécharge les fichiers manquants. Ne lève jamais (état porté
    par `etat`)."""
    dossier = dossier_modele()
    try:
        fichiers = fichiers_requis(precision)
        etat.octets_total = sum(f.taille for f in fichiers)
        etat.octets_telecharges = sum(f.taille for f in fichiers if fichier_valide(dossier, f))
        dossier.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=120.0),
            transport=_transport,
        ) as client:
            for f in fichiers:
                if fichier_valide(dossier, f):
                    continue
                etat.statut = "telechargement"
                await _telecharger_fichier(client, dossier, f, etat)
        etat.statut = "success"
        etat.octets_telecharges = etat.octets_total
        etat.termine_le = time.time()
    except asyncio.CancelledError:
        etat.statut = "annule"
        etat.erreur = None
    except ErreurLaya as exc:
        etat.statut, etat.erreur = "erreur", str(exc)
    except (httpx.HTTPError, OSError) as exc:
        etat.statut, etat.erreur = "erreur", f"téléchargement interrompu ({type(exc).__name__})"
    except Exception as exc:  # noqa: BLE001 — ne jamais geler l'état
        etat.statut, etat.erreur = "erreur", f"Erreur inattendue : {type(exc).__name__}"
    finally:
        etat.en_cours = False

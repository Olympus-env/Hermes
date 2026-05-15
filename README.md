# HERMES

Application desktop **100 % locale** de veille et réponse automatisée aux appels d'offre.
Zéro cloud, zéro coût récurrent, validation humaine obligatoire avant toute soumission.

## Architecture

| Composant | Technologie | Rôle |
|-----------|-------------|------|
| **HERMES** | Tauri 2 + React 18 + Tailwind | Application desktop, orchestrateur |
| **ARGOS** | Playwright + APScheduler | Collecte / scraping des portails AO |
| **KRINOS** | pdfplumber + pymupdf + Ollama | Extraction, analyse, scoring |
| **HERMION** | Ollama + workflow engine | Rédaction des réponses |
| **MNEMOSYNE** | SQLite + SQLModel | Base de données locale |
| **PYTHIA** | Ollama + Mistral 7B | LLM local |

Backend FastAPI sur `127.0.0.1:8000` uniquement — aucun port exposé à l'extérieur.

---

## Pour l'utilisateur final

Un installeur Windows tout-en-un est produit par `scripts/build-installer.ps1`
(voir [`installer/README.md`](installer/README.md)) :

```
HERMES-Setup-<version>.exe  (~2 Go, Ollama inclus)
```

Double-clic → installation guidée → raccourci bureau créé → utilisable.
Au premier lancement, HERMES télécharge automatiquement le modèle de langage
Mistral 7B (~4,4 Go) avec une barre de progression. Aucune installation
manuelle de Python, Ollama ou autre prérequis n'est nécessaire.

À la fermeture de la fenêtre, le backend et Ollama sont arrêtés
automatiquement. À la désinstallation, l'utilisateur peut conserver ou
supprimer ses données locales (BDD, documents).

---

## Prérequis (développement)

> Pour utiliser HERMES en production, voir « Pour l'utilisateur final »
> ci-dessus — l'installeur s'occupe de tout. Cette section concerne
> le développement sur le projet.

### Obligatoires
- **Python 3.11+** (testé sur 3.12) — sous Windows : `py -3.12`
- **Node.js 18+** et npm
- **git**

### Pour build desktop (Tauri)
- **Rust** (stable) — <https://rustup.rs/>
- **Microsoft Edge WebView2** (préinstallé sur Windows 11)
- **Build Tools C++** (Visual Studio Build Tools 2022 ou supérieur)

### Pour build de l'installeur
- **Inno Setup 6** (gratuit) — <https://jrsoftware.org/isdl.php>
- **PyInstaller** (auto-installé par `scripts/build-backend.ps1`)

### Pour l'analyse IA (Phase 5+)
- Ollama/PYTHIA est utilisé en local sur `127.0.0.1:11434`.
- Dans l'environnement Joshua, l'installation autonome et les modèles sont sous
  `D:\HermesDeps\ollama`.
- Modèles attendus :
  - `mistral:7b-instruct-q4_K_M`
  - `nomic-embed-text`

Les téléchargements lourds liés à HERMES doivent rester sur `D:` quand l'outil le
permet (`D:\HermesDeps`) : modèles Ollama, navigateurs Playwright, caches npm/pip/Cargo.

---

## Arborescence

```
hermes/
├── backend/                 # API FastAPI + agents Python
│   ├── hermes/
│   │   ├── agents/          # ARGOS, KRINOS, HERMION, PYTHIA (client Ollama)
│   │   ├── api/             # routes FastAPI
│   │   ├── db/              # modèles SQLModel + session
│   │   ├── config.py
│   │   └── main.py          # entrée FastAPI
│   ├── hermes_entry.py      # point d'entrée PyInstaller (backend.exe)
│   ├── hermes_entry.spec    # config PyInstaller
│   ├── tests/
│   └── requirements.txt
├── frontend/                # Tauri + React + Tailwind
│   ├── src/                 # React app
│   ├── src-tauri/           # config Tauri (Rust) — sidecar lifecycle
│   └── package.json
├── installer/               # pipeline Inno Setup
│   ├── HERMES.iss           # script d'installeur
│   └── README.md
├── docs/
├── scripts/                 # scripts dev + build
├── tools/HermesLauncher/    # launcher .NET historique (optionnel)
└── Lancer HERMES.exe        # launcher historique (obsolète si hermes.exe en release)
```

---

## Lancement recommandé

Sur Windows, le script PowerShell suivant lance tout l'écosystème et
**tue automatiquement le backend + PYTHIA à la fermeture de la fenêtre** :

```powershell
.\scripts\start-hermes.ps1
```

Il démarre dans l'ordre :

1. **PYTHIA/Ollama** depuis `D:\HermesDeps\ollama\bin` (s'il n'est pas déjà actif)
2. **Backend FastAPI** sur `127.0.0.1:8000`
3. **Application desktop HERMES** via Tauri

Une fois la fenêtre HERMES fermée, le backend et PYTHIA (s'ils ont été
démarrés par le script) sont stoppés proprement.

> Une fois HERMES recompilé en release (`cd frontend && npm run tauri build`),
> le binaire `hermes.exe` gère **lui-même** le cycle de vie : il lance Ollama
> + backend au démarrage et les tue à la fermeture de la fenêtre. Plus besoin
> du launcher .NET — c'est un simple double-clic sur l'icône HERMES.
>
> Le launcher `Lancer HERMES.exe` historique reste fonctionnel pour le moment ;
> son code source (`tools/HermesLauncher/`) a été mis à jour avec un Job
> Object Windows pour kill propre, recompilable via `dotnet build -c Release`
> si tu installes le .NET SDK 8.

### En cas de processus zombies

Si une ancienne instance bloque le port `:8000` ou `:11434` :

```powershell
.\scripts\kill-hermes.ps1
```

### Vérifications utiles

- API : <http://127.0.0.1:8000/health>
- AO collectés : <http://127.0.0.1:8000/appels-offre>
- Modèles Ollama : `D:\HermesDeps\ollama\bin\ollama.exe list`

---

## Démarrage rapide (mode dev)

### Backend
```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn hermes.main:app --reload --host 127.0.0.1 --port 8000
```

Vérifications :
- `http://127.0.0.1:8000/health` → `{"status":"ok",...}`
- `http://127.0.0.1:8000/docs` → Swagger UI

### Frontend (web dev)
```powershell
cd frontend
npm install
npm run dev
```
→ <http://localhost:5173>

### Frontend (desktop Tauri — nécessite Rust)
```powershell
cd frontend
npm run tauri dev
```

### Scripts locaux

```powershell
.\scripts\start-pythia.ps1     # démarre Ollama/PYTHIA depuis D:
.\scripts\start-backend.ps1    # démarre FastAPI avec les chemins HERMES
.\scripts\start-desktop.ps1    # lance Tauri dev avec caches sur D:
.\scripts\start-hermes.ps1     # lance tout + tue à la fermeture (équivalent .exe)
.\scripts\kill-hermes.ps1      # tue les processus HERMES zombies
.\scripts\build-backend.ps1    # compile backend.exe autonome (PyInstaller)
.\scripts\build-installer.ps1  # compile HERMES-Setup-<version>.exe (Inno Setup)
```

### Backend autonome (PyInstaller)

`scripts/build-backend.ps1` produit `D:\HermesDeps\tooling\backend-build\backend\backend.exe`
(~115 Mo, inclut Python + dépendances). Quand ce binaire existe, `hermes.exe`
(release) le démarre **en priorité** au lieu de chercher un venv Python. Pour
l'utilisateur final, cela signifie : pas besoin d'installer Python.

Override via `HERMES_BACKEND_EXE=<chemin>` si tu veux pointer ailleurs.

### Installeur Windows (Inno Setup)

`scripts/build-installer.ps1` orchestre la chaîne complète :

1. `npm run tauri build` → `hermes.exe`
2. `scripts/build-backend.ps1` → `backend\backend.exe`
3. Télécharge `OllamaSetup.exe` depuis ollama.com
4. Compile via `ISCC.exe` (Inno Setup 6)

Sortie : `installer/dist/HERMES-Setup-<version>.exe`. Voir
[`installer/README.md`](installer/README.md) pour les options
(`-SkipFrontend`, `-SkipBackend`, `-SkipOllama` pour itérer plus vite).

---

## Fonctionnalités disponibles

- **Profil utilisateur configurable** au premier lancement et dans Paramètres.
  HERMION pourra utiliser le nom, prénom et email localement pour rédiger les
  réponses.
- **ARGOS réel** : collecte BOAMP via l'API publique DILA et persistance dans
  SQLite/MNEMOSYNE.
- **Filtrage ARGOS** : mots-clés inclus/exclus configurables dans
  *Paramètres → Critères de filtrage*. Les AO non pertinents sont rejetés
  avant insertion. Routes `GET/PUT /argos/filtre`.
  Le filtre est bien partagé entre frontend et backend : l'UI enregistre les
  critères dans MNEMOSYNE via l'API, et le runner ARGOS les recharge à chaque
  collecte avant d'insérer les AO. Le scraper ne filtre pas lui-même ; le
  filtrage est centralisé dans le runner.
- **Limite ARGOS multi-portails** : le seul scraper réel actuellement
  enregistré est `boamp`. L'interface Paramètres affiche désormais les scrapers
  réellement exposés par le backend au lieu de portails statiques. PLACE, TED,
  AWS Achat, Achat Solutions ou Maximilien ne seront collectés qu'après ajout
  d'un scraper backend dédié dans le registre ARGOS.
- **Onglet Veille connecté au backend** : les AO affichés viennent de
  `/appels-offre`, pas des données mock.
- **Qualification AO persistée** : depuis la Veille, les actions
  « Marquer à répondre » et « Exclure » appellent l'API et mettent à jour le
  statut MNEMOSYNE (`a_repondre` / `rejete`).
- **Portails lisibles** : l'API enrichit les AO avec le nom du portail
  (`BOAMP`, etc.) au lieu d'exposer seulement l'identifiant technique.
- **KRINOS extraction documentaire** : socle d'extraction PDF/XLSX/DOCX/HTML et
  téléchargement de documents.
- **KRINOS analyse IA (PYTHIA)** : résumé, score 0-100, tags métier et critères
  d'attribution générés en local par Mistral 7B via Ollama. Endpoints
  `POST /krinos/appels-offre/{id}/analyser` et `GET …/analyse`.
- **Pondération KRINOS configurable** : les poids par dimension de scoring sont
  persistés et utilisés au prochain calcul de score. Les analyses stockent les
  scores par dimension, la fiche AO affiche cette ventilation avec les poids
  courants, et l'action « Recalculer score » permet d'appliquer une nouvelle
  pondération sans relancer PYTHIA quand ces scores sont disponibles.
- **HERMION rédaction IA** : génération d'une réponse markdown multi-sections
  (plan puis rédaction section par section) en local via PYTHIA. Versionnement
  (`v1`, `v2`, …), validation humaine obligatoire (statut `en_attente` jusqu'à
  approbation explicite). Endpoints `/hermion/appels-offre/{id}/rediger`,
  `/hermion/reponses/{id}`, `…/statut`, `…/contenu`.
- **Onglet « Réponses » connecté au backend** : liste live filtrée par statut
  (en attente, à modifier, validées, rejetées, exportées), aperçu markdown,
  édition inline du contenu, actions valider / demander révision / rejeter
  avec propagation au statut de l'AO (`repondu` à la validation). Endpoint
  `GET /hermion/reponses` joint avec les métadonnées AO.
- **Téléchargement modèle au 1er run** : si le modèle Mistral 7B n'est pas
  encore présent, un modal d'onboarding affiche une barre de progression
  `Go / Go` pendant le pull Ollama. Endpoints `/pythia/modele/status` et
  `/pythia/modele/telecharger`.
- **Cycle de vie complet** : en release, `hermes.exe` démarre Ollama + backend
  comme sidecars et les tue à la fermeture — aucun processus zombie.
- **Backend autonome (`backend.exe`)** : 115 Mo via PyInstaller, sans
  dépendance Python externe.
- **Installeur Windows** : `HERMES-Setup-<version>.exe` (~2 Go, Ollama inclus)
  pour distribution à un utilisateur final.

---

## Avancement (plan 10 phases)

- [x] **Phase 1** — Fondations (Tauri shell + FastAPI + SQLite + MNEMOSYNE)
- [x] **Phase 2** — ARGOS scraping basique (BOAMP via API DILA, APScheduler)
- [x] **Phase 3** — ARGOS authentification Playwright (socle credentials chiffrés)
- [x] **Phase 4** — KRINOS extraction documents
- [x] **Phase 5** — KRINOS IA (PYTHIA — résumé + score + tags via Mistral 7B)
- [x] **Phase 6** — Interface onglet 1 « Veille » (**MVP**)
- [x] **Phase 6.1** — Actions Veille persistées (statuts AO + nom portail)
- [x] **Phase 7** — HERMION rédaction (plan + sections, versionnement, validation humaine)
- [x] **Phase 8** — Interface onglet 2 « Réponses » (liste live, édition markdown, transitions de statut)
- [x] **Phase 9** — Paramètres & configuration utilisateur
- [~] **Phase 10** — Finalisation : sidecar Tauri ✅, backend.exe ✅,
  téléchargement modèle 1er run ✅, installeur Inno Setup ✅ ; reste
  export PDF et envoi mail

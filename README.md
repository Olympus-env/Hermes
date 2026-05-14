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

## Prérequis

### Obligatoires
- **Python 3.11+** (testé sur 3.12) — sous Windows : `py -3.12`
- **Node.js 18+** et npm
- **git**

### Pour build desktop (Tauri)
- **Rust** (stable) — <https://rustup.rs/>
- **Microsoft Edge WebView2** (préinstallé sur Windows 11)
- **Build Tools C++** (Visual Studio Build Tools 2022 ou supérieur)

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
│   │   ├── agents/          # ARGOS, KRINOS, HERMION
│   │   ├── api/             # routes FastAPI
│   │   ├── db/              # modèles SQLModel + session
│   │   ├── config.py
│   │   └── main.py          # entrée FastAPI
│   ├── tests/
│   └── requirements.txt
├── frontend/                # Tauri + React + Tailwind
│   ├── src/                 # React app
│   ├── src-tauri/           # config Tauri (Rust)
│   └── package.json
├── docs/
├── scripts/                 # scripts dev / lancement local
├── tools/HermesLauncher/    # source du launcher Windows
└── Lancer HERMES.exe        # launcher local : backend + PYTHIA + desktop
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
.\scripts\start-pythia.ps1    # démarre Ollama/PYTHIA depuis D:
.\scripts\start-backend.ps1   # démarre FastAPI avec les chemins HERMES
.\scripts\start-desktop.ps1   # lance Tauri dev avec caches sur D:
.\scripts\build-backend.ps1   # compile backend.exe autonome (PyInstaller)
.\scripts\start-hermes.ps1    # lance tout + tue à la fermeture (équivalent .exe)
.\scripts\kill-hermes.ps1     # tue les processus HERMES zombies
```

### Backend autonome (PyInstaller)

`scripts/build-backend.ps1` produit `D:\HermesDeps\tooling\backend-build\backend\backend.exe`
(~115 Mo, inclut Python + dépendances). Quand ce binaire existe, `hermes.exe`
(release) le démarre **en priorité** au lieu de chercher un venv Python. Pour
l'utilisateur final, cela signifie : pas besoin d'installer Python.

Override via `HERMES_BACKEND_EXE=<chemin>` si tu veux pointer ailleurs.

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
- **HERMION rédaction IA** : génération d'une réponse markdown multi-sections
  (plan puis rédaction section par section) en local via PYTHIA. Versionnement
  (`v1`, `v2`, …), validation humaine obligatoire (statut `en_attente` jusqu'à
  approbation explicite). Endpoints `/hermion/appels-offre/{id}/rediger`,
  `/hermion/reponses/{id}`, `…/statut`, `…/contenu`.
- **Desktop Tauri** : build Windows généré sous
  `D:\HermesDeps\tooling\cargo-target\release`.

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
- [ ] **Phase 8** — Interface onglet 2 « Réponses »
- [x] **Phase 9** — Paramètres & configuration utilisateur
- [ ] **Phase 10** — Finalisation (auto-start, export, mail)

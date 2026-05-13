# CLAUDE.md — Guide projet HERMES pour Claude Code

Ce document est un mémo persistant à destination de Claude, lu automatiquement à
chaque session ouverte sur ce dépôt. Il complète la mémoire utilisateur globale
et donne les conventions propres à HERMES.

---

## 🎯 Vision en une phrase

HERMES est une **application desktop 100 % locale** de veille et réponse aux
appels d'offre — zéro cloud, zéro coût récurrent, validation humaine obligatoire
avant toute soumission.

## 🧭 Boussole : 3 invariants non négociables

1. **Local-first** — aucune donnée ne sort de la machine. FastAPI n'écoute que
   sur `127.0.0.1`, jamais sur `0.0.0.0`. Aucune télémétrie. Aucun appel
   externe sauf vers les portails AO ciblés.
2. **Validation humaine obligatoire** — la soumission finale d'une réponse à un
   AO est *exclusivement* humaine, sans exception. HERMION rédige, ne soumet
   jamais.
3. **Zéro abonnement** — pas de SaaS, pas d'API payante. Tout tourne en local
   (LLM via Ollama, BDD SQLite, etc.).

Toute proposition d'architecture doit respecter ce triptyque.

---

## 🏛️ Nomenclature mythologique

| Nom | Rôle |
|-----|------|
| **HERMES** | L'application complète (l'orchestrateur) |
| **ARGOS** | Agent de collecte / scraping (Playwright + APScheduler) |
| **KRINOS** | Agent d'analyse / extraction / scoring (pdfplumber + pymupdf + Ollama) |
| **HERMION** | Agent de rédaction (Ollama + workflow engine) |
| **MNEMOSYNE** | La base SQLite locale |
| **PYTHIA** | Le LLM local (Ollama + Mistral 7B Instruct q4_K_M) |

**Toujours utiliser ces noms** dans le code, les commentaires, les noms de
modules et les logs. C'est l'identité du projet.

---

## 🧰 Stack technique

- **Backend** : Python 3.12 + FastAPI 0.115 + SQLModel 0.0.22 + Uvicorn
- **Frontend** : Vite 5 + React 18 + TypeScript 5 + Tailwind 3
- **Desktop** : Tauri 2 (Rust) — wrapper natif
- **BDD** : SQLite (mode WAL) via SQLModel
- **Scraping** : Playwright Python + APScheduler
- **LLM** : Ollama (HTTP local sur 11434) + Mistral 7B Instruct q4_K_M
- **Crypto** : `cryptography` (AES-256, GCM)

---

## 🖥️ Spécificités environnement Joshua (Windows 11)

- Le `python` du PATH est **3.7.2** (trop ancien) → toujours utiliser :
  - `py -3.12` pour invoquer Python directement
  - ou activer le venv : `.\backend\.venv\Scripts\Activate.ps1`
- Shell par défaut : **PowerShell 7** (utiliser syntaxe PowerShell, pas bash).
- L'API Bash via WSL/Git Bash est dispo mais les chemins Windows se traduisent
  en `/e/Hermes/...`.

---

## 🚀 Commandes courantes

### Backend
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn hermes.main:app --host 127.0.0.1 --port 8000 --reload
pytest tests -v
```

### Frontend (web dev)
```powershell
cd frontend
npm run dev          # Vite sur http://127.0.0.1:5173
npm run build        # production build
```

### Frontend (desktop Tauri — exige Rust + VS Build Tools)
```powershell
cd frontend
npm install @tauri-apps/cli @tauri-apps/api    # à faire une fois
npm run tauri dev
npm run tauri build
```

### LLM
```powershell
ollama serve                                 # démarre le daemon
ollama pull mistral:7b-instruct-q4_K_M       # ~4.4 Go, à faire une fois
ollama pull nomic-embed-text                 # pour les embeddings
```

---

## 📐 Conventions de code

### Python (backend)
- **Pas de `from __future__ import annotations` dans `db/models.py`** —
  SQLModel/SQLAlchemy introspectent les annotations à l'exécution et ont besoin
  des types réels (pas des chaînes). Sinon `list["AppelOffre"]` casse au mapping.
- Datetimes : **timezone-aware UTC** (`datetime.now(timezone.utc)`), jamais
  `datetime.utcnow()` (déprécié en 3.12).
- Tous les noms publics en **français** (variables, endpoints, tables) — c'est
  la langue de travail du projet et de l'utilisateur final.
- Pour les relations SQLModel : utiliser `List` (typing) plutôt que `list` natif
  pour garder l'introspection SQLAlchemy heureuse.

### TypeScript (frontend)
- Strict mode activé partout.
- Composants nommés en **français** (`Veille`, `Reponses`, `StatusBar`).
- Pas de dépendance UI lourde (pas de Material-UI, etc.) — Tailwind suffit.

### Sécurité
- **Credentials portails** : chiffrement AES-256 dans `portails.credentials_chiffres`
  (BLOB), jamais en clair.
- **Clé maître** : générée au premier lancement, dérivée de la machine, stockée
  hors VCS.
- **Checksum SHA-256** sur chaque document téléchargé (`documents.checksum_sha256`).
- **CSP Tauri** : `connect-src` limité à `127.0.0.1:8000` et `localhost:8000`.

### Git
- Commits en français, sujet < 70 caractères.
- Inclure le co-author Claude dans les commits de session.
- `.gitignore` exclut `data/`, `*.db`, `.env`, `node_modules/`, `target/`, etc.

---

## 🔢 Schéma BDD MNEMOSYNE (8 tables)

Définies dans `backend/hermes/db/models.py`.

| Table | Rôle |
|-------|------|
| `portails` | Sources de scraping (BOAMP, TED, achatpublic, etc.) |
| `appels_offre` | Table centrale — un AO détecté |
| `documents` | Fichiers téléchargés (PDF/xlsx/html) liés à un AO |
| `analyses_krinos` | Résumés + score 0-100 + tags par AO |
| `reponses_hermion` | Versions de réponse rédigées (multi-versions) |
| `base_connaissances` | Index vectoriel (AO validés + docs réf., embeddings BLOB) |
| `parametres` | Config applicative clé/valeur |
| `logs_agents` | Journal d'actions ARGOS/KRINOS/HERMION |

### Statuts d'AO (enum `StatutAO`)
`brut` → `analyse` → `a_repondre` → `en_redaction` → `repondu` | `rejete` | `expire`

### Statuts de réponse (enum `StatutReponse`)
`en_generation` → `en_attente` → (`a_modifier` ↺ | `validee` | `rejetee`) → `exportee`

---

## 🛣️ Plan 10 phases (avancement réel)

| # | Phase | État |
|---|-------|------|
| 1 | Fondations (Tauri + FastAPI + SQLite) | ✅ |
| 2 | ARGOS scraping basique | en cours |
| 3 | ARGOS authentification Playwright | |
| 4 | KRINOS extraction docs | |
| 5 | KRINOS IA (PYTHIA) | |
| 6 | Interface onglet 1 « Veille » — **MVP** | |
| 7 | HERMION rédaction | |
| 8 | Interface onglet 2 « Réponses » | |
| 9 | Paramètres & configuration | |
| 10 | Finalisation (auto-start, export PDF, mail) | |

L'état authoritatif est dans le README + `git log` — toujours vérifier avant
d'annoncer une avancée.

---

## 📚 Documents de référence

- **Cahier des charges officiel** : `HERMES_CDC_v1.0.pdf` à la racine.
- **README.md** : démarrage rapide + prérequis utilisateur.
- **`docs/`** : documents techniques additionnels au fil du dev.

---

## ⚠️ Pièges connus

- **SQLModel + `from __future__ import annotations`** : casse les relations
  (`list["X"]` traité comme string). Garder les imports classiques dans
  `models.py`.
- **CORS** : le frontend Vite tourne sur `localhost:5173`, le backend sur
  `127.0.0.1:8000`. `localhost` et `127.0.0.1` sont des origines distinctes pour
  CORS — l'allow-list inclut les deux.
- **Playwright** : après `pip install playwright`, ne pas oublier
  `playwright install chromium` pour télécharger le navigateur (~150 Mo).
- **Ollama sous Windows** : démarre comme service automatiquement. Tester avec
  `curl http://127.0.0.1:11434/api/tags`.
- **Tauri Windows** : exige **MS Build Tools 2022** (composant « Desktop dev
  with C++ ») en plus de Rust. Sans ça, `npm run tauri dev` échoue à la
  compilation.

---

## 🤝 Style de collaboration

L'utilisateur (Joshua) est francophone et a partagé un CDC complet : il sait ce
qu'il veut. Il préfère :
- réponses en français,
- avancées concrètes plutôt que longues clarifications,
- commits réguliers et rapports synthétiques en fin de session,
- l'autonomie : « fait ce que tu veux » signifie réellement « décide et avance ».

Demander confirmation uniquement pour les **actions à fort impact** (installation
système majeure, suppression, push, choix d'architecture irréversible).

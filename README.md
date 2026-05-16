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

## Installation (utilisateur final)

> Windows 10/11 64 bits. Aucun prérequis : ni Python, ni Node, ni Rust, ni
> Ollama à installer — l'installeur s'occupe de tout.

1. **Télécharger** le dernier installeur depuis la page des releases :
   <https://github.com/Olympus-env/Hermes/releases/latest> →
   fichier `HERMES-Setup-<version>.exe` (**~800 Mo**, Ollama embarqué).
2. **Double-cliquer** sur le fichier téléchargé → installation guidée →
   raccourci Bureau + entrée menu Démarrer créés.
3. **Lancer HERMES.** Au tout premier démarrage, l'application télécharge
   automatiquement le modèle de langage Mistral 7B (**~4,4 Go**, barre de
   progression). Cette étape nécessite une connexion internet **une seule
   fois** ; ensuite HERMES fonctionne 100 % hors-ligne.

> Une variante allégée d'installeur (~120 Mo, sans Ollama embarqué) peut être
> publiée : dans ce cas Ollama doit être installé séparément. Le nom du
> fichier sur la release précise le contenu.

Pas de page Releases / pas encore de version publiée ? Voir
[« Installeur Windows (Inno Setup) »](#installeur-windows-inno-setup) pour
construire l'installeur depuis les sources (chaîne développeur).

À la fermeture de la fenêtre, le backend et Ollama sont arrêtés
automatiquement. À la désinstallation, l'utilisateur peut conserver ou
supprimer ses données locales (BDD, documents).

Sur une machine utilisateur, les données HERMES sont stockées dans
`%LocalAppData%\HERMES` : base SQLite, documents, logs, clé maître locale et
modèles Ollama téléchargés par HERMES. L'application installée ne dépend pas
des chemins de développement `E:\Hermes` ou `D:\HermesDeps`.

---

## Prérequis (développement)

> Pour simplement utiliser HERMES, voir « Installation (utilisateur final) »
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
Les scripts de build acceptent aussi `-DepsRoot <chemin>` ou la variable
`HERMES_DEPS_DIR` pour utiliser un autre disque de travail.

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

### Ports locaux

En développement, trois services locaux peuvent être ouverts :

| Port | Service | Rôle |
|------|---------|------|
| `8000` | Backend FastAPI HERMES | API locale (`/health`, `/appels-offre`, `/hermion`, etc.) |
| `5173` | Frontend Vite React | Interface web de développement |
| `11434` | Ollama / PYTHIA | LLM local utilisé par KRINOS et HERMION |

Ces ports doivent rester liés à `127.0.0.1`. Ils servent au développement local
et ne doivent pas être exposés sur le réseau.

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
→ <http://127.0.0.1:5173>

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

`scripts/build-backend.ps1` produit par défaut
`D:\HermesDeps\tooling\backend-build\backend\backend.exe` (~115 Mo, inclut
Python + dépendances). Le dossier peut être changé via `-DepsRoot` ou
`HERMES_DEPS_DIR`. Quand ce binaire est copié dans l'installeur, `hermes.exe`
(release) le démarre **en priorité** au lieu de chercher un venv Python. Pour
l'utilisateur final, cela signifie : pas besoin d'installer Python.

Overrides dev/debug disponibles : `HERMES_BACKEND_EXE=<chemin>`,
`HERMES_OLLAMA_EXE=<chemin>`, `HERMES_DATA_DIR=<chemin>`.

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
- **ARGOS réel** : collecte BOAMP via l'API publique DILA et TED Europa via
  l'API publique v3, puis persistance dans SQLite/MNEMOSYNE.
- **Filtrage ARGOS** : mots-clés inclus/exclus configurables dans
  *Paramètres → Critères de filtrage*. Les AO non pertinents sont rejetés
  avant insertion. Routes `GET/PUT /argos/filtre`.
  Le filtre est bien partagé entre frontend et backend : l'UI enregistre les
  critères dans MNEMOSYNE via l'API, et le runner ARGOS les recharge à chaque
  collecte avant d'insérer les AO. Le scraper ne filtre pas lui-même ; le
  filtrage est centralisé dans le runner.
- **Limite ARGOS multi-portails** : les scrapers réels actuellement enregistrés
  sont `boamp` et `ted`. L'interface Paramètres affiche les scrapers réellement
  exposés par le backend au lieu de portails statiques. PLACE, Achat Public,
  Marches.fr, AWS Achat, Achat Solutions ou Maximilien ne seront collectés
  qu'après ajout d'un scraper backend dédié dans le registre ARGOS.
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
  Les timeouts HERMION sont séparés de KRINOS : plan `180 s`, section `420 s`
  par défaut, avec bonus configurable par longueur cible. Une réponse longue
  est possible, mais sa qualité dépend du workflow MNEMOSYNE, du profil et des
  documents disponibles ; sans contexte métier, HERMION peut produire une
  réponse longue mais générique.
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
- **Installeur Windows** : `HERMES-Setup-<version>.exe` (~800 Mo, Ollama
  embarqué) publié sur GitHub Releases pour l'utilisateur final.

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
  téléchargement modèle 1er run ✅, installeur Inno Setup ✅. Le reste est
  désormais réorganisé dans le **Périmètre V1** ci-dessous (export PDF,
  pipeline autonome, multi-portails publics… ; email repoussé en V2).

---

## Lecture CDC v1.0 — état d'implémentation

Cette section consolide l'écart entre le cahier des charges
`HERMES_CDC_v1.0.pdf`, le code actuellement présent et les besoins probables
d'un usage commercial réel.

### Ce qui est déjà couvert

- **Socle local conforme** : application desktop Tauri/React, backend FastAPI
  lié à `127.0.0.1`, SQLite/MNEMOSYNE, PYTHIA/Ollama local, sans télémétrie ni
  dépendance cloud.
- **Cycle de vie desktop** : `hermes.exe` peut démarrer Ollama + backend et les
  arrêter à la fermeture ; scripts PowerShell de secours disponibles.
- **ARGOS MVP** : collecte BOAMP réelle via API publique DILA et TED Europa
  via API publique v3, dédoublonnage, journalisation, stockage MNEMOSYNE,
  scheduler APScheduler, configuration des portails côté API, socle
  credentials chiffrés.
- **Filtrage ARGOS MVP** : mots-clés inclus/exclus persistés, suggestion IA via
  PYTHIA, application avant insertion par le runner.
- **KRINOS MVP+** : téléchargement/référencement de documents, extraction
  PDF/XLSX/DOCX/HTML, analyse IA locale, résumé, score, justification, tags,
  scores par dimension et recalcul pondéré sans relancer PYTHIA.
- **HERMION MVP** : génération multi-sections, versionnement, statuts de
  validation, édition manuelle, rejet/demande de modification/validation
  humaine, aucun mécanisme de soumission automatique.
- **Interface MVP** : onboarding, onglet Veille, panneau AO, onglet Réponses,
  paramètres profil/filtre/scoring/portails, téléchargement du modèle au
  premier lancement.
- **Distribution** : backend PyInstaller, build Tauri release, installeur Inno
  Setup, stockage des dépendances lourdes sur `D:`.

### Écarts CDC encore ouverts

- **ARGOS multi-portails** : BOAMP et TED Europa sont opérationnels. Les autres
  portails publics ou authentifiés demandés par le CDC (Achat Public,
  Marches.fr, AWS Marketplace, portails clients…) nécessitent chacun un scraper
  dédié, des tests parser et une intégration registre.
- **Portails authentifiés complets** : le socle Playwright/chiffrement existe,
  mais il manque le vrai flux de capture de session, la détection d'expiration,
  la reconnexion interactive et les alertes UI.
- **Filtres avancés** : le CDC demande mots-clés, secteur/codes NAF, zone,
  budget min/max, délai minimum, émetteurs liste blanche/noire et type de
  marché. Aujourd'hui, seuls inclus/exclus textuels sont opérationnels.
- **Fiabilité ARGOS** : retry réseau avec backoff, rattrapage au redémarrage,
  watchdog, état détaillé par portail et journal consultable depuis l'UI sont
  encore à compléter.
- **KRINOS extraction avancée** : l'extraction existe, mais il manque OCR pour
  PDF scannés, vérification d'intégrité SHA-256 à chaque lecture, extraction
  structurée plus complète des champs clés et chaîne automatique
  téléchargement → extraction → analyse.
- **Grille scoring CDC** : la pondération actuelle fonctionne, mais ses
  dimensions métier diffèrent de la grille CDC initiale
  (mots-clés/secteur/budget/délai/zone). Il faut choisir entre conserver la
  grille actuelle ou migrer vers la grille CDC.
- **HERMION workflow utilisateur avancé** : le workflow onboarding/paramètres
  existe avec sections, briefs, consignes globales et longueurs cibles. Il
  manque encore l'import direct JSON/MD, les variables `{{champ}}`, les
  révisions guidées par commentaire et une gestion plus fine du ton/style.
- **Base de connaissances HERMION** : les tables existent, mais il manque
  l'import de documents de référence, l'indexation embeddings, la recherche
  sémantique locale et l'injection des 3 à 5 sources pertinentes sans citation.
- **Priorisation HERMION** : le CDC prévoit que HERMION récupère et priorise
  les AO à répondre selon score + deadline. Aujourd'hui, l'utilisateur lance la
  rédaction depuis un AO.
- **Exports et mails** : export PDF, envoi mail des réponses, mail
  récapitulatif ARGOS et configuration SMTP sont encore absents.
- **Notifications OS** : les notifications natives d'une réponse prête, d'une
  session expirée ou d'un cycle ARGOS échoué ne sont pas encore branchées.
- **Rétention et sauvegardes** : pas encore de purge automatique des logs,
  archivage des AO rejetés après 90 jours, sauvegarde quotidienne de la BDD ou
  purge documentaire manuelle.
- **Paramètres système** : chemins BDD/stockage/logs, modèle Ollama,
  température, longueur max et démarrage automatique OS ne sont pas encore
  pilotables depuis l'UI.

---

## Périmètre V1 (verrouillé le 2026-05-16)

La V1 vise un **pipeline 100 % autonome** : ARGOS collecte → filtre →
KRINOS note/tague/résume → **sans intervention humaine**, les AO les mieux
notés passent en queue HERMION → réponses générées via MNEMOSYNE + workflow →
l'utilisateur critique et exporte. L'**email/SMTP est repoussé en V2**, ainsi
que toutes les fonctionnalités « vraiment avancées ».

### V1 — livré (2026-05-16)

- [x] **ARGOS multi-portails publics** — BOAMP (DILA) + **TED Europa** (API v3
  publique sans auth). Décision : ce sont les 2 sources officielles libres ;
  Achat Public/Marches.fr/PLACE (pas d'API libre) → V2. `fd8b3c4`
- [x] **Orchestration autonome** — après chaque cycle ARGOS : filtre → KRINOS
  (docs → extraction → analyse → score/tags/résumé) → bascule des AO au-dessus
  d'un **seuil configurable** vers HERMION, sans clic humain. `798d100`
- [x] **Onboarding étendu + workflow IA** — l'utilisateur fournit un workflow
  ou des réponses exemples ; PYTHIA en dérive un workflow corrigeable
  (onboarding étape 4 + Paramètres → Rédaction HERMION). `429e9bb`
- [x] **Export PDF** des réponses validées (`chemin_export`, 100 % local
  via fpdf2). `e82dfc9`
- [x] **Journal des agents dans l'UI** — onglet Journal filtrable. `e28b644`
- [x] **Notifications in-app** — centre alimenté par le journal (pastille +
  panneau Topbar). Les **vraies notifications OS** sont repoussées en V2. `eeebcda`
- [→ V2] **Démarrage automatique au login Windows** — repoussé : exige un
  plugin Tauri/Rust non compilable dans l'environnement actuel.

Validation : 131 tests backend verts, build frontend vert. Validation locale
complémentaire le 2026-05-16 : `pip install -r requirements.txt` OK avec
`fpdf2`, services locaux `8000`/`5173`/`11434` OK, collecte réelle BOAMP+TED OK,
KRINOS avec Ollama réel OK, HERMION réel OK sur une réponse de 1 705 mots.
Validation release complémentaire : `backend.exe` PyInstaller construit et
démarré sans Python externe sur port temporaire, `cargo check --release` Tauri
vert, runtime Tauri aligné sur `%LocalAppData%\HERMES` et chemins Ollama
standards.
Réutilisé tel quel : filtre mots-clés, KRINOS, versionnement HERMION, onglets
Veille/Réponses, installeur Windows.

## V2 — repoussé (« vraiment avancé »)

- **Email/SMTP** : envoi mail des réponses, mail récap ARGOS, config SMTP.
- **Intégration OS native (Tauri/Rust)** : vraies notifications système
  (plugin `tauri-plugin-notification`) et démarrage automatique au login
  Windows (`tauri-plugin-autostart`). En V1, notifications in-app à la place.
- **Portails authentifiés** : capture de session Playwright réelle, détection
  d'expiration, reconnexion, alertes UI.
- **Filtres avancés** : codes NAF, budget min/max, zone, délai minimum, type
  de marché, émetteurs liste blanche/noire, profils de filtre.
- **Base de connaissances** : import docs de référence, embeddings
  `nomic-embed-text`, recherche sémantique (au-delà du workflow seed V1).
- **KRINOS robuste** : OCR PDF scannés, vérification checksum à chaque lecture,
  extraction structurée fine, historique/comparaison d'analyses.
- **HERMION avancé** : import workflow JSON/MD, variables `{{champ}}`,
  révisions guidées par commentaire utilisateur, meilleure injection de
  contexte MNEMOSYNE/base de connaissances pour éviter les réponses longues
  mais trop génériques.
- **Pilotage commercial** : pipeline go/no-go, motifs de perte, tableau de
  bord, calendrier d'échéances, fiches acheteur, exports CSV.
- Reste des « besoins extrapolés » et suggestions UI/UX ci-dessous.

---

## Besoins extrapolés hors CDC

Ces besoins ne sont pas explicitement demandés dans le CDC, mais deviendront
probablement importants pour une équipe commerciale.

- **Go/No-Go assisté** : décision rapide avec raisons structurées
  (fit métier, budget, délai, références disponibles, charge estimée, risques).
- **Estimation d'effort de réponse** : temps commercial/avant-vente estimé,
  complexité documentaire, nombre de pièces à produire.
- **Checklist de dépôt** : pièces administratives, mémoire technique, DUME,
  attestations, signatures, références, bordereaux de prix.
- **Gestion des responsabilités** : assigner un AO à un commercial ou à un
  expert, même en usage local mono-poste.
- **Historique acheteur** : retrouver les précédents AO d'un même émetteur et
  les décisions prises.
- **Capitalisation commerciale** : transformer une réponse validée en source de
  connaissance réutilisable après validation.
- **Analyse de concurrence implicite** : mémoriser attributaires/perdants si
  renseignés manuellement, sans scraping agressif ni cloud.
- **Modes de rédaction** : réponse courte, mémoire technique, note de synthèse,
  mail de qualification interne, liste de questions à poser à l'acheteur.
- **Pack de revue humaine** : signaler les passages à vérifier, les hypothèses
  et les zones où HERMION manque d'informations.
- **Confidentialité renforcée** : bouton "purger ce dossier", export chiffré,
  verrouillage de l'application par mot de passe local.

---

## Suggestions d'amélioration UI/UX

### Qualité de vie immédiate

- Bouton "Analyser avec KRINOS" visible dans la fiche AO, distinct de
  "Rédiger une réponse".
- Bouton "Télécharger DCE" réellement branché à KRINOS downloader.
- Badges clairs : "non analysé", "documents manquants", "analyse prête",
  "réponse générée", "validée".
- Tri par défaut configurable : deadline, score, date de collecte, montant.
- Raccourcis clavier simples : ouvrir AO, marquer à répondre, exclure,
  lancer analyse.
- Filtres enregistrés dans l'onglet Veille.
- Toasts plus détaillés avec lien direct vers l'AO ou la réponse concernée.
- État "PYTHIA occupée" pour éviter que l'utilisateur lance plusieurs tâches
  lourdes en parallèle sans visibilité.

### Aide à la décision commerciale

- Score décomposé en deux colonnes : "opportunité" et "risque".
- Résumé exécutif en 5 lignes : besoin, acheteur, budget, deadline, décision
  recommandée.
- Rubrique "Pourquoi répondre ?" et "Pourquoi ne pas répondre ?".
- Détection clauses bloquantes : certifications, délais courts, pénalités,
  références obligatoires, présence locale.
- Estimation de probabilité de succès, explicitement présentée comme aide et
  non comme vérité.

### Suivi et reporting

- Vue calendrier hebdomadaire des échéances.
- Tableau "à traiter aujourd'hui".
- Export CSV du pipeline.
- Rapport hebdomadaire local : nouveaux AO, AO exclus, AO à répondre, réponses
  validées, délais critiques.
- Tags commerciaux personnalisables : stratégique, récurrent, partenaire,
  faible marge, référence utile.

### Robustesse et transparence IA

- Afficher le modèle PYTHIA utilisé, la durée, et si le résultat vient d'une
  ancienne analyse.
- Bouton "Voir prompt/contexte" en mode debug local.
- Indicateur de confiance sur extraction documentaire.
- Comparaison entre score initial et score recalculé après changement de
  pondération.
- Journal des décisions humaines pour entraîner les futurs filtres/scorings
  locaux.

### Fonctionnalités possibles, même mineures

- Favoris / épingler un AO.
- Notes internes par AO et par réponse.
- Pièces jointes manuelles dans une fiche AO.
- Copier le résumé KRINOS dans le presse-papiers.
- Générer un mail interne "avis de go/no-go".
- Générer une liste de questions à poser pendant la phase de clarification.
- Détecter automatiquement les dates de visite obligatoire.
- Alerte si deadline tombe un week-end ou un jour férié français.
- Mode "démo" avec données fictives réinitialisables.
- Assistant de nettoyage de données locales : purger logs, documents, AO
  rejetés, réponses rejetées.

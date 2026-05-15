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
- **ARGOS MVP** : collecte BOAMP réelle via API publique DILA, dédoublonnage,
  journalisation, stockage MNEMOSYNE, scheduler APScheduler, configuration des
  portails côté API, socle credentials chiffrés.
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

- **ARGOS multi-portails** : le CDC demande plusieurs portails publics et
  authentifiés ; le code ne collecte réellement que BOAMP. TED, Achat Public,
  Marches.fr, AWS Marketplace ou portails clients nécessitent chacun un scraper
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
- **HERMION workflow utilisateur** : pas encore d'import de workflow JSON/MD,
  de sections obligatoires paramétrables, de variables `{{champ}}`, de longueur
  cible par section ni de ton/style configurable en paramètres.
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

## Phases suivantes proposées

### Phase 10 — Finalisation CDC courte

Objectif : finir les éléments explicitement promis dans le plan CDC v1.0.

- Export PDF des réponses validées, avec `chemin_export` renseigné.
- Envoi mail manuel d'une réponse validée, après validation humaine.
- Configuration SMTP locale dans Paramètres.
- Notifications OS : réponse prête, cycle ARGOS terminé/échoué, session
  portail expirée.
- Démarrage automatique optionnel au login Windows.
- Journal agents consultable depuis l'interface.

### Phase 11 — ARGOS multi-portails fiable

Objectif : transformer ARGOS d'un collecteur BOAMP en vrai moteur de veille.

- Ajouter scrapers publics : TED Europa, Achat Public, Marches.fr ou autre
  portail prioritaire.
- Ajouter une interface de configuration par portail réellement branchée au
  registre backend.
- Implémenter capture Playwright réelle pour un portail authentifié pilote.
- Ajouter retry/backoff, rattrapage après échec et statut détaillé par portail.
- Ajouter tests offline par portail à partir de snapshots HTML/JSON.

### Phase 12 — Filtres commerciaux avancés

Objectif : permettre à un commercial de réduire fortement le bruit.

- Étendre le modèle de filtre : mots-clés ET/OU, exclus, codes NAF/tags,
  zone, budget min/max, délai minimum, type marché, émetteurs favoris/exclus.
- Prévisualiser l'impact d'un filtre sur les AO déjà en base.
- Ajouter profils de filtre sauvegardables par marché ou offre commerciale.
- Ajouter scoring séparé "fit commercial" vs "risque opérationnel".

### Phase 13 — KRINOS automatique et plus robuste

Objectif : rendre l'analyse moins manuelle et plus fiable.

- Pipeline automatique après collecte : documents → extraction → analyse.
- OCR pour PDF scannés.
- Vérification checksum avant lecture et alerte si document modifié.
- Extraction structurée des critères d'attribution prix/technique, budget,
  allotissement, pièces attendues, clauses éliminatoires.
- Historique des analyses et comparaison entre versions.

### Phase 14 — HERMION workflow et base de connaissances

Objectif : passer d'un rédacteur générique à un assistant commercial cadré.

- Import workflow JSON/Markdown depuis Paramètres.
- Variables dynamiques `{{emetteur}}`, `{{objet}}`, `{{budget}}`,
  `{{date_limite}}`, `{{score}}`, etc.
- Import docs de référence : plaquette, CV, certifications, références clients,
  mémoires techniques passés.
- Embeddings locaux via `nomic-embed-text`, stockage MNEMOSYNE et recherche
  sémantique.
- Génération de révisions à partir d'un commentaire utilisateur avec création
  d'une nouvelle version.

### Phase 15 — Pilotage commercial

Objectif : adapter HERMES au quotidien de commerciaux qui doivent arbitrer vite.

- Pipeline commercial : nouveau → qualifié → go/no-go → réponse en cours →
  déposée manuellement → gagné/perdu.
- Motifs de rejet et de perte standardisés.
- Tableau de bord : deadlines, valeur estimée du pipe, taux de réponse, taux
  de transformation, marchés à risque.
- Vue calendrier des échéances et rappels J-14/J-7/J-2.
- Fiches compte/acheteur : historique AO, contacts, décisions passées,
  préférences et niveau d'appétence.

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

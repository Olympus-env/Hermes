# Installeur HERMES

Pipeline qui produit `HERMES-Setup-<version>.exe`, un installeur Windows
distribuable qui :

- Pose `hermes.exe` + `backend\backend.exe` dans `Program Files\HERMES`
- Installe Ollama silencieusement (si non déjà présent) via l'installeur
  officiel embarqué
- Crée raccourci Bureau + Menu Démarrer
- Enregistre la désinstallation dans le Panneau de configuration
- À la désinstallation, propose de conserver ou supprimer les données
  utilisateur (`%LocalAppData%\HERMES`)

L'utilisateur final n'a qu'à double-cliquer sur `HERMES-Setup-x.y.z.exe`.

## Prérequis (côté développeur uniquement)

1. **Inno Setup 6** (gratuit) — <https://jrsoftware.org/isdl.php>
   Pèse ~7 Mo. Installer dans le dossier par défaut.
2. **Rust + .NET pour le frontend** — déjà installés pour bosser sur HERMES.
3. **Python venv backend + PyInstaller** — installé automatiquement par
   `scripts/build-backend.ps1`.

## Construction

```powershell
.\scripts\build-installer.ps1
```

Le script orchestre tout :
1. `npm run tauri build` → `hermes.exe`
2. `scripts/build-backend.ps1` → `backend.exe`
3. Téléchargement de `OllamaSetup.exe` (~700 Mo) depuis ollama.com
4. Compilation Inno Setup

Sortie : `installer/dist/HERMES-Setup-<version>.exe` (~800 Mo si Ollama
embarqué, ~120 Mo sans).

### Options

```powershell
# Skip la recompilation Tauri si rien n'a changé côté frontend
.\scripts\build-installer.ps1 -SkipFrontend

# Skip backend (si backend.exe est à jour)
.\scripts\build-installer.ps1 -SkipBackend

# Skip Ollama (installeur léger, l'utilisateur devra installer Ollama lui-même)
.\scripts\build-installer.ps1 -SkipOllama

# Build le plus rapide (re-package uniquement)
.\scripts\build-installer.ps1 -SkipFrontend -SkipBackend
```

## Structure

```
installer/
├── HERMES.iss          ← script Inno Setup (versionné)
├── README.md           ← ce fichier
├── staging/            ← fichiers prêts à packager (généré, ignoré)
│   ├── hermes.exe
│   ├── hermes.ico
│   ├── backend/
│   │   └── backend.exe (+ DLLs)
│   └── OllamaSetup.exe
└── dist/               ← installeur final (ignoré)
    └── HERMES-Setup-0.1.0.exe
```

## Test de l'installeur

1. Lance l'installeur sur une VM Windows propre (ou en mode utilisateur
   standard pour valider les permissions).
2. Vérifie que `Program Files\HERMES\hermes.exe` existe.
3. Vérifie qu'Ollama est installé (`ollama.exe` accessible).
4. Lance HERMES depuis le menu Démarrer.
5. Au premier lancement, le modal de téléchargement du modèle Mistral
   doit apparaître automatiquement.
6. Ferme HERMES → aucun processus HERMES/backend/ollama zombie.
7. Désinstalle depuis le Panneau de configuration. L'app doit
   disparaître complètement (et te demander si tu veux garder les
   données utilisateur).

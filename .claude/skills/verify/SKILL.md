---
name: verify
description: Recette pour lancer HERMES en local et vérifier une modification à l'exécution (backend FastAPI, faux Ollama, frontend). À utiliser par le vérificateur avant tout verdict PASS/FAIL.
---

# Vérifier HERMES à l'exécution

La preuve, c'est l'app qui tourne — pas les tests. Toujours isoler : dossier de
données temporaire, port libre, jamais `./data` ni le port 8000 de Joshua.

## Backend (macOS / Linux)

```bash
cd backend
test -d .venv || (python3.11 -m venv .venv && .venv/bin/pip install -q -r requirements.txt ruff)
D=$(mktemp -d); PORT=87$((RANDOM % 90 + 10))
HERMES_DB_PATH=$D/h.db HERMES_STORAGE_PATH=$D/s HERMES_LOG_PATH=$D/l \
HERMES_MASTER_KEY_PATH=$D/m.key \
HERMES_DEBUG=true HERMES_SCHEDULER_AUTO_START=false \
HERMES_PYTHIA_MODELE=<modèle déjà installé, cf. `ollama list`> \
  .venv/bin/uvicorn hermes.main:app --host 127.0.0.1 --port $PORT > $D/uv.log 2>&1 &
PID=$!
until curl -sf http://127.0.0.1:$PORT/health >/dev/null; do sleep 0.3; done
# ... piloter les routes touchées, capturer les réponses ...
kill $PID; cat $D/uv.log   # les logs font partie des preuves
```

Sous Windows (env de Joshua) : `py -3.12` et `.\.venv\Scripts\...`.

- Liste des routes : `curl -s http://127.0.0.1:$PORT/openapi.json`.
- Seed de données : passer par l'API (`POST /argos/initialiser`, etc.) ou par un
  petit script qui importe `hermes.db` avec les mêmes variables `HERMES_*`.
- Tests réseau vers TED/BOAMP : lecture seule uniquement, requêtes de recherche.

## PYTHIA sans vrai LLM

Ollama n'est pas forcément installé. Lancer un faux Ollama sur un port libre et
pointer `HERMES_OLLAMA_BASE_URL=http://127.0.0.1:<port>` (loopback obligatoire,
sinon la config le réécrit). Le faux serveur répond à `POST /api/generate` /
`/api/chat` avec un JSON choisi pour le scénario (sortie valide, invalide, vide,
`<think>…</think>`, lenteur) et enregistre les payloads reçus — utile pour
vérifier `num_ctx`, `format`, `think`.

Si Ollama tourne vraiment (`curl -s http://127.0.0.1:11434/api/tags`), on peut
l'utiliser, mais ne jamais télécharger de modèle sans accord.

## Frontend

```bash
cd frontend && npm ci && npx tsc -b && npm run build
npm run dev -- --host 127.0.0.1 --port 5173   # puis navigateur intégré
```

Pour un changement UI : ouvrir la vue dans le navigateur intégré avec le backend
lancé ci-dessus (adapter `VITE_*`/URL API si nécessaire), capture d'écran.

## Pièges

- `hermes.config` force `host=127.0.0.1` et une URL Ollama loopback.
- **Scheduler** : il démarre dès que `HERMES_DEBUG` n'est pas `true`, même avec
  `HERMES_SCHEDULER_AUTO_START=false` (`main.py`) → vraies collectes TED/BOAMP et
  pipeline en boucle. Toujours `HERMES_DEBUG=true`, puis piloter
  `/argos/collecter*` ou `/orchestration/traiter` à la main.
- **Téléchargement de modèle** : si le modèle PYTHIA configuré n'est pas installé,
  le frontend lance tout seul `POST /pythia/modele/telecharger` (~5 Go). Toujours
  fixer `HERMES_PYTHIA_MODELE` sur un modèle présent (`ollama list`) ou pointer
  `HERMES_OLLAMA_BASE_URL` vers un faux Ollama. Jamais de pull sans accord.
- **Protection CSRF** : tout appel non-GET exige l'en-tête
  `X-Hermes-Client: hermes-ui` (sinon 403) ; `Host` doit être 127.0.0.1/localhost.
- **Ressources partagées** entre agents parallèles : choisir un port libre
  (vérifier avec `lsof -i :$PORT`), ne jamais écrire dans la base d'un autre port,
  utiliser son propre onglet du navigateur intégré, ses propres fichiers dans un
  sous-dossier dédié du scratchpad.
- Les tests dépendant de la date du jour doivent utiliser des dates relatives.

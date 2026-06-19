# Capacites TED et BOAMP a exploiter dans HERMES

Date: 2026-06-19

Ce document cadre les fonctionnalites des API TED et BOAMP que HERMES devrait
utiliser pour fiabiliser ARGOS, enrichir KRINOS et preparer HERMION, sans
sortir des invariants du projet: application locale, pas de telemetry, pas de
dependance cloud payante et aucune soumission automatique.

## Decision courte

HERMES doit traiter TED et BOAMP comme deux sources officielles
complementaires:

- BOAMP: source francaise prioritaire pour les marches publics nationaux,
  exploitee via le dataset Opendatasoft DILA.
- TED: source europeenne prioritaire pour les marches au-dessus des seuils,
  exploitee via la Search API v3 publique.

ARGOS doit rester en lecture seule: recherche, collecte, dedoublonnage,
qualification et telechargement de documents publics quand ils sont fournis.
HERMES ne doit pas utiliser les API TED de publication, validation ou gestion
eForms pour soumettre ou modifier des avis.

## Capacites BOAMP a utiliser

API cible:

- `GET https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records`

Capacites utiles:

- Recherche d'avis publics sans authentification.
- Filtrage ODSQL via `where`.
- Recherche textuelle ciblee via `search(champ, "terme")`.
- Tri via `order_by`, notamment `dateparution desc`.
- Pagination via `limit` et `offset`.
- Selection de champs via `select`.
- Requetes analytiques simples via `group_by` et agregations si besoin.
- Lecture du schema dataset pour verifier les champs disponibles.

Champs BOAMP a normaliser dans HERMES:

- `idweb` ou identifiant equivalent -> `reference_externe`.
- `url_avis` -> `url_source`.
- `objet` -> titre/objet.
- `nomacheteur` -> emetteur.
- `dateparution` -> `date_publication`.
- `datelimitereponse` -> `date_limite`.
- `nature_libelle` / `type_marche` -> `type_marche`.
- `code_departement` et `code_departement_prestation` -> zone.
- `descripteur_code` / `descripteur_libelle` -> classification metier.

Recommandations BOAMP:

- Garder le filtrage serveur sur `objet`, mais ne pas s'y limiter pour le
  filtrage final: le runner doit rester le garde-fou client.
- Ajouter un mode de recherche par expressions metier fortes, pas par acronymes
  seuls. Exemple: preferer `envoi de SMS`, `messagerie`, `notification` a
  `SMS` seul, qui peut matcher des sigles d'acheteurs.
- Utiliser `select` pour reduire les payloads lorsque la pagination monte en
  volume.
- Conserver le recouvrement incremental deja implemente, mais ajouter des tests
  live optionnels des requetes ODSQL critiques.
- Preparer un enrichissement par descripteurs BOAMP pour aider le scoring
  KRINOS.

## Capacites TED a utiliser

API cible:

- `POST https://api.ted.europa.eu/v3/notices/search`

Capacites utiles:

- Recherche publique d'avis publies sans API key.
- Requetes expertes TED via le champ `query`.
- Filtrage par lieu d'execution, ex. `place-of-performance IN (FRA)`.
- Filtrage textuel par titre, ex. `notice-title ~ "terme"`.
- Filtrage par CPV, nature de contrat, type d'avis, dates, acheteur et autres
  champs eForms quand valides.
- Selection des champs retournes via `fields`.
- Pagination via `PAGE_NUMBER` ou iteration.
- Scope `ACTIVE` pour les opportunites en cours.
- Liens directs vers HTML/PDF/XML quand presents dans `links`.
- Telechargement direct d'avis TED en HTML/PDF/XML par URL publique.

Champs TED a normaliser dans HERMES:

- `publication-number` -> `reference_externe`.
- `notice-title` -> titre/objet.
- `publication-date` -> `date_publication`.
- `deadline-receipt-tender-date-lot` -> `date_limite`.
- `buyer-name` -> emetteur.
- `place-of-performance` -> zone.
- `classification-cpv` -> classification.
- `links` -> URL source et liens documents/avis.
- `notice-type` et `contract-nature`, si disponibles -> type/procedure.

Recommandations TED:

- Garder `place-of-performance IN (FRA)` comme filtre de base V1 pour un usage
  LinkMobility France, mais rendre le pays configurable plus tard.
- Utiliser `notice-title ~ "terme"` pour les mots-cles precis; eviter le
  full-text trop large en premiere intention.
- Ajouter progressivement les filtres CPV et nature de contrat, car ils sont
  plus robustes que les acronymes.
- Recuperer les liens HTML/PDF/XML pour alimenter KRINOS quand TED les expose.
- Ne pas utiliser les API TED Publication/Validation/Submission: elles servent
  aux eSenders et demandent authentification/API key, hors perimetre HERMES.

## Capacites a ne pas utiliser en V1

- Soumission automatique d'offres ou de candidatures.
- Publication ou gestion d'avis TED via API authentifiee.
- Validation eForms TED pour produire des avis.
- Scraping agressif de portails prives sans session utilisateur explicite.
- Services tiers payants de monitoring AO.

## Priorites d'implementation

### P1 - Fiabiliser la collecte officielle

- Introduire un `CapabilityProfile` par portail ARGOS:
  - support du filtrage serveur;
  - champs filtrables confirmes;
  - champs retournes;
  - support pagination;
  - support liens documents.
- Centraliser les query builders BOAMP/TED avec tests unitaires.
- Ajouter des tests de non-regression sur les acronymes courts (`SMS`, `RCS`)
  pour eviter les faux positifs evidents.
- Ajouter `select` BOAMP et `fields` TED comme listes explicites versionnees.

### P2 - Enrichir les filtres metier

- Ajouter filtres CPV/TED et descripteurs BOAMP.
- Ajouter type/nature de marche.
- Ajouter zone configurable.
- Ajouter dates: publication depuis, deadline minimum, deadline maximum.
- Ajouter montant/budget uniquement si le champ est fiable sur la source.

### P3 - Alimenter KRINOS avec plus de contexte

- Collecter les liens documents publics exposes par TED/BOAMP.
- Normaliser les documents source, checksums et types.
- Creer un etat `documents_manquants` / `documents_detectes` dans la fiche AO.
- Declencher KRINOS automatiquement seulement apres telechargement best-effort.

### P4 - Observabilite ARGOS

- Journaliser la requete serveur utilisee, sans secrets.
- Journaliser le mode de fallback quand une requete serveur est rejetee.
- Exposer dans l'UI le dernier statut par portail:
  - derniere tentative;
  - derniere collecte reussie;
  - nombre nouveaux/dedoublonnes/filtres;
  - derniere erreur.

## Impacts code attendus

Backend:

- `backend/hermes/agents/argos/base.py`
- `backend/hermes/agents/argos/boamp.py`
- `backend/hermes/agents/argos/ted.py`
- `backend/hermes/agents/argos/filtre.py`
- `backend/hermes/agents/argos/runner.py`
- `backend/hermes/db/models.py` si nouveaux champs persistants.
- `backend/hermes/api/argos.py` pour exposer les capacites et filtres.

Frontend:

- `frontend/src/views/Settings.tsx` pour les filtres avances.
- `frontend/src/views/Tenders.tsx` pour les badges source/documents.
- `frontend/src/lib/api.ts` pour les nouveaux contrats.

Tests:

- Query builders BOAMP/TED.
- Filtres acronyme vs mot entier.
- Pagination et fallback serveur.
- Normalisation des champs TED/BOAMP.
- Respect des portails actifs/inactifs.
- Tests live optionnels marques separement, jamais obligatoires pour CI locale.

## Definition de done

- Les deux scrapers restent en lecture seule.
- Les requetes serveur sont testees et documentees.
- Les faux positifs acronymes les plus courants sont couverts.
- Le runner conserve le filtre client comme garde-fou.
- Les nouvelles donnees enrichissent KRINOS sans imposer de dependance reseau
  hors portails officiels et documents publics.
- `pytest`, `ruff`, `npm run build` restent verts.

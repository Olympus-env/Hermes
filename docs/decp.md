# DECP : analyse concurrentielle des marchés attribués

Issue #32. Vérifié en live le 2026-09-29 (lecture seule).

## Source retenue

**Données essentielles de la commande publique consolidées (format tabulaire)**,
jeu data.gouv.fr `donnees-essentielles-de-la-commande-publique-consolidees-format-tabulaire`
(id `608c055b35eb4e6ee20eb325`), consolidé et mis à jour quotidiennement par decp.info
(Colin Maudry / Open Data Services), à partir de toutes les sources de publication (AIFE, portails
régionaux, Atexo, etc.).

- Ressource interrogée : `decp.csv`, resource id `22847056-61df-452d-837d-8b8ceadbfc52`
  (~2,6 Go, jamais téléchargée par HERMES).
- **API tabulaire officielle** de data.gouv.fr, sans clé ni authentification :
  `https://tabular-api.data.gouv.fr/api/resources/22847056-61df-452d-837d-8b8ceadbfc52/data/`
- Licence : Licence Ouverte 2.0 (Etalab), réutilisation libre y compris commerciale, avec
  mention de la source.
- Écartés : `data.economie.gouv.fr` (jeux `decp_augmente`, `decp-2022-marches-valides`) marqués
  obsolètes / partiels ; le Parquet (`decp.parquet`, 250 Mo) n'est pas exposé par l'API tabulaire
  (404 constaté) et impliquerait un téléchargement massif.

## Champs utilisés

| Champ DECP | Usage |
|------------|-------|
| `uid` | identifiant du marché (SIRET acheteur + id) ; un marché multi-titulaires occupe plusieurs lignes, HERMES le compte une fois |
| `acheteur_id` | SIRET de l'acheteur (filtre) |
| `titulaire_id`, `titulaire_nom` | titulaires (SIRET) ; regroupés par SIREN pour ne pas doublonner les établissements |
| `montant` | montant du marché (euros) |
| `codeCPV` | CPV du marché (8 chiffres) |
| `offresRecues` | nombre d'offres reçues (souvent vide) |
| `dateNotification` | date de notification (fenêtre 3 ans, tri décroissant) |
| `donneesActuelles` | `true` : dernière version du marché (exclut les versions remplacées par une modification) |
| `objet` | libellé (tronqué à 200 caractères) |

## Requêtes

Toutes en GET, paginées (`page_size=200`, 3 pages max = 600 lignes, plafond signalé à l'UI) :

```
# historique de l'acheteur
?acheteur_id__exact=<SIRET>&donneesActuelles__exact=true
&dateNotification__greater=<aujourd'hui - 3 ans>&dateNotification__sort=desc&columns=...

# historique du secteur (groupe CPV = 4 premiers chiffres ; préfixe re-vérifié côté client)
?codeCPV__contains=<4 chiffres>&donneesActuelles__exact=true&...
```

`__contains` est sensible à la casse et n'est pas un préfixe ; la recherche par nom d'acheteur
est donc jugée **trop imprécise** ("Ville de Nevers" ne retrouve pas "COMMUNE DE NEVERS (MAIRIE)")
et n'est pas utilisée : l'analyse acheteur exige un SIRET.

## Liaison AO ↔ acheteur

Colonnes ajoutées à `appels_offre` (migration `_migrer_colonnes`, bases existantes OK) :
`emetteur_siret` (14 chiffres) et `code_cpv` (8 chiffres).

- **BOAMP** : extraits du champ `donnees` (JSON de l'avis) à la collecte. Trois formats gérés :
  eForms (organisation liée à `cac:ContractingParty`, CPV `cbc:ItemClassificationCode`),
  FNSimple (`codeIdentificationNational`, `classPrincipale`), ancien format
  (`CODE_IDENT_NATIONAL`, `CPV.PRINCIPAL`). AO collectés avant la migration : rattrapés à la
  première consultation de l'encart (relecture de l'avis par `idweb`, lecture seule).
- **TED** : la recherche TED n'expose pas de SIRET acheteur (les champs `buyer-identifier` /
  `organisation-identifier-buyer` ne renvoient rien d'exploitable). Seul le CPV (déjà stocké
  dans `code_naf`) est utilisé : l'encart n'affiche alors que l'historique du secteur.

## API et cache

`GET /appels-offre/{id}/concurrence[?actualiser=true]` : blocs `acheteur` et `secteur`
(nombre de marchés, montant médian et total, offres moyennes, titulaires récurrents,
tendance 12 mois vs 12 mois précédents avec seuil ±10 % sur la médiane, marchés récents).

- Cache local `cache_decp` (MNEMOSYNE), TTL 24 h ; en cas de panne, le cache périmé est servi.
- Rate-limit : requêtes sérialisées, 1 s minimum entre deux appels, retry/backoff commun ARGOS.
- Seul hôte contacté : `tabular-api.data.gouv.fr` (portail public officiel). Les requêtes ne
  contiennent que le SIRET de l'acheteur (donnée publique) ou un code CPV.

## Limites

- Les DECP ne couvrent que les marchés ≥ 40 000 € HT (seuil de publication) ; les petits MAPA
  sont absents.
- `offresRecues` et `montant` sont parfois vides ou aberrants (`montant_anomalie` non filtré ici).
- Publication avec délai : les attributions très récentes peuvent manquer.
- Première consultation lente (~25 s constatés pour un acheteur + un secteur, l'API filtrant
  `contains` sans index) ; ensuite instantané via le cache.
- Le secteur est un échantillon des 600 marchés les plus récents du groupe CPV (indiqué dans l'UI).

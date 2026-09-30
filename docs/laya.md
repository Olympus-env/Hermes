# Juge Laya (KRINOS) — choix techniques, banc d'essai, limites

Issue #56 : Laya remplace Jev (TypeSafe) comme second avis local de KRINOS.

## Moteur retenu : ONNX Runtime + `tokenizers`, dans le process backend

- **Modèle** : `convaiinnovations/laya-multilingual` (Apache 2.0), encodeur mmBERT-base
  (22 couches, vocabulaire 256 k) + tête de décision. Un seul graphe ONNX : entrées
  `input_ids`, `attention_mask`, `marker_pos`, `marker_mask`, `qtype` ; sortie `logits`
  (un par option) et `act_logits`.
- **Portage** : il n'existe pas d'ONNX officiel. On utilise le portage communautaire
  `onnx-community/laya-multilingual-ONNX` (Apache 2.0), **révision épinglée**
  `46b77bbf5642fec5f14e540570228a8cbe8ab81f`. Parité annoncée par son auteur : écart max
  des logits 3e-5 (fp32) ; en fp16, écart max 0,035 en probabilité et aucun choix changé.
- **Dépendances** : `onnxruntime` (déjà là pour RapidOCR) et `tokenizers` (wheel Rust,
  ~3 Mo, ajoutée à `requirements.txt` et au `.spec` PyInstaller). Ni PyTorch ni
  `transformers`.
- **Alternative écartée** : le serveur `laya-serve` en loopback (sidecar) exigerait PyTorch,
  soit environ +700 Mo dans l'installeur, pour un résultat identique. L'int8 communautaire
  (325 Mo) a été écarté faute de mesure de parité documentée.
- **Séquence** : `construire_sequence` (`laya_moteur.py`) est un portage Python pur de
  `build_sequence` de `rl_common.py` (référence Laya). Vérifiée contre la référence :
  test pytest (référence recopiée, 30 cas aléatoires, faux tokenizer) et, hors CI, sur
  120 séquences avec le vrai tokenizer (`transformers`) : identiques. Jetons : `<bos>` = CLS,
  `<eos>` = SEP, `<mask>`, `<pad>`. Le texte `<mask>` des données est neutralisé, et
  `laya.construire_state` retire aussi `<bos>`, `<eos>`, `<pad>`… pour qu'un document ne puisse
  pas injecter de jeton spécial.

## Fichiers du modèle et téléchargement consenti

| Fichier | Taille | SHA-256 |
|---|---|---|
| `tokenizer.json` | 34,4 Mo | `609d8f4c…ab5b6f` |
| `config.json` | 2,9 Ko | `cc32109b…dcc` |
| `onnx/model_fp16.onnx` + `_data` | 3,6 Mo + 644 Mo | `81f641e2…d98a`, `3c9eb52f…ee4cf` |
| `onnx/model.onnx` + `_data` (fp32) | 3,6 Mo + 1,29 Go | `22461d98…f2f9f`, `f01238e1…d09` |

(Empreintes complètes dans `backend/hermes/agents/krinos/laya_modele.py`.)

- Consentement explicite : `POST /krinos/laya/modele/telecharger` exige `confirme: true` ;
  l'interface demande une confirmation nommant la source et la taille. **Rien au démarrage.**
- Chaque fichier est vérifié par SHA-256 avant d'être rendu visible (reprise possible sur
  `.part`, fichier corrompu rejeté). Stockage : `<dossier de données HERMES>/modeles/laya`
  (`HERMES_LAYA_DOSSIER` pour l'écraser).
- Intégrité au chargement (#63) : au premier chargement du moteur dans le process
  (`moteur_onnx`), `verifier_integrite` recalcule le SHA-256 complet de chaque fichier, en
  streaming (blocs de 1 Mo, jamais 650 Mo en mémoire). Les empreintes sont mises en cache par
  process, clé (chemin, taille, `mtime_ns`) : un fichier inchangé n'est haché qu'une fois.
  En cas d'écart (même à taille égale), le chargement est refusé (`ModeleLayaAltere`), le
  fichier est signalé dans `a_reinstaller` de `GET /krinos/laya/modele` (le modèle n'est plus
  `installe`), et un log KRINOS est écrit. Rien n'est retéléchargé sans nouveau consentement ;
  la réinstallation consentie ne remplace que les fichiers altérés.
- Mesuré : 682 Mo (fp16) téléchargés et vérifiés en 40 s depuis cet environnement.

## Contexte retenu

Laya lit **1024 tokens** (valeur d'entraînement ; `HERMES_LAYA_MAX_TOKENS`, jusqu'à 8192, la
parité ONNX n'étant documentée que jusqu'à 2048). La tête (consigne + options) prend au plus
256 tokens ; l'état reçoit le reste, soit **~2 300 caractères** (ratio prudent de 3
caractères par token). État composé : avis (titre 200, objet 500 caractères), profil métier
(400 caractères au moins, jusqu'au quart du budget), puis extrait du DCE : 60 % de tête,
40 % de queue et fenêtres autour des passages suspects détectés par les motifs locaux.
Conséquence documentée : **un piège au milieu d'un DCE long n'est pas lu** (la détection par
motifs et le juge local PYTHIA restent les garde-fous du milieu de document).

## Formulation des questions (avertissement de l'issue sur `noul`)

Le banc confirme que le Noul suit les libellés plutôt que le contenu :

| Formulation | Pièges à phrase visible détectés | Faux positifs DCE sains | Faux positifs AO réels |
|---|---|---|---|
| Noul, libellés français décrivant la réponse (ancienne) | 10/10 | **6/7** | **35/62** |
| `choice` neutre A/B | 0/10 (signal inversé, AUROC 0,27) | 3/7 | 42/62 |
| **Noul neutre, instruction anglaise (retenue)** | 6/10 | 1/7 | 6/62 |

L'ancienne formulation détectait tout parce qu'elle répondait « manipulation » à presque
tout DCE ; les pièges dont la phrase était **tronquée hors de l'état** (5/5) sortaient
« détectés » : le signal ne dépendait pas du contenu. Le `choice` neutre demandé par l'issue
en repli **ne corrige rien** (pire). La formulation retenue n'utilise pas de libellés
(`criteres=None` : le modèle applique ses libellés neutres « false/true ») et une consigne
anglaise ; les pièges tronqués restent bas (0/5), comme il se doit. Les rubriques des
dimensions (Score 0-4) restent en français.

## Résultats du banc (`backend/scripts/banc_laya.py`)

Machine : Xeon 2,1 GHz, 4 vCPU, ONNX Runtime 1.30.0, CPU. Corpus : 4 fixtures du banc PYTHIA + 3
témoins longs sans piège, 15 DCE piégés (les 5 formulations de #38 × début/milieu/fin d'un DCE
de ~15 000 caractères), **62 AO réels BOAMP** (22 pertinents / 40 hors profil pour un profil
« ESN : développement, hébergement/infogérance, cybersécurité », étiquetés à la main sur le
titre ; 4 avis ambigus écartés). Corpus versionné : `backend/scripts/banc_laya_ao_reels.json`.

**Latence CPU** (jugement complet = 7 questions ; état plafonné à 1024 tokens) :

| Précision | Chargement | Avis seul (médiane) | Avec DCE long (médiane) | p95 | Pré-tri (1 question) |
|---|---|---|---|---|---|
| fp16 (644 Mo) | 2,2 s | 1,46 s | 5,40 s | 5,67 s | 0,17 s |
| fp32 (1,29 Go) | 1,7 s | 1,46 s | 5,18 s | 5,49 s | 0,17 s |

fp16 n'est pas plus rapide sur ce CPU (Xeon 2,1 GHz, 4 vCPU) mais divise le téléchargement
par deux pour des décisions quasi identiques : **fp16 par défaut**, fp32 au choix.

**Qualité** (formulation retenue, T = 1) :
- Manipulation ≥ 0,5 : 6/10 pièges à phrase visible détectés, 1/7 faux positifs sur DCE sains,
  6/62 sur AO réels ; AUROC 0,87. Laya est un complément des motifs et du juge PYTHIA, pas
  un remplaçant.
- Pertinence Noul sur les 62 AO réels : AUROC **0,67** seulement ; à 0,3 (défaut du pré-tri)
  presque tout passe (exactitude 37 %) : le pré-tri est sans effet tant que le seuil n'est pas
  recalé (meilleur seuil mesuré ~0,99 pour 71 % d'exactitude). Le signal est trop faible pour
  écarter des AO sans supervision : rester en opt-in, calibrer sur l'historique (#44).
- Score 0-100 : 3 fixtures sur 4 dans la fourchette attendue ; la fixture « voirie » (attendu
  0-40) obtient 68,7. Les scores sont peu discriminants (« les questions `score` sont
  faibles ») : d'où l'importance du drapeau de divergence avec PYTHIA et du routage humain.
- fp16 et fp32 donnent des résultats quasi identiques (AUROC manipulation 0,87 contre 0,89 ;
  mêmes taux de détection et de faux positifs).

**Température de calibration** (confiance moyenne des dimensions) : T = 1 → 0,28 ; 1,5 → 0,17 ;
2 → 0,11 ; 3 → 0,06. Le modèle rend des distributions déjà étalées sur les rubriques ; la
température est réglable dans Paramètres (0,5 à 5) et appliquée avant tout calcul ; elle est
mémorisée dans les détails de chaque analyse.

**Comparaison au juge local PYTHIA (#41)** : **non mesurée**, aucun Ollama dans cet
environnement (`127.0.0.1:11434` injoignable). Le banc l'interroge automatiquement s'il répond
et l'ajoute au rapport ; à relancer sur la machine de Joshua.

## Migration depuis Jev

- Colonnes `score_jev`, `confiance_jev`, `details_jev`, `hors_profil_jev`, `pertinence_jev`
  renommées `*_laya` (`ALTER TABLE … RENAME COLUMN`, idempotent) ; drapeaux stockés
  `jev:*` / `divergence_jev_pythia` réécrits `laya:*` / `divergence_laya_pythia`.
- Réglages `krinos.jev.{seuils,config,pretri}` copiés vers `krinos.laya.*` (seuils et seuil de
  pré-tri conservés ; interrupteurs `actif` remis à faux, Laya étant un autre juge) ; budget
  TypeSafe supprimé. Clé `poids_jev` du composite relue comme `poids_laya`.
- API : `/krinos/jev*` devient `/krinos/laya*` ; champs `*_jev` → `*_laya`.

## Limites restantes

- Pertinence et scores faibles (voir ci-dessus) ; le fine-tuning sur l'historique est hors
  périmètre de #56.
- Pièges au milieu d'un DCE long non lus (contexte de 1024 tokens).
- Comparaison PYTHIA à refaire avec Ollama.
- `tokenizers` et `onnxruntime` ajoutent des binaires au `.spec` PyInstaller : à valider au
  prochain build de l'installeur Windows.

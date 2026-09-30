/**
 * Client minimaliste pour l'API HERMES (backend FastAPI local sur 127.0.0.1:8000).
 *
 * Aucune URL externe — toute la communication reste sur la boucle locale.
 */

const API_BASE =
  (import.meta.env.VITE_HERMES_API as string | undefined) ??
  "http://127.0.0.1:8000";

export type HealthResponse = {
  status: "ok" | string;
  app: string;
  version: string;
  timestamp: string;
};

export type InfoResponse = {
  app: string;
  version: string;
  agents: string[];
  portails_configures: number;
};

export type AppelOffre = {
  id: number;
  portail_id: number | null;
  portail_nom: string | null;
  reference_externe: string | null;
  url_source: string;
  titre: string;
  emetteur: string | null;
  objet: string | null;
  budget_estime: number | null;
  devise: string;
  date_publication: string | null;
  date_limite: string | null;
  type_marche: string | null;
  zone_geographique: string | null;
  code_naf: string | null;
  statut: string;
  cree_le: string;
  maj_le: string;
  // Score KRINOS pondéré ; null si l'AO n'a jamais été analysé (≠ score 0).
  score: number | null;
  analyse_disponible: boolean;
  // État documents (Boucle 3) : liens détectés par ARGOS vs fichiers téléchargés.
  documents_detectes: number;
  documents_telecharges: number;
  documents_manquants: number;
  // Pré-tri Laya : AO jugé « hors profil », non analysé par PYTHIA (analyse forçable).
  hors_profil_laya?: boolean;
  pertinence_laya?: number | null;
};

// Analyse concurrentielle DECP (GET /appels-offre/{id}/concurrence).
export type AnalyseConcurrence = {
  nb_marches: number;
  montant_median: number | null;
  montant_total: number | null;
  offres_moyennes: number | null;
  titulaires: {
    nom: string;
    siret: string | null;
    nb_marches: number;
    montant_total: number;
    part: number;
  }[];
  tendance: {
    sens: "hausse" | "baisse" | "stable" | "indeterminee";
    // false : échantillon plafonné ne remontant pas à la période précédente.
    precedent_couvert: boolean;
    nb_recent: number;
    nb_precedent: number;
    montant_median_recent: number | null;
    montant_median_precedent: number | null;
  };
  periode_annees: number;
  echantillon_plafonne: boolean;
  total_reel: number | null;
  periode_debut: string | null;
  periode_fin: string | null;
};

export type ConcurrenceAO = {
  siret: string | null;
  cpv: string | null;
  acheteur: AnalyseConcurrence | null;
  secteur: AnalyseConcurrence | null;
  maj_le: string | null;
  depuis_cache: boolean;
  message: string | null;
};

export type AppelsOffrePage = {
  total: number;
  items: AppelOffre[];
  limit: number;
  offset: number;
};

export type CollecteArgos = {
  portail: string;
  ao_trouves: number;
  ao_nouveaux: number;
  ao_dedoublonnes: number;
  duree_ms: number;
  succes: boolean;
  erreurs: string[];
};

export type CycleCollecteArgos = {
  resultats: CollecteArgos[];
  ao_trouves: number;
  ao_nouveaux: number;
  ao_dedoublonnes: number;
  ao_filtres: number;
  succes: boolean;
};

export type EtatSchedulerArgos = {
  en_marche: boolean;
  jobs: { id: string; prochaine_execution: string | null }[];
};

export type ScrapersArgos = {
  disponibles: string[];
};

export type PortailArgos = {
  id: number;
  nom: string;
  url_base: string;
  type: "public" | "prive";
  actif: boolean;
  frequence_minutes: number;
  derniere_collecte: string | null;
  credentials_configures: boolean;
};

// Natures de marché canoniques (mappées par portail côté backend).
export type NatureMarche = "services" | "travaux" | "fournitures";

export type CriteresAvances = {
  cpv: string[];
  descripteurs: string[];
  natures: string[];
  pays: string[];
  departements: string[];
  date_publication_depuis: string | null;
  deadline_min: string | null;
  deadline_max: string | null;
};

export type FiltreVeille = {
  inclus: string[];
  exclus: string[];
  actif: boolean;
  avance: CriteresAvances;
};

export type CapaciteArgos = {
  portail: string;
  filtrage_serveur: boolean;
  champs_filtrables: string[];
  champs_retournes: string[];
  pagination: boolean;
  liens_documents: boolean;
};

export type DocumentKrinos = {
  id: number;
  nom_fichier: string;
  chemin_local: string;
  type: string;
  taille_octets: number;
  checksum_sha256: string;
  contenu_extrait: boolean;
};

export type TelechargementDocuments = {
  appel_offre_id: number;
  documents: DocumentKrinos[];
  nouveaux: number;
};

export const CRITERES_AVANCES_VIDE: CriteresAvances = {
  cpv: [],
  descripteurs: [],
  natures: [],
  pays: [],
  departements: [],
  date_publication_depuis: null,
  deadline_min: null,
  deadline_max: null,
};

export type SuggestionMotsCles = {
  inclus: string[];
  exclus: string[];
  raisonnement: string;
};

export type PonderationKrinos = {
  affinite_metier: number;
  references: number;
  adequation_budget: number;
  capacite_equipe: number;
  calendrier: number;
  total: number;
};

export type AnalyseKrinos = {
  id: number;
  appel_offre_id: number;
  resume: string;
  score: number;
  justification_score: string;
  scores_dimensions: Partial<Record<keyof Omit<PonderationKrinos, "total">, number>>;
  /** Analyse locale de secours (PYTHIA a échoué) : résumé et score heuristiques. */
  degradee?: boolean;
  /** Motif d'injection détecté dans le texte de l'AO : décision humaine requise. */
  suspect_injection?: boolean;
  /** Drapeau global (injection, incohérence, divergence Laya/PYTHIA). */
  a_verifier?: boolean;
  drapeaux?: string[];
  /** Juge Laya (optionnel, local), séparé du score PYTHIA. */
  score_laya?: number | null;
  /** Confiance Laya 0-1 (après température de calibration). */
  confiance_laya?: number | null;
  details_laya?: {
    pertinence?: number | null;
    manipulation?: number | null;
    tokens?: number;
    temperature?: number;
  } | null;
  /** Go/no-go composite (PYTHIA + Laya + pertinence), recalculé sans ré-inférence. */
  composite?: number | null;
  verdict_composite?: "go" | "no_go" | "a_verifier" | "indetermine" | null;
  tags: string[];
  criteres_extraits: string | null;
  duree_analyse_ms: number | null;
  modele_llm: string | null;
  cree_le: string;
};

export type PrecisionLaya = "fp16" | "fp32";

export type ProgressionLaya = {
  precision: string;
  en_cours: boolean;
  statut: string;
  fichier: string;
  octets_telecharges: number;
  octets_total: number;
  pourcent: number;
  erreur: string | null;
  termine_le: number | null;
};

export type ModeleLaya = {
  precision: PrecisionLaya;
  installe: boolean;
  manquants: string[];
  /** Fichiers présents mais altérés (SHA-256 invalide) : modèle à réinstaller. */
  a_reinstaller: string[];
  /** Taille indicative à télécharger pour cette précision. */
  taille_octets: number;
  dossier: string;
  espace_disque_libre_octets: number;
  progression: ProgressionLaya;
};

/** Réglages du juge Laya (local, ONNX) : ni clé, ni budget, rien ne sort de la machine. */
export type ConfigLaya = {
  /** Voulu par l'utilisateur. */
  actif: boolean;
  /** Voulu ET poids installés : Laya répond réellement. */
  operationnel: boolean;
  precision: PrecisionLaya;
  /** Température de calibration (0,5 à 5) : > 1 aplatit les probabilités. */
  temperature: number;
  max_tokens: number;
  /** Pré-tri de pertinence avant KRINOS (désactivé par défaut). */
  pretri_actif?: boolean;
  /** Probabilité 0-1 sous laquelle un AO est marqué « hors profil (Laya) ». */
  pretri_seuil?: number;
  modele: ModeleLaya;
};

/** Profil métier structuré (sans aucune donnée d'identité : nom, email, SIRET…). */
export type ProfilMetier = {
  activite: string;
  secteurs: string[];
  codes_cpv: string[];
  zone_geographique: string;
  effectif: number | null;
  ca_tranche: string;
  certifications: string[];
  types_marches: string[];
  references_types: string[];
};

export type SeuilsLaya = {
  divergence: number;
  manipulation: number;
  pertinence: number;
  confiance: number;
};

export type ConfigComposite = {
  poids_pythia: number;
  poids_laya: number;
  poids_pertinence: number;
  seuil_go: number;
};

export type MatriceSeuil = {
  seuil: number;
  vrais_positifs: number;
  faux_positifs: number;
  vrais_negatifs: number;
  faux_negatifs: number;
  taux_accord: number | null;
};

export type SourceCalibration = {
  n: number;
  taux_accord: number | null;
  score_moyen_accepte: number | null;
  score_moyen_rejete: number | null;
  matrice: MatriceSeuil[];
};

export type Calibration = {
  echantillon: { total: number; acceptes: number; rejetes: number; avec_laya: number };
  ecart_moyen_laya_pythia: number | null;
  seuil_go: number;
  sources: Record<"pythia" | "laya" | "composite", SourceCalibration>;
  heuristique: string;
};

export type ProgressionModele = {
  modele: string;
  en_cours: boolean;
  statut: string;
  octets_telecharges: number;
  octets_total: number;
  pourcent: number;
  erreur: string | null;
  termine_le: number | null;
};

export type StatutModele = {
  modele: string;
  installe: boolean;
  ollama_disponible: boolean;
  progression: ProgressionModele;
};

export type ModelePropose = {
  nom: string;
  taille_octets: number;
  installe: boolean;
};

export type OptionsModeles = {
  modele_actuel: string;
  proposes: ModelePropose[];
  installes: string[];
  espace_disque_libre_octets: number;
  modele_libre: boolean;
};

export type StatutReponseHermion =
  | "en_generation"
  | "en_attente"
  | "a_modifier"
  | "validee"
  | "rejetee"
  | "exportee";

export type ReponseHermion = {
  id: number;
  appel_offre_id: number;
  version: number;
  statut: StatutReponseHermion;
  contenu: string;
  longueur_mots: number | null;
  duree_generation_ms: number | null;
  workflow_utilise: string | null;
  commentaire_humain: string | null;
  chemin_export: string | null;
  cree_le: string;
  maj_le: string;
};

export type ProgressionHermion = {
  appel_offre_id: number;
  etape: string;
  libelle: string;
  index: number;
  total: number;
  message: string;
  erreur: string | null;
  termine: boolean;
  reponse_id: number | null;
  secondes_ecoulees: number;
  connue: boolean;
};

export type ReponseAvecAO = {
  id: number;
  appel_offre_id: number;
  appel_offre_titre: string;
  appel_offre_emetteur: string | null;
  version: number;
  statut: StatutReponseHermion;
  longueur_mots: number | null;
  duree_generation_ms: number | null;
  cree_le: string;
  maj_le: string;
};

export type NiveauLog = "debug" | "info" | "warning" | "error";

export type LogAgentEntry = {
  id: number;
  agent: string;
  niveau: NiveauLog;
  message: string;
  contexte: string | null;
  appel_offre_id: number | null;
  portail_id: number | null;
  cree_le: string;
};

export type LogsPage = {
  total: number;
  items: LogAgentEntry[];
  limit: number;
  offset: number;
};

export type ActiviteAgent = {
  id: number;
  agent: string;
  niveau: NiveauLog;
  message: string;
  cree_le: string;
};

/** Agrégats de l'Accueil (GET /tableau-de-bord). */
export type TableauDeBord = {
  genere_le: string;
  total_ao: number;
  urgents: number;
  score_eleve: number;
  a_repondre: number;
  /** Nombre d'AO par StatutAO (brut, analyse, a_repondre, en_redaction, repondu, …). */
  par_statut: Record<string, number>;
  /** Dernière version de réponse de chaque AO, comptée par StatutReponseHermion. */
  reponses: Record<string, number>;
  activite: ActiviteAgent[];
};

export type ConfigOrchestration = {
  actif: boolean;
  seuil_score: number;
  auto_rediger: boolean;
  max_par_cycle: number;
};

export type RapportOrchestration = {
  actif: boolean;
  ao_analyses: number;
  ao_rediges: number;
  ao_sous_seuil: number;
  /** AO au-dessus du seuil mais drapeautés par KRINOS (décision humaine). */
  ao_a_verifier?: number;
  ao_echecs: number;
  details: { ao_id: number; action: string; score?: number }[];
};

export type SectionWorkflow = {
  titre: string;
  brief: string;
  longueur_cible: number | null;
};

export type WorkflowHermion = {
  configure: boolean;
  source: string;
  consignes_globales: string;
  sections: SectionWorkflow[];
};

export type RedactionRequest = {
  profil?: {
    prenom?: string;
    nom?: string;
    email?: string;
    entreprise?: string;
    activite?: string;
  };
  consignes?: string;
};

export type RedactionResponse = {
  reponse: ReponseHermion;
  plan: { titre: string; brief: string }[];
};

/** Délai par défaut des lectures (GET). Les écritures/traitements longs
 * (collecte, génération PYTHIA) n'ont pas de délai sauf `timeoutMs` explicite. */
const TIMEOUT_LECTURE_MS = 30_000;

type FetchOptions = RequestInit & { timeoutMs?: number };

/** Combine le signal de l'appelant et un délai maximal en un seul signal. */
function signalAvecTimeout(
  signal: AbortSignal | null | undefined,
  timeoutMs: number | undefined,
): { signal: AbortSignal | undefined; nettoyer: () => void } {
  if (!timeoutMs) return { signal: signal ?? undefined, nettoyer: () => {} };
  const ctrl = new AbortController();
  const surAbandon = () => ctrl.abort(signal?.reason);
  if (signal?.aborted) ctrl.abort(signal.reason);
  else signal?.addEventListener("abort", surAbandon, { once: true });
  const timer = setTimeout(
    () => ctrl.abort(new Error(`Délai dépassé (${Math.round(timeoutMs / 1000)} s)`)),
    timeoutMs,
  );
  return {
    signal: ctrl.signal,
    nettoyer: () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", surAbandon);
    },
  };
}

async function fetchJson<T>(path: string, options?: FetchOptions): Promise<T> {
  const { timeoutMs, ...init } = options ?? {};
  const delai = timeoutMs ?? (!init.method || init.method === "GET" ? TIMEOUT_LECTURE_MS : 0);
  const { signal, nettoyer } = signalAvecTimeout(init.signal, delai);
  try {
    return await fetchJsonBrut<T>(path, { ...init, signal });
  } finally {
    nettoyer();
  }
}

async function fetchJsonBrut<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      // Protection CSRF : exigé par le backend sur tout non-GET (force un preflight).
      "X-Hermes-Client": "hermes-ui",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!r.ok) {
    // Remonte le `detail` FastAPI quand il est présent : message bien plus
    // lisible que le seul code HTTP (ex. « PYTHIA est down » sur un 502).
    const detail = await lireDetailErreur(r);
    throw new Error(detail ?? `${r.status} ${r.statusText} sur ${path}`);
  }
  return (await r.json()) as T;
}

/** Extrait un message lisible du corps d'une réponse d'erreur (best-effort). */
async function lireDetailErreur(r: Response): Promise<string | null> {
  try {
    const data = await r.clone().json();
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      // Erreurs de validation FastAPI : liste d'objets {msg, loc}.
      const msgs = detail
        .map((d) => (typeof d?.msg === "string" ? d.msg : null))
        .filter(Boolean);
      if (msgs.length > 0) return msgs.join(" · ");
    }
  } catch {
    /* corps non-JSON : on retombe sur le message HTTP générique */
  }
  return null;
}

export const api = {
  health: () => fetchJson<HealthResponse>("/health"),
  info: () => fetchJson<InfoResponse>("/info"),
  collecterArgos: (limite = 20) =>
    fetchJson<CycleCollecteArgos>(`/argos/collecter?limite=${limite}`, {
      method: "POST",
    }),
  listerScrapersArgos: () => fetchJson<ScrapersArgos>("/argos/scrapers"),
  listerPortailsArgos: () => fetchJson<PortailArgos[]>("/argos/portails"),
  enregistrerPortailArgos: (
    nom: string,
    portail: {
      url_base: string;
      type?: "public" | "prive";
      actif?: boolean;
      frequence_minutes?: number;
      config_scraping?: string | null;
    },
  ) =>
    fetchJson<PortailArgos>(`/argos/portails/${encodeURIComponent(nom)}`, {
      method: "PUT",
      body: JSON.stringify(portail),
    }),
  listerAO: (statut?: string, signal?: AbortSignal) =>
    fetchJson<AppelsOffrePage>(
      `/appels-offre${statut ? `?statut=${encodeURIComponent(statut)}` : ""}`,
      { signal },
    ),
  etatSchedulerArgos: (signal?: AbortSignal) =>
    fetchJson<EtatSchedulerArgos>("/argos/scheduler", { signal }),
  tableauDeBord: (signal?: AbortSignal) =>
    fetchJson<TableauDeBord>("/tableau-de-bord", { signal }),
  detailAO: (id: number) => fetchJson<AppelOffre>(`/appels-offre/${id}`),
  // Premier appel : jusqu'à ~3 requêtes espacées vers data.gouv.fr, d'où le délai large.
  concurrenceAO: (id: number, actualiser = false, signal?: AbortSignal) =>
    fetchJson<ConcurrenceAO>(
      `/appels-offre/${id}/concurrence${actualiser ? "?actualiser=true" : ""}`,
      { signal, timeoutMs: 90_000 },
    ),
  modifierStatutAO: (id: number, statut: string) =>
    fetchJson<AppelOffre>(`/appels-offre/${id}/statut`, {
      method: "PATCH",
      body: JSON.stringify({ statut }),
    }),
  listerCapacitesArgos: () => fetchJson<CapaciteArgos[]>("/argos/capacites"),
  lireFiltreVeille: () => fetchJson<FiltreVeille>("/argos/filtre"),
  ecrireFiltreVeille: (filtre: {
    inclus: string[];
    exclus: string[];
    avance?: CriteresAvances;
  }) =>
    fetchJson<FiltreVeille>("/argos/filtre", {
      method: "PUT",
      body: JSON.stringify(filtre),
    }),
  telechargerDocumentsAO: (aoId: number) =>
    fetchJson<TelechargementDocuments>(
      `/krinos/appels-offre/${aoId}/documents/telecharger`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  // Déverrouille ARGOS en fin d'onboarding : les collectes ne démarrent
  // qu'après cet appel, une fois les filtres métier persistés.
  initialiserArgos: () =>
    fetchJson<{ message: string; refiltrage: Record<string, number> }>(
      "/argos/initialiser",
      { method: "POST" },
    ),
  suggererFiltreVeille: (profil: { entreprise: string; activite: string; infos: string }) =>
    fetchJson<SuggestionMotsCles>("/argos/filtre/suggerer", {
      method: "POST",
      body: JSON.stringify(profil),
    }),
  lirePonderation: () => fetchJson<PonderationKrinos>("/krinos/ponderation"),
  ecrirePonderation: (p: Omit<PonderationKrinos, "total">) =>
    fetchJson<PonderationKrinos>("/krinos/ponderation", {
      method: "PUT",
      body: JSON.stringify(p),
    }),
  lireAnalyseKrinos: (aoId: number) =>
    fetchJson<AnalyseKrinos>(`/krinos/appels-offre/${aoId}/analyse`),
  // Relance une analyse KRINOS complète via PYTHIA (résumé + ventilation +
  // score). `forcer` régénère même si une analyse existe déjà.
  analyserKrinos: (aoId: number, forcer = true) =>
    fetchJson<{ analyse: AnalyseKrinos; nouveau: boolean }>(
      `/krinos/appels-offre/${aoId}/analyser`,
      { method: "POST", body: JSON.stringify({ forcer }) },
    ),
  recalculerScoreKrinos: (aoId: number) =>
    fetchJson<AnalyseKrinos>(`/krinos/appels-offre/${aoId}/recalculer-score`, {
      method: "POST",
    }),
  statutModele: () => fetchJson<StatutModele>("/pythia/modele/status"),
  optionsModeles: () => fetchJson<OptionsModeles>("/pythia/modele/options"),
  // Le téléchargement exige un consentement explicite (`confirme: true`).
  telechargerModele: (modele: string) =>
    fetchJson<ProgressionModele>("/pythia/modele/telecharger", {
      method: "POST",
      body: JSON.stringify({ modele, confirme: true }),
    }),
  annulerTelechargementModele: () =>
    fetchJson<ProgressionModele>("/pythia/modele/annuler", { method: "POST" }),
  choisirModeleInstalle: (modele: string) =>
    fetchJson<StatutModele>("/pythia/modele/choisir", {
      method: "POST",
      body: JSON.stringify({ modele }),
    }),
  listerLogs: (params: {
    agent?: string;
    niveau?: NiveauLog;
    limit?: number;
    offset?: number;
  } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (params.agent) q.set("agent", params.agent);
    if (params.niveau) q.set("niveau", params.niveau);
    q.set("limit", String(params.limit ?? 100));
    q.set("offset", String(params.offset ?? 0));
    return fetchJson<LogsPage>(`/logs?${q.toString()}`, { signal });
  },
  lireProfilMetier: () => fetchJson<ProfilMetier>("/profil/metier"),
  ecrireProfilMetier: (p: ProfilMetier) =>
    fetchJson<ProfilMetier>("/profil/metier", {
      method: "PUT",
      body: JSON.stringify(p),
    }),
  lireConfigLaya: () => fetchJson<ConfigLaya>("/krinos/laya"),
  ecrireConfigLaya: (
    c: Partial<{ actif: boolean; temperature: number; precision: PrecisionLaya }>,
  ) =>
    fetchJson<ConfigLaya>("/krinos/laya", {
      method: "PUT",
      body: JSON.stringify(c),
    }),
  /** Consentement explicite : `confirme` doit être vrai (jamais lancé sans clic). */
  telechargerModeleLaya: (precision: PrecisionLaya) =>
    fetchJson<ProgressionLaya>("/krinos/laya/modele/telecharger", {
      method: "POST",
      body: JSON.stringify({ precision, confirme: true }),
    }),
  annulerTelechargementLaya: () =>
    fetchJson<ProgressionLaya>("/krinos/laya/modele/annuler", { method: "POST" }),
  statutModeleLaya: () => fetchJson<ModeleLaya>("/krinos/laya/modele"),
  lireConfigJugeLocal: () => fetchJson<{ actif: boolean }>("/krinos/juge-local"),
  ecrireConfigJugeLocal: (actif: boolean) =>
    fetchJson<{ actif: boolean }>("/krinos/juge-local", {
      method: "PUT",
      body: JSON.stringify({ actif }),
    }),
  ecrireConfigPretriLaya: (pretri_actif: boolean, pretri_seuil: number) =>
    fetchJson<ConfigLaya>("/krinos/laya/pretri", {
      method: "PUT",
      body: JSON.stringify({ pretri_actif, pretri_seuil }),
    }),
  lireSeuilsLaya: () => fetchJson<SeuilsLaya>("/krinos/laya/seuils"),
  ecrireSeuilsLaya: (seuils: SeuilsLaya) =>
    fetchJson<SeuilsLaya>("/krinos/laya/seuils", {
      method: "PUT",
      body: JSON.stringify(seuils),
    }),
  lireComposite: () => fetchJson<ConfigComposite>("/krinos/composite"),
  ecrireComposite: (c: ConfigComposite) =>
    fetchJson<ConfigComposite>("/krinos/composite", {
      method: "PUT",
      body: JSON.stringify(c),
    }),
  lireCalibration: () => fetchJson<Calibration>("/krinos/calibration"),
  lireConfigOrchestration: () =>
    fetchJson<ConfigOrchestration>("/orchestration/config"),
  ecrireConfigOrchestration: (c: ConfigOrchestration) =>
    fetchJson<ConfigOrchestration>("/orchestration/config", {
      method: "PUT",
      body: JSON.stringify(c),
    }),
  lancerPipeline: () =>
    fetchJson<RapportOrchestration>("/orchestration/traiter", {
      method: "POST",
    }),
  lireWorkflowHermion: () => fetchJson<WorkflowHermion>("/hermion/workflow"),
  ecrireWorkflowHermion: (wf: {
    consignes_globales: string;
    sections: SectionWorkflow[];
    source?: string;
  }) =>
    fetchJson<WorkflowHermion>("/hermion/workflow", {
      method: "PUT",
      body: JSON.stringify({ source: "manuel", ...wf }),
    }),
  deriverWorkflowHermion: (p: { mode: "workflow" | "exemples"; contenu: string }) =>
    fetchJson<WorkflowHermion>("/hermion/workflow/deriver", {
      method: "POST",
      body: JSON.stringify(p),
    }),
  listerReponsesHermion: (statut?: StatutReponseHermion) =>
    fetchJson<ReponseAvecAO[]>(
      `/hermion/reponses${statut ? `?statut=${statut}` : ""}`,
    ),
  lireReponseHermion: (id: number) =>
    fetchJson<ReponseHermion>(`/hermion/reponses/${id}`),
  rediger: (ao_id: number, payload: RedactionRequest = {}) =>
    fetchJson<RedactionResponse>(`/hermion/appels-offre/${ao_id}/rediger`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  // Avancement de la rédaction en cours (polling pendant la génération).
  progressionHermion: (ao_id: number) =>
    fetchJson<ProgressionHermion>(
      `/hermion/appels-offre/${ao_id}/progression`,
    ),
  modifierStatutReponse: (
    id: number,
    statut: StatutReponseHermion,
    commentaire?: string,
  ) =>
    fetchJson<ReponseHermion>(`/hermion/reponses/${id}/statut`, {
      method: "PATCH",
      body: JSON.stringify(
        commentaire !== undefined ? { statut, commentaire_humain: commentaire } : { statut },
      ),
    }),
  exporterReponse: (id: number) =>
    fetchJson<ReponseHermion>(`/hermion/reponses/${id}/exporter`, {
      method: "POST",
    }),
  /** Télécharge le PDF exporté (blob) — `window.open` est bloqué dans la webview Tauri. */
  telechargerExportReponse: async (id: number): Promise<Blob> => {
    const r = await fetch(`${API_BASE}/hermion/reponses/${id}/export`);
    if (!r.ok) {
      const detail = await lireDetailErreur(r);
      throw new Error(detail ?? `${r.status} ${r.statusText} sur l'export`);
    }
    return r.blob();
  },
  modifierContenuReponse: (id: number, contenu: string, commentaire?: string) =>
    fetchJson<ReponseHermion>(`/hermion/reponses/${id}/contenu`, {
      method: "PATCH",
      body: JSON.stringify(
        commentaire !== undefined ? { contenu, commentaire_humain: commentaire } : { contenu },
      ),
    }),
};

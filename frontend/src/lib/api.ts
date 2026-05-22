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

export type FiltreVeille = {
  inclus: string[];
  exclus: string[];
  actif: boolean;
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
  tags: string[];
  criteres_extraits: string | null;
  duree_analyse_ms: number | null;
  modele_llm: string | null;
  cree_le: string;
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

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} sur ${path}`);
  }
  return (await r.json()) as T;
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
  listerAO: (statut?: string) =>
    fetchJson<AppelsOffrePage>(
      `/appels-offre${statut ? `?statut=${encodeURIComponent(statut)}` : ""}`,
    ),
  detailAO: (id: number) => fetchJson<AppelOffre>(`/appels-offre/${id}`),
  modifierStatutAO: (id: number, statut: string) =>
    fetchJson<AppelOffre>(`/appels-offre/${id}/statut`, {
      method: "PATCH",
      body: JSON.stringify({ statut }),
    }),
  lireFiltreVeille: () => fetchJson<FiltreVeille>("/argos/filtre"),
  ecrireFiltreVeille: (filtre: { inclus: string[]; exclus: string[] }) =>
    fetchJson<FiltreVeille>("/argos/filtre", {
      method: "PUT",
      body: JSON.stringify(filtre),
    }),
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
  telechargerModele: (modele?: string) =>
    fetchJson<ProgressionModele>("/pythia/modele/telecharger", {
      method: "POST",
      body: JSON.stringify(modele ? { modele } : {}),
    }),
  listerLogs: (params: {
    agent?: string;
    niveau?: NiveauLog;
    limit?: number;
    offset?: number;
  } = {}) => {
    const q = new URLSearchParams();
    if (params.agent) q.set("agent", params.agent);
    if (params.niveau) q.set("niveau", params.niveau);
    q.set("limit", String(params.limit ?? 100));
    q.set("offset", String(params.offset ?? 0));
    return fetchJson<LogsPage>(`/logs?${q.toString()}`);
  },
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
  urlExportReponse: (id: number) =>
    `${API_BASE}/hermion/reponses/${id}/export`,
  modifierContenuReponse: (id: number, contenu: string, commentaire?: string) =>
    fetchJson<ReponseHermion>(`/hermion/reponses/${id}/contenu`, {
      method: "PATCH",
      body: JSON.stringify(
        commentaire !== undefined ? { contenu, commentaire_humain: commentaire } : { contenu },
      ),
    }),
};

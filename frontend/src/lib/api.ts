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

export type FiltreVeille = {
  inclus: string[];
  exclus: string[];
  actif: boolean;
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
  statutModele: () => fetchJson<StatutModele>("/pythia/modele/status"),
  telechargerModele: (modele?: string) =>
    fetchJson<ProgressionModele>("/pythia/modele/telecharger", {
      method: "POST",
      body: JSON.stringify(modele ? { modele } : {}),
    }),
};

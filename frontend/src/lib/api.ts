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
  titre: string;
  emetteur: string | null;
  date_limite: string | null;
  statut: string;
  cree_le: string;
  url_source: string;
};

export type AppelsOffrePage = {
  total: number;
  items: AppelOffre[];
  limit: number;
  offset: number;
};

async function fetchJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} sur ${path}`);
  }
  return (await r.json()) as T;
}

export const api = {
  health: () => fetchJson<HealthResponse>("/health"),
  info: () => fetchJson<InfoResponse>("/info"),
  listerAO: (statut?: string) =>
    fetchJson<AppelsOffrePage>(
      `/appels-offre${statut ? `?statut=${encodeURIComponent(statut)}` : ""}`,
    ),
};

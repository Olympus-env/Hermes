// Types et constantes partagés du frontend HERMES (agents, statuts, échéances).
// Les données viennent de MNEMOSYNE via `lib/api.ts` : plus aucun jeu fictif ici.

export type AgentKey = "argos" | "krinos" | "hermion";

export type AgentState = "active" | "running" | "inactive";

export type TagTone = "gold" | "green" | "violet" | "coral";

export type TenderTag = { label: string; tone: TagTone };

export type Tender = {
  id: string;
  title: string;
  issuer: string;
  portal: string;
  deadline: string;
  budget: string;
  reference: string;
  score: number;
  // false ou absent = AO jamais analysé par KRINOS (score à ignorer/afficher
  // « non analysé » plutôt que 0).
  analyzed?: boolean;
  tags: TenderTag[];
  summary: string;
  keypoints: string[];
  status: string;
  // État documents (Boucle 3/4) : liens détectés par ARGOS vs téléchargés.
  documentsDetectes?: number;
  documentsTelecharges?: number;
  horsProfilJev?: boolean;
};

export type ResponseStatus =
  | "en-attente"
  | "a-modifier"
  | "validee"
  | "rejetee"
  | "exportee";

export const AGENTS: Record<
  AgentKey,
  { name: string; color: string; role: string }
> = {
  argos:   { name: "ARGOS",   color: "#1D9E75", role: "Collecte" },
  krinos:  { name: "KRINOS",  color: "#7F77DD", role: "Analyse" },
  hermion: { name: "HERMION", color: "#D85A30", role: "Rédaction" },
};

export const RESPONSE_STATUS: Record<
  ResponseStatus,
  { label: string; color: string; bg: string }
> = {
  "en-attente": { label: "En attente de validation", color: "#E0A93B", bg: "rgba(224,169,59,0.12)" },
  "a-modifier": { label: "À modifier",               color: "#D85A30", bg: "rgba(216,90,48,0.12)" },
  "validee":    { label: "Validée",                  color: "#1D9E75", bg: "rgba(29,158,117,0.12)" },
  "rejetee":    { label: "Rejetée",                  color: "#E0524E", bg: "rgba(229,82,78,0.14)" },
  "exportee":   { label: "Exportée",                 color: "#7A8190", bg: "rgba(122,129,144,0.14)" },
};

export function deadlineInfo(dateStr: string) {
  const d = new Date(dateStr);
  const ms = d.getTime() - Date.now();
  const days = Math.ceil(ms / 86_400_000);
  const formatted = d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const urgent = days < 7;
  return { formatted, days, urgent };
}

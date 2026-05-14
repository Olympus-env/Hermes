// Mock data + helpers pour HERMES.
// Reflète le prototype `data.js` — sera remplacé par des appels au backend
// FastAPI au fil de l'implémentation des phases 4-10.

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
  tags: TenderTag[];
  summary: string;
  keypoints: string[];
  status: string;
};

export type ResponseStatus =
  | "en-attente"
  | "a-modifier"
  | "validee"
  | "rejetee"
  | "exportee";

export type Reponse = {
  id: string;
  tender: string;
  issuer: string;
  pages: number;
  generatedAt: string;
  status: ResponseStatus;
  score: number;
  comment: string;
};

export type Portal = {
  name: string;
  url: string;
  active: boolean;
  lastSync: string;
  count: number;
};

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

const TODAY = new Date("2026-05-14");

export function deadlineInfo(dateStr: string) {
  const d = new Date(dateStr);
  const ms = d.getTime() - TODAY.getTime();
  const days = Math.ceil(ms / 86_400_000);
  const formatted = d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const urgent = days < 7;
  return { formatted, days, urgent };
}

export const TENDERS: Tender[] = [
  {
    id: "ao-2026-0142",
    title: "Refonte du système d'information de la direction des affaires maritimes",
    issuer: "Ministère de la Mer — DAM",
    portal: "BOAMP",
    deadline: "2026-05-19",
    budget: "1.8 M€ — 2.4 M€",
    reference: "26S0067412",
    score: 87,
    tags: [
      { label: "SI métier", tone: "gold" },
      { label: "Secteur public", tone: "violet" },
      { label: "Migration", tone: "green" },
    ],
    summary:
      "Refonte complète du SI maritime avec migration des bases historiques (Oracle 11g) vers une architecture moderne (PostgreSQL + microservices). Le marché inclut le RUN sur 3 ans avec option de reconduction tacite. KRINOS identifie une forte adéquation avec les références Naval Group et DGAMPA livrées sur 2023–2025.",
    keypoints: [
      "Reconduction 3+1 ans",
      "Visite obligatoire le 28/04",
      "Réf. similaires : DGAMPA, Naval Group",
      "Allotissement : 3 lots (SI / RUN / Tierce Maintenance)",
    ],
    status: "à répondre",
  },
  {
    id: "ao-2026-0139",
    title: "Plateforme de télémédecine — Région Occitanie phase 2",
    issuer: "Conseil Régional Occitanie",
    portal: "AWS Achat",
    deadline: "2026-05-16",
    budget: "640 k€",
    reference: "ORC-2026-TM-08",
    score: 74,
    tags: [
      { label: "E-santé", tone: "green" },
      { label: "Région", tone: "gold" },
    ],
    summary:
      "Extension de la plateforme régionale de télémédecine déployée en 2024. Intégration de modules de téléexpertise dermatologique et cardiologique. KRINOS note un calendrier serré (livraison V1 prévue septembre) et recommande de chiffrer l'option \"hébergement HDS\" séparément.",
    keypoints: [
      "Hébergement HDS obligatoire",
      "Volumétrie : 14 000 actes/an",
      "Interop CI-SIS phase 2",
      "Pénalités fermes au-delà de S+10",
    ],
    status: "nouveau",
  },
  {
    id: "ao-2026-0138",
    title: "Marché-cadre AMO transformation numérique 2026–2029",
    issuer: "Caisse des Dépôts — Banque des Territoires",
    portal: "PLACE",
    deadline: "2026-06-04",
    budget: "Accord-cadre 8 M€",
    reference: "CDC-AMO-26",
    score: 92,
    tags: [
      { label: "AMO", tone: "violet" },
      { label: "Accord-cadre", tone: "gold" },
      { label: "Multi-attributaire", tone: "coral" },
    ],
    summary:
      "Accord-cadre multi-attributaire à bons de commande pour des prestations d'AMO sur les programmes territoriaux. 5 titulaires retenus. KRINOS estime que nos références CDC (mission 2022 et 2024) constituent un avantage différenciant majeur.",
    keypoints: [
      "Multi-attributaire — 5 titulaires",
      "Bons de commande sans minimum",
      "Référence CDC : forte affinité",
      "Pondération technique : 60 %",
    ],
    status: "à répondre",
  },
  {
    id: "ao-2026-0136",
    title: "Audit de sécurité et tests d'intrusion infrastructures critiques",
    issuer: "ANSSI",
    portal: "PLACE",
    deadline: "2026-05-30",
    budget: "320 k€ — 480 k€",
    reference: "ANSSI-PASSI-26-04",
    score: 58,
    tags: [
      { label: "Cyber", tone: "coral" },
      { label: "PASSI", tone: "violet" },
    ],
    summary:
      "Marché PASSI requérant la qualification ANSSI sur les 5 portées. HERMION détecte que nous ne disposons que de 4 portées qualifiées — risque de candidature non recevable. ARGOS recommande un partenariat groupement.",
    keypoints: [
      "Qualification PASSI 5 portées requise",
      "Habilitation Confidentiel Défense — équipe",
      "Réponse en groupement possible",
      "DCE complexe (47 pièces)",
    ],
    status: "nouveau",
  },
  {
    id: "ao-2026-0131",
    title: "Développement d'une application mobile citoyenne",
    issuer: "Métropole de Lyon",
    portal: "AWS Achat",
    deadline: "2026-06-22",
    budget: "210 k€",
    reference: "ML-2026-MOB-12",
    score: 41,
    tags: [
      { label: "Mobile", tone: "green" },
      { label: "Collectivité", tone: "gold" },
    ],
    summary:
      "Application mobile de signalement et services citoyens. KRINOS signale une forte concurrence (12 réponses attendues d'après historique 2023) et un budget bas en regard du périmètre. Pertinence modérée — à arbitrer.",
    keypoints: [
      "Budget contraint",
      "Forte concurrence attendue",
      "Pas de visite préalable",
      "Critère prix : 50 %",
    ],
    status: "nouveau",
  },
  {
    id: "ao-2026-0129",
    title: "Modernisation du datacenter de production — phase tranches conditionnelles",
    issuer: "AP-HP",
    portal: "BOAMP",
    deadline: "2026-07-10",
    budget: "3.2 M€",
    reference: "APHP-DSI-26-DC2",
    score: 31,
    tags: [{ label: "Infrastructure", tone: "violet" }],
    summary:
      "Marché orienté infrastructure physique (baies, climatisation, onduleurs). KRINOS estime que ce marché ne correspond pas à notre cœur de métier (logiciel + AMO). Recommandation : exclure.",
    keypoints: [
      "Hors cœur de métier",
      "Infrastructure physique",
      "Compétences réseau non couvertes",
    ],
    status: "nouveau",
  },
];

export const RESPONSES: Reponse[] = [
  {
    id: "rep-2026-0044",
    tender: "Refonte SI direction des affaires maritimes",
    issuer: "Ministère de la Mer — DAM",
    pages: 84,
    generatedAt: "2026-05-13 09:42",
    status: "en-attente",
    score: 87,
    comment: "",
  },
  {
    id: "rep-2026-0043",
    tender: "Marché-cadre AMO transformation numérique",
    issuer: "Caisse des Dépôts",
    pages: 62,
    generatedAt: "2026-05-12 17:08",
    status: "a-modifier",
    score: 92,
    comment:
      "Renforcer la section 3.2 sur la méthodologie agile. Préciser la composition de l'équipe avec les CV signés.",
  },
  {
    id: "rep-2026-0041",
    tender: "Plateforme de télémédecine Occitanie phase 2",
    issuer: "Région Occitanie",
    pages: 41,
    generatedAt: "2026-05-11 14:21",
    status: "validee",
    score: 74,
    comment: "",
  },
  {
    id: "rep-2026-0039",
    tender: "Audit cyber préfectures Île-de-France",
    issuer: "SGAR Île-de-France",
    pages: 38,
    generatedAt: "2026-05-09 11:55",
    status: "rejetee",
    score: 52,
    comment:
      "Non retenu. Note technique 14/20 — critère expérience PASSI insuffisamment démontré selon le rapport d'analyse.",
  },
  {
    id: "rep-2026-0036",
    tender: "Schéma directeur SI — Conseil Départemental 33",
    issuer: "Département de la Gironde",
    pages: 56,
    generatedAt: "2026-05-06 16:14",
    status: "exportee",
    score: 81,
    comment: "",
  },
];

export const PORTALS: Portal[] = [
  { name: "BOAMP",            url: "boamp.fr",                       active: true,  lastSync: "il y a 12 min", count: 1284 },
  { name: "PLACE",            url: "place.marches-publics.gouv.fr",  active: true,  lastSync: "il y a 18 min", count: 642  },
  { name: "AWS Achat",        url: "marches-publics.aws-achat.com",  active: true,  lastSync: "il y a 7 min",  count: 318  },
  { name: "TED Europa",       url: "ted.europa.eu",                  active: false, lastSync: "—",             count: 0    },
  { name: "Achat Solutions",  url: "achatpublic.com",                active: true,  lastSync: "il y a 22 min", count: 156  },
  { name: "Maximilien",       url: "maximilien.fr",                  active: false, lastSync: "—",             count: 0    },
];

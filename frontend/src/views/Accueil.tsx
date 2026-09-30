import { AnimatePresence, motion } from "motion/react";
import { AGENTS, type AgentKey, type AgentState } from "../lib/data";
import { api, type ActiviteAgent } from "../lib/api";
import { useApi } from "../lib/useApi";
import { AgentDot } from "../components/AgentChip";
import { Compteur } from "../components/Compteur";
import {
  COURBE,
  DECALAGE_TUILES,
  DELAI_ACTIVITE,
  DELAI_FILET,
  DUREE,
  VARIANTES_BADGE,
  VARIANTES_ELEMENT,
  delaiCascade,
} from "../lib/motion";
import { Icon } from "../components/Icon";
import type { ViewKey } from "../components/Sidebar";

type Props = {
  onNavigate: (v: ViewKey) => void;
  agents: Record<AgentKey, AgentState>;
  isLoading: boolean;
  onTriggerCycle: () => void;
  /** Incrémenté par l'App après une collecte : relit les agrégats. */
  refreshKey?: number;
};

type PipelineSeg = { key: string; label: string; n: number; color: string };

// Étapes du pipeline = statuts StatutAO « vivants », dans l'ordre du flux.
const ETAPES_PIPELINE: { key: string; label: string; color: string }[] = [
  { key: "brut",         label: "Collectés",    color: "#7A8190" },
  { key: "analyse",      label: "Analysés",     color: "#C8A951" },
  { key: "a_repondre",   label: "À répondre",   color: "#7F77DD" },
  { key: "en_redaction", label: "En rédaction", color: "#D85A30" },
  { key: "repondu",      label: "Répondus",     color: "#1D9E75" },
];

const heure = (iso: string): string => {
  const d = new Date(iso);
  const memeJour = d.toDateString() === new Date().toDateString();
  const hm = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  return memeJour
    ? hm
    : `${d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })} ${hm}`;
};

const agentDe = (ligne: ActiviteAgent): AgentKey => ligne.agent.toLowerCase() as AgentKey;

export function Accueil({ onNavigate, agents, isLoading, onTriggerCycle, refreshKey = 0 }: Props) {
  const { data, error } = useApi((signal) => api.tableauDeBord(signal), [refreshKey]);

  const counts = {
    total: data?.total_ao ?? 0,
    urgent: data?.urgents ?? 0,
    high: data?.score_eleve ?? 0,
    toAnswer: data?.a_repondre ?? 0,
  };
  const reponses = data?.reponses ?? {};
  const enValidation = (reponses["en_attente"] ?? 0) + (reponses["a_modifier"] ?? 0);
  const activite = data?.activite ?? [];

  const pipeline: PipelineSeg[] = ETAPES_PIPELINE.map((e) => ({
    ...e,
    n: data?.par_statut[e.key] ?? 0,
  }));

  const pipelineMax = Math.max(1, ...pipeline.map((p) => p.n));

  return (
    <div className="view">
      {isLoading && (
        <div className="loading-banner">
          <span className="loading-banner__icon" />
          <span>
            <strong style={{ color: "var(--argos)", letterSpacing: "0.08em" }}>ARGOS</strong>{" "}
            collecte les nouveaux appels d'offre…
          </span>
          <div className="loading-banner__bar" />
          <span
            style={{
              color: "var(--fg-3)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
            }}
          >
            scrapers ARGOS
          </span>
        </div>
      )}

      <div className="view__scroll">
        {error && !data && (
          <div className="loading-banner" role="alert">
            <span>Impossible de lire MNEMOSYNE : {error}</span>
          </div>
        )}
        <motion.div
          className="accueil-grid"
          initial="initial"
          animate="animate"
          variants={{ initial: {}, animate: { transition: { staggerChildren: DECALAGE_TUILES } } }}
        >
          {/* KPI tiles */}
          <motion.div variants={VARIANTES_ELEMENT} className="tile col-3">
            <div className="tile__label">
              AO détectés
            </div>
            <div className="tile__value"><Compteur valeur={counts.total} /></div>
            <div className="tile__sub">{counts.urgent} urgents (J−7)</div>
            <Barre />
          </motion.div>
          <motion.div variants={VARIANTES_ELEMENT} className="tile col-3">
            <div className="tile__label">Score ≥ 70</div>
            <div className="tile__value" style={{ color: "var(--argos)" }}><Compteur valeur={counts.high} /></div>
            <div className="tile__sub">Pertinence haute selon KRINOS</div>
<Barre fond="linear-gradient(90deg, var(--argos), transparent)" />
          </motion.div>
          <motion.div variants={VARIANTES_ELEMENT} className="tile col-3">
            <div className="tile__label">À répondre</div>
            <div className="tile__value" style={{ color: "var(--krinos)" }}><Compteur valeur={counts.toAnswer} /></div>
            <div className="tile__sub">Marqués par l'opérateur</div>
<Barre fond="linear-gradient(90deg, var(--krinos), transparent)" />
          </motion.div>
          <motion.div variants={VARIANTES_ELEMENT} className="tile col-3">
            <div className="tile__label">Réponses en validation</div>
            <div className="tile__value" style={{ color: "var(--warn)" }}>
              <Compteur valeur={enValidation} />
            </div>
            <div className="tile__sub">
              {reponses["validee"] ?? 0} validées · {reponses["exportee"] ?? 0} exportées
            </div>
<Barre fond="linear-gradient(90deg, var(--hermion), transparent)" />
          </motion.div>

          {/* Pipeline */}
          <motion.div variants={VARIANTES_ELEMENT} className="tile col-8">
            <div className="tile__label">
              <span>Pipeline des appels d'offre</span>
              <button className="btn btn--ghost btn--sm" onClick={onTriggerCycle}>
                <Icon.refresh size={11} /> Forcer un cycle
              </button>
            </div>
            <div className="pipeline">
              {pipeline.map((p, i) => (
                <motion.div
                  key={p.key}
                  className="pipeline__seg"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: DUREE.lente,
                    delay: delaiCascade(i + 2),
                    ease: [...COURBE.sortie],
                  }}
                  style={{
                    ["--w" as any]: (p.n / pipelineMax) * 6 + 1,
                    background: `linear-gradient(180deg, ${p.color}33 0%, ${p.color}22 100%)`,
                    borderLeft: `2px solid ${p.color}`,
                  }}
                >
                  <span>
                    <Compteur valeur={p.n} formater={(n) => n.toLocaleString("fr-FR")} />
                  </span>
                </motion.div>
              ))}
            </div>
            <div className="pipeline__legend">
              {pipeline.map((p) => (
                <span className="pipeline__legend-item" key={p.key}>
                  <span className="pipeline__legend-dot" style={{ background: p.color }} />
                  {p.label}
                </span>
              ))}
            </div>
          </motion.div>

          {/* Quick actions */}
          <motion.div variants={VARIANTES_ELEMENT} className="tile col-4">
            <div className="tile__label">Actions rapides</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
              <button className="btn btn--gold" onClick={() => onNavigate("tenders")}>
                <Icon.document size={13} /> Voir les appels d'offre
              </button>
              <button className="btn" onClick={() => onNavigate("responses")}>
                <Icon.reply size={13} /> File de validation
              </button>
              <button className="btn btn--ghost" onClick={() => onNavigate("settings")}>
                <Icon.settings size={13} /> Configurer les portails
              </button>
            </div>
          </motion.div>

          {/* Activity feed */}
          <motion.div variants={VARIANTES_ELEMENT} className="tile col-8">
            <div className="tile__label">
              <span>Activité des agents</span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--fg-4)",
                  textTransform: "none",
                  letterSpacing: 0,
                }}
              >
                {new Date().toLocaleDateString("fr-FR", {
                  day: "numeric",
                  month: "long",
                  year: "numeric",
                })}
              </span>
            </div>
            <div style={{ marginTop: 6 }}>
              {activite.length === 0 && (
                <div style={{ padding: "14px 0", fontSize: 12, color: "var(--fg-3)" }}>
                  Aucune activité d'agent enregistrée pour le moment.
                </div>
              )}
              {activite.map((row, i) => {
                const cle = agentDe(row);
                const a = AGENTS[cle] ?? { name: row.agent, color: "var(--fg-3)", role: "" };
                return (
                  <motion.div
                    className="activity-row"
                    key={row.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{
                      duration: DUREE.base,
                      delay: DELAI_ACTIVITE + delaiCascade(i),
                      ease: [...COURBE.sortie],
                    }}
                  >
                    <span className="activity-row__time">{heure(row.cree_le)}</span>
                    <span className="activity-row__msg">
                      <span className="activity-row__agent" style={{ color: a.color }}>{a.name}</span>
                      <span style={{ color: "var(--fg-4)", margin: "0 8px" }}>·</span>
                      {row.message}
                    </span>
                    <span>
                      <AgentDot agent={cle} state="active" size={6} />
                    </span>
                  </motion.div>
                );
              })}
            </div>
          </motion.div>

          {/* Status of agents */}
          <motion.div variants={VARIANTES_ELEMENT} className="tile col-4">
            <div className="tile__label">État des agents</div>
            <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
              {(Object.entries(AGENTS) as [AgentKey, (typeof AGENTS)[AgentKey]][]).map(
                ([key, a]) => {
                  const state = agents[key];
                  const stateColor =
                    state === "active"
                      ? a.color
                      : state === "running"
                        ? "var(--warn)"
                        : "var(--fg-4)";
                  const stateLabel =
                    state === "active" ? "Actif" : state === "running" ? "En cours" : "Inactif";
                  return (
                    <div
                      key={key}
                      style={{
                        padding: "10px 12px",
                        border: "1px solid var(--line)",
                        borderRadius: 6,
                        borderLeft: `2px solid ${a.color}`,
                        background: "var(--bg-1)",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                        }}
                      >
                        <span
                          style={{
                            fontWeight: 600,
                            fontSize: 12,
                            letterSpacing: "0.08em",
                            color: a.color,
                          }}
                        >
                          {a.name}
                        </span>
                        {/* L'état s'enchaîne : ancien libellé sorti, nouveau entré */}
                        <AnimatePresence mode="wait" initial={false}>
                          <motion.span
                            key={state}
                            className={state === "running" ? "etat-agent--en-cours" : undefined}
                            variants={VARIANTES_BADGE}
                            initial="initial"
                            animate="animate"
                            exit="exit"
                            style={{ fontSize: 11, color: stateColor, fontWeight: 500 }}
                          >
                            ● {stateLabel}
                          </motion.span>
                        </AnimatePresence>
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--fg-3)", marginTop: 4 }}>
                        {a.role}
                      </div>
                    </div>
                  );
                },
              )}
            </div>
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}

/** Filet de tuile : se trace de gauche à droite (transform seulement). */
function Barre({ fond }: { fond?: string }) {
  return (
    <motion.div
      className="tile__bar"
      initial={{ scaleX: 0 }}
      animate={{ scaleX: 1 }}
      transition={{ duration: DUREE.lente, delay: DELAI_FILET, ease: [...COURBE.sortie] }}
      style={{ transformOrigin: "left center", ...(fond ? { background: fond } : {}) }}
    />
  );
}

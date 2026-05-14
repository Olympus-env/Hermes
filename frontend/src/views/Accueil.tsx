import { AGENTS, RESPONSES, TENDERS, deadlineInfo, type AgentKey, type AgentState } from "../lib/data";
import { AgentDot } from "../components/AgentChip";
import { Icon } from "../components/Icon";
import type { ViewKey } from "../components/Sidebar";

type Props = {
  onNavigate: (v: ViewKey) => void;
  agents: Record<AgentKey, AgentState>;
  isLoading: boolean;
  onTriggerCycle: () => void;
};

type PipelineSeg = { key: string; label: string; n: number; color: string };

const PIPELINE: PipelineSeg[] = [
  { key: "veille",     label: "Veille",     n: 1284, color: "#5A6070" },
  { key: "collectes",  label: "Collectés",  n: 142,  color: "#7A8190" },
  { key: "pertinents", label: "Pertinents", n: 38,   color: "#C8A951" },
  { key: "a-repondre", label: "À répondre", n: 6,    color: "#7F77DD" },
  { key: "rediges",    label: "Rédigés",    n: 3,    color: "#D85A30" },
  { key: "deposes",    label: "Déposés",    n: 2,    color: "#1D9E75" },
];

const ACTIVITY: { time: string; agent: AgentKey; msg: string }[] = [
  { time: "09:42", agent: "argos",   msg: "Cycle terminé — 14 nouveaux AO collectés depuis BOAMP, PLACE, AWS Achat" },
  { time: "09:43", agent: "krinos",  msg: "Scoring de 14 AO — 3 marqués pertinents (≥ 70), 6 à arbitrer" },
  { time: "09:51", agent: "krinos",  msg: "AO 26S0067412 — score 87 / forte affinité avec références Naval Group" },
  { time: "10:08", agent: "hermion", msg: "Brouillon de réponse généré pour « Marché-cadre AMO transformation »" },
  { time: "10:15", agent: "argos",   msg: "Échec connexion TED Europa — credentials invalides, voir paramètres" },
  { time: "10:21", agent: "hermion", msg: "PDF généré — Refonte SI direction des affaires maritimes (84 p.)" },
];

export function Accueil({ onNavigate, agents, isLoading, onTriggerCycle }: Props) {
  const tenders = TENDERS;
  const responses = RESPONSES;

  const counts = {
    total: tenders.length,
    urgent: tenders.filter((t) => deadlineInfo(t.deadline).urgent).length,
    high: tenders.filter((t) => t.score >= 70).length,
    toAnswer: tenders.filter((t) => t.status === "à répondre").length,
  };

  const pipelineMax = Math.max(...PIPELINE.map((p) => p.n));

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
            3 / 4 portails
          </span>
        </div>
      )}

      <div className="view__scroll">
        <div className="accueil-grid">
          {/* KPI tiles */}
          <div className="tile col-3">
            <div className="tile__label">
              AO en veille <span className="kbd">7j</span>
            </div>
            <div className="tile__value">{counts.total}</div>
            <div className="tile__sub">+{counts.urgent} urgents (J−7)</div>
            <div className="tile__bar" />
          </div>
          <div className="tile col-3">
            <div className="tile__label">Score ≥ 70</div>
            <div className="tile__value" style={{ color: "var(--argos)" }}>{counts.high}</div>
            <div className="tile__sub">Pertinence haute selon KRINOS</div>
            <div
              className="tile__bar"
              style={{ background: "linear-gradient(90deg, var(--argos), transparent)" }}
            />
          </div>
          <div className="tile col-3">
            <div className="tile__label">À répondre</div>
            <div className="tile__value" style={{ color: "var(--krinos)" }}>{counts.toAnswer}</div>
            <div className="tile__sub">Marqués par l'opérateur</div>
            <div
              className="tile__bar"
              style={{ background: "linear-gradient(90deg, var(--krinos), transparent)" }}
            />
          </div>
          <div className="tile col-3">
            <div className="tile__label">Réponses en validation</div>
            <div className="tile__value" style={{ color: "var(--warn)" }}>
              {responses.filter((r) => r.status === "en-attente" || r.status === "a-modifier").length}
            </div>
            <div className="tile__sub">
              {responses.filter((r) => r.status === "validee").length} validées ·{" "}
              {responses.filter((r) => r.status === "exportee").length} exportées
            </div>
            <div
              className="tile__bar"
              style={{ background: "linear-gradient(90deg, var(--hermion), transparent)" }}
            />
          </div>

          {/* Pipeline */}
          <div className="tile col-8">
            <div className="tile__label">
              <span>Pipeline — 7 derniers jours</span>
              <button className="btn btn--ghost btn--sm" onClick={onTriggerCycle}>
                <Icon.refresh size={11} /> Forcer un cycle
              </button>
            </div>
            <div className="pipeline">
              {PIPELINE.map((p) => (
                <div
                  key={p.key}
                  className="pipeline__seg"
                  style={{
                    ["--w" as any]: (p.n / pipelineMax) * 6 + 1,
                    background: `linear-gradient(180deg, ${p.color}33 0%, ${p.color}22 100%)`,
                    borderLeft: `2px solid ${p.color}`,
                  }}
                >
                  <span>{p.n.toLocaleString("fr-FR")}</span>
                </div>
              ))}
            </div>
            <div className="pipeline__legend">
              {PIPELINE.map((p) => (
                <span className="pipeline__legend-item" key={p.key}>
                  <span className="pipeline__legend-dot" style={{ background: p.color }} />
                  {p.label}
                </span>
              ))}
            </div>
          </div>

          {/* Quick actions */}
          <div className="tile col-4">
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
          </div>

          {/* Activity feed */}
          <div className="tile col-8">
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
                Aujourd'hui · 14 mai 2026
              </span>
            </div>
            <div style={{ marginTop: 6 }}>
              {ACTIVITY.map((row, i) => {
                const a = AGENTS[row.agent];
                return (
                  <div className="activity-row" key={i}>
                    <span className="activity-row__time">{row.time}</span>
                    <span className="activity-row__msg">
                      <span className="activity-row__agent" style={{ color: a.color }}>{a.name}</span>
                      <span style={{ color: "var(--fg-4)", margin: "0 8px" }}>·</span>
                      {row.msg}
                    </span>
                    <span>
                      <AgentDot agent={row.agent} state="active" size={6} />
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Status of agents */}
          <div className="tile col-4">
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
                        <span style={{ fontSize: 11, color: stateColor, fontWeight: 500 }}>
                          ● {stateLabel}
                        </span>
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--fg-3)", marginTop: 4 }}>
                        {a.role}
                      </div>
                    </div>
                  );
                },
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

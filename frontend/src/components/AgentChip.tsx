import { AGENTS, type AgentKey, type AgentState } from "../lib/data";

type DotProps = { agent: AgentKey; state?: AgentState; size?: number };

export function AgentDot({ agent, state = "active", size = 8 }: DotProps) {
  const a = AGENTS[agent];
  const stateColor =
    state === "active" ? a.color : state === "running" ? "#E0A93B" : "#3A3F4A";
  return (
    <span
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        background: stateColor,
        boxShadow: state === "active" ? `0 0 8px ${a.color}66` : "none",
        transition: "background 200ms, box-shadow 200ms",
      }}
    />
  );
}

type ChipProps = { agent: AgentKey; state: AgentState; compact?: boolean };

export function AgentChip({ agent, state, compact = false }: ChipProps) {
  const a = AGENTS[agent];
  const stateLabel =
    state === "active" ? "Actif" : state === "running" ? "En cours" : "Inactif";
  const stateColor =
    state === "active" ? a.color : state === "running" ? "#E0A93B" : "#5A6070";
  return (
    <div className="agent-chip" data-state={state}>
      <span
        className="agent-chip__dot"
        style={{
          background: stateColor,
          boxShadow: state === "active" ? `0 0 0 3px ${a.color}22` : "none",
        }}
      >
        {state === "running" && (
          <span className="agent-chip__pulse" style={{ background: stateColor }} />
        )}
      </span>
      <span className="agent-chip__name">{a.name}</span>
      {!compact && (
        <>
          <span className="agent-chip__sep">·</span>
          <span className="agent-chip__state" style={{ color: stateColor }}>
            {stateLabel}
          </span>
        </>
      )}
    </div>
  );
}

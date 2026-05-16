import { useCallback, useEffect, useState } from "react";
import { Icon } from "../components/Icon";
import { api, type LogAgentEntry, type NiveauLog } from "../lib/api";

const AGENTS: { id: string | "all"; label: string }[] = [
  { id: "all", label: "Tous" },
  { id: "ARGOS", label: "ARGOS" },
  { id: "KRINOS", label: "KRINOS" },
  { id: "HERMION", label: "HERMION" },
  { id: "HERMES", label: "Pipeline" },
];

const NIVEAUX: { id: NiveauLog | "all"; label: string }[] = [
  { id: "all", label: "Tous niveaux" },
  { id: "info", label: "Info" },
  { id: "warning", label: "Avertissements" },
  { id: "error", label: "Erreurs" },
];

const COULEUR_NIVEAU: Record<NiveauLog, string> = {
  debug: "var(--fg-4)",
  info: "var(--fg-3)",
  warning: "var(--warn, #e0a93b)",
  error: "#dc5050",
};

const PAGE = 100;

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function Journal() {
  const [agent, setAgent] = useState<string | "all">("all");
  const [niveau, setNiveau] = useState<NiveauLog | "all">("all");
  const [items, setItems] = useState<LogAgentEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (offset: number, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const page = await api.listerLogs({
          agent: agent === "all" ? undefined : agent,
          niveau: niveau === "all" ? undefined : niveau,
          limit: PAGE,
          offset,
        });
        setTotal(page.total);
        setItems((prev) => (append ? [...prev, ...page.items] : page.items));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [agent, niveau],
  );

  useEffect(() => {
    void load(0, false);
  }, [load]);

  return (
    <div className="view">
      <div className="filters">
        {AGENTS.map((a) => (
          <button
            key={a.id}
            className={`btn ${agent === a.id ? "btn--gold" : "btn--ghost"} btn--sm`}
            onClick={() => setAgent(a.id)}
          >
            {a.label}
          </button>
        ))}
        <div style={{ width: 1, background: "var(--line)", margin: "0 4px" }} />
        {NIVEAUX.map((n) => (
          <button
            key={n.id}
            className={`btn ${niveau === n.id ? "btn--gold" : "btn--ghost"} btn--sm`}
            onClick={() => setNiveau(n.id)}
          >
            {n.label}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11.5, color: "var(--fg-3)", marginRight: 8 }}>
          {total} entrée{total > 1 ? "s" : ""}
        </span>
        <button
          className="btn btn--ghost btn--sm"
          onClick={() => void load(0, false)}
          disabled={loading}
        >
          <Icon.refresh size={11} /> {loading ? "Chargement…" : "Rafraîchir"}
        </button>
      </div>

      {error && (
        <div
          style={{
            margin: "12px 0",
            padding: "10px 14px",
            background: "rgba(220,80,80,0.10)",
            border: "1px solid rgba(220,80,80,0.30)",
            borderRadius: 6,
            fontSize: 12.5,
            color: "var(--fg-2)",
          }}
        >
          Erreur : {error}
        </div>
      )}

      <div
        style={{
          marginTop: 12,
          border: "1px solid var(--line)",
          borderRadius: 8,
          overflow: "hidden",
        }}
      >
        {items.length === 0 && !loading ? (
          <div style={{ padding: 30, textAlign: "center", color: "var(--fg-3)", fontSize: 12.5 }}>
            Aucune entrée de journal pour ce filtre.
          </div>
        ) : (
          items.map((log) => (
            <div
              key={log.id}
              style={{
                display: "flex",
                gap: 12,
                padding: "8px 14px",
                borderBottom: "1px solid var(--line)",
                fontSize: 12.5,
                alignItems: "baseline",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color: "var(--fg-4)",
                  whiteSpace: "nowrap",
                }}
              >
                {formatDate(log.cree_le)}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10.5,
                  letterSpacing: "0.06em",
                  color: "var(--gold)",
                  width: 64,
                  flexShrink: 0,
                }}
              >
                {log.agent}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  textTransform: "uppercase",
                  color: COULEUR_NIVEAU[log.niveau],
                  width: 64,
                  flexShrink: 0,
                }}
              >
                {log.niveau}
              </span>
              <span style={{ color: "var(--fg-2)", lineHeight: 1.5 }}>
                {log.message}
                {log.appel_offre_id != null && (
                  <span style={{ color: "var(--fg-4)", marginLeft: 6 }}>
                    · AO {log.appel_offre_id}
                  </span>
                )}
              </span>
            </div>
          ))
        )}
      </div>

      {items.length < total && (
        <div style={{ textAlign: "center", marginTop: 14 }}>
          <button
            className="btn btn--ghost btn--sm"
            disabled={loading}
            onClick={() => void load(items.length, true)}
          >
            Charger plus ({items.length} / {total})
          </button>
        </div>
      )}
    </div>
  );
}

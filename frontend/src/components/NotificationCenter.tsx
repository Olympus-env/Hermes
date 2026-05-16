import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";
import { api, type LogAgentEntry, type NiveauLog } from "../lib/api";

const SEEN_KEY = "hermes.notifsLastSeen";
const POLL_MS = 20_000;

const COULEUR_NIVEAU: Record<NiveauLog, string> = {
  debug: "var(--fg-4)",
  info: "var(--gold)",
  warning: "var(--warn, #e0a93b)",
  error: "#dc5050",
};

// Marqueurs d'événements « notables » remontés à l'utilisateur (en plus de
// tous les warning/error). Volontairement étroit : le journal complet reste
// disponible dans l'onglet Journal.
const MARQUEURS = [
  "réponse v", // HERMION : réponse vN générée
  "exportée en PDF",
  "Pipeline autonome",
  "Collecte ", // ARGOS : Collecte boamp : N nouveaux…
  "Analyse KRINOS terminée",
];

function estNotable(log: LogAgentEntry): boolean {
  if (log.niveau === "error" || log.niveau === "warning") return true;
  return MARQUEURS.some((m) => log.message.includes(m));
}

function tempsRelatif(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return "";
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `il y a ${h} h`;
  return `il y a ${Math.floor(h / 24)} j`;
}

type Props = { onOpenJournal?: () => void };

/**
 * Centre de notifications in-app : pastille + panneau alimentés par le
 * journal des agents (`/logs`). Remplace les notifications OS natives pour
 * la V1 (les vraies notifications système sont repoussées en V2 — elles
 * exigent un plugin Tauri/Rust).
 */
export function NotificationCenter({ onOpenJournal }: Props) {
  const [logs, setLogs] = useState<LogAgentEntry[]>([]);
  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<number>(() => {
    const raw = window.localStorage.getItem(SEEN_KEY);
    const t = raw ? Date.parse(raw) : 0;
    return Number.isNaN(t) ? 0 : t;
  });
  const timer = useRef<number | null>(null);

  const charger = useCallback(async () => {
    try {
      const page = await api.listerLogs({ limit: 50 });
      setLogs(page.items.filter(estNotable));
    } catch {
      // Pas critique : on garde l'état précédent.
    }
  }, []);

  useEffect(() => {
    void charger();
    timer.current = window.setInterval(() => void charger(), POLL_MS);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [charger]);

  const nonLus = useMemo(
    () => logs.filter((l) => Date.parse(l.cree_le) > lastSeen).length,
    [logs, lastSeen],
  );

  const ouvrir = () => {
    setOpen((o) => {
      const next = !o;
      if (next && logs.length > 0) {
        const recent = Math.max(...logs.map((l) => Date.parse(l.cree_le)));
        setLastSeen(recent);
        window.localStorage.setItem(SEEN_KEY, new Date(recent).toISOString());
      }
      return next;
    });
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        className="btn btn--ghost btn--sm"
        onClick={ouvrir}
        title="Notifications"
        style={{ position: "relative" }}
        aria-label={`Notifications${nonLus > 0 ? ` (${nonLus} non lues)` : ""}`}
      >
        <Icon.bell size={14} />
        {nonLus > 0 && (
          <span
            style={{
              position: "absolute",
              top: -4,
              right: -4,
              minWidth: 16,
              height: 16,
              padding: "0 4px",
              borderRadius: 8,
              background: "#dc5050",
              color: "#fff",
              fontSize: 10,
              fontWeight: 700,
              lineHeight: "16px",
              textAlign: "center",
            }}
          >
            {nonLus > 9 ? "9+" : nonLus}
          </span>
        )}
      </button>

      {open && (
        <>
          <div
            onClick={() => setOpen(false)}
            style={{ position: "fixed", inset: 0, zIndex: 40 }}
          />
          <div
            style={{
              position: "absolute",
              top: 32,
              right: 0,
              width: 380,
              maxHeight: 460,
              overflowY: "auto",
              background: "var(--bg-1, #15161a)",
              border: "1px solid var(--line-strong, #2a2c33)",
              borderRadius: 8,
              boxShadow: "0 12px 32px rgba(0,0,0,0.45)",
              zIndex: 41,
            }}
          >
            <div
              style={{
                padding: "10px 14px",
                borderBottom: "1px solid var(--line)",
                fontSize: 11,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--fg-3)",
              }}
            >
              Notifications
            </div>

            {logs.length === 0 ? (
              <div
                style={{
                  padding: 24,
                  textAlign: "center",
                  color: "var(--fg-3)",
                  fontSize: 12.5,
                }}
              >
                Rien à signaler pour l'instant.
              </div>
            ) : (
              logs.slice(0, 25).map((log) => (
                <div
                  key={log.id}
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: "9px 14px",
                    borderBottom: "1px solid var(--line)",
                    fontSize: 12.5,
                    alignItems: "baseline",
                  }}
                >
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 3,
                      background: COULEUR_NIVEAU[log.niveau],
                      flexShrink: 0,
                      marginTop: 5,
                    }}
                  />
                  <div style={{ flex: 1 }}>
                    <div style={{ color: "var(--fg-2)", lineHeight: 1.45 }}>
                      {log.message}
                    </div>
                    <div
                      style={{
                        marginTop: 2,
                        fontSize: 10.5,
                        color: "var(--fg-4)",
                        fontFamily: "var(--font-mono)",
                      }}
                    >
                      {log.agent} · {tempsRelatif(log.cree_le)}
                    </div>
                  </div>
                </div>
              ))
            )}

            {onOpenJournal && (
              <button
                className="btn btn--ghost btn--sm"
                style={{ width: "100%", borderRadius: 0, padding: "10px 0" }}
                onClick={() => {
                  setOpen(false);
                  onOpenJournal();
                }}
              >
                Voir le journal complet
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

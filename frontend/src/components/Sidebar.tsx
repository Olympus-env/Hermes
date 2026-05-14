import { AGENTS, type AgentKey, type AgentState } from "../lib/data";
import { AgentChip } from "./AgentChip";
import { GreekFrieze } from "./GreekFrieze";
import { HermesMark } from "./HermesMark";
import { Icon } from "./Icon";

export type ViewKey = "accueil" | "tenders" | "responses" | "settings";

type Item = {
  id: ViewKey;
  label: string;
  icon: (p: { size?: number }) => JSX.Element;
  count: number | null;
};

type Props = {
  active: ViewKey;
  onChange: (v: ViewKey) => void;
  agents: Record<AgentKey, AgentState>;
  tenderCount: number;
  responseCount: number;
  pendingValidationCount: number;
};

export function Sidebar({
  active,
  onChange,
  agents,
  tenderCount,
  pendingValidationCount,
}: Props) {
  const items: Item[] = [
    { id: "accueil",   label: "Accueil",        icon: Icon.home,     count: null },
    { id: "tenders",   label: "Appels d'offre", icon: Icon.document, count: tenderCount },
    { id: "responses", label: "Réponses",       icon: Icon.reply,    count: pendingValidationCount },
    { id: "settings",  label: "Paramètres",     icon: Icon.settings, count: null },
  ];

  return (
    <aside className="sidebar app__sidebar">
      <div className="sidebar__brand">
        <div className="sidebar__brand-mark">
          <HermesMark size={26} />
        </div>
        <div className="sidebar__brand-text">
          <span className="sidebar__brand-name">HERMES</span>
          <span className="sidebar__brand-sub">Veille · Réponse</span>
        </div>
      </div>

      <div className="sidebar__frieze">
        <GreekFrieze height={16} color="#C8A951" opacity={0.45} strokeWidth={1.3} />
      </div>

      <nav className="sidebar__nav">
        <div className="nav-section-title">Navigation</div>
        {items.map((it) => {
          const ActIcon = it.icon;
          return (
            <button
              key={it.id}
              className={`nav-item${active === it.id ? " nav-item--active" : ""}`}
              onClick={() => onChange(it.id)}
            >
              <ActIcon size={15} />
              <span>{it.label}</span>
              {it.count != null && it.count > 0 && (
                <span className="nav-item__count">{it.count}</span>
              )}
            </button>
          );
        })}
      </nav>

      <div style={{ flex: 1 }} />

      <div className="sidebar__frieze">
        <GreekFrieze height={14} color="#C8A951" opacity={0.38} strokeWidth={1.3} />
      </div>

      <div className="sidebar__agents">
        <div className="sidebar__agents-title">Agents</div>
        {(Object.entries(AGENTS) as [AgentKey, (typeof AGENTS)[AgentKey]][]).map(
          ([key, a]) => (
            <div className="sidebar__agent-row" key={key}>
              <AgentChip agent={key} state={agents[key]} compact />
              <span className="sidebar__agent-role">{a.role}</span>
            </div>
          ),
        )}
      </div>
    </aside>
  );
}

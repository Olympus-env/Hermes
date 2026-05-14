import { AGENTS, type AgentKey, type AgentState } from "../lib/data";
import {
  getProfileAvatarLetter,
  getProfileDisplayName,
  type UserProfile,
} from "../lib/userProfile";
import { AgentChip } from "./AgentChip";
import { Icon } from "./Icon";
import type { ViewKey } from "./Sidebar";

type Props = {
  active: ViewKey;
  agents: Record<AgentKey, AgentState>;
  nextCycle: string;
  profile: UserProfile;
};

const TITLES: Record<ViewKey, { main: string; sub: string }> = {
  accueil:   { main: "Accueil",        sub: "Vue d'ensemble" },
  tenders:   { main: "Appels d'offre", sub: "Veille active" },
  responses: { main: "Réponses",       sub: "File de validation" },
  settings:  { main: "Paramètres",     sub: "Configuration" },
};

export function Topbar({ active, agents, nextCycle, profile }: Props) {
  const t = TITLES[active];

  return (
    <header className="topbar app__topbar">
      <div className="topbar__inner">
        <div className="topbar__title">
          <span className="topbar__title-main">{t.main}</span>
          <span className="topbar__title-sub">— {t.sub}</span>
        </div>

        <div className="topbar__spacer" />

        <div className="topbar__agents">
          {(Object.keys(AGENTS) as AgentKey[]).map((k) => (
            <AgentChip key={k} agent={k} state={agents[k]} />
          ))}
        </div>

        <div className="topbar__cycle">
          <Icon.clock size={12} />
          <span>
            Prochain cycle ARGOS dans <strong>{nextCycle}</strong>
          </span>
        </div>

        <div className="topbar__user">
          <div className="topbar__user-avatar">{getProfileAvatarLetter(profile)}</div>
          <span className="topbar__user-name">{getProfileDisplayName(profile)}</span>
        </div>
      </div>
    </header>
  );
}

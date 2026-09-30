import { AnimatePresence, motion } from "motion/react";
import { RESSORT, TR_RAPIDE, TR_SORTIE } from "../lib/motion";
import { AGENTS, type AgentKey, type AgentState } from "../lib/data";
import {
  getProfileAvatarLetter,
  getProfileDisplayName,
  type UserProfile,
} from "../lib/userProfile";
import { AgentChip } from "./AgentChip";
import { Icon } from "./Icon";
import { NotificationCenter } from "./NotificationCenter";
import type { ViewKey } from "./Sidebar";

type Props = {
  active: ViewKey;
  agents: Record<AgentKey, AgentState>;
  nextCycle: string;
  profile: UserProfile;
  isLoading?: boolean;
  onLaunchArgos?: () => void;
  onOpenJournal?: () => void;
};

const TITLES: Record<ViewKey, { main: string; sub: string }> = {
  accueil:   { main: "Accueil",        sub: "Vue d'ensemble" },
  tenders:   { main: "Appels d'offre", sub: "Veille active" },
  responses: { main: "Réponses",       sub: "File de validation" },
  journal:   { main: "Journal",        sub: "Activité des agents" },
  settings:  { main: "Paramètres",     sub: "Configuration" },
};

export function Topbar({
  active,
  agents,
  nextCycle,
  profile,
  isLoading,
  onLaunchArgos,
  onOpenJournal,
}: Props) {
  const t = TITLES[active];

  return (
    <header className="topbar app__topbar">
      <div className="topbar__inner">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={active}
            className="topbar__title"
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0, transition: TR_RAPIDE }}
            exit={{ opacity: 0, x: 4, transition: TR_SORTIE }}
          >
            <span className="topbar__title-main">{t.main}</span>
            <span className="topbar__title-sub">— {t.sub}</span>
          </motion.div>
        </AnimatePresence>

        <div className="topbar__spacer" />

        <div className="topbar__agents">
          {(Object.keys(AGENTS) as AgentKey[]).map((k) => (
            <AgentChip key={k} agent={k} state={agents[k]} />
          ))}
        </div>

        <div className="topbar__cycle">
          <Icon.clock size={12} />
          <span>
            Prochain cycle dans <strong>{nextCycle}</strong>
          </span>
          {onLaunchArgos && (
            <motion.button
              className="btn btn--gold btn--sm"
              style={{ marginLeft: 8 }}
              whileHover={isLoading ? undefined : { y: -1 }}
              whileTap={isLoading ? undefined : { scale: 0.96 }}
              transition={RESSORT.net}
              onClick={onLaunchArgos}
              disabled={isLoading}
              title="Déclenche immédiatement une collecte ARGOS (sans attendre le cycle)"
            >
              <Icon.refresh size={11} />
              {isLoading ? "Collecte…" : "Lancer ARGOS"}
            </motion.button>
          )}
        </div>

        <div style={{ marginLeft: 12 }}>
          <NotificationCenter onOpenJournal={onOpenJournal} />
        </div>

        <div className="topbar__user">
          <div className="topbar__user-avatar">{getProfileAvatarLetter(profile)}</div>
          <span className="topbar__user-name">{getProfileDisplayName(profile)}</span>
        </div>
      </div>
    </header>
  );
}

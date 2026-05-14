import { useEffect } from "react";
import { AGENTS } from "../lib/data";
import type { ToastInput } from "../lib/toast";
import { HermesMark } from "./HermesMark";
import { Icon } from "./Icon";

type Props = {
  toast: ToastInput | null;
  onClose: () => void;
};

export function Toast({ toast, onClose }: Props) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onClose, 6500);
    return () => clearTimeout(t);
  }, [toast, onClose]);

  if (!toast) return null;

  const agent = AGENTS[toast.agent];
  const agentColor = agent ? agent.color : "var(--hermion)";

  return (
    <div className="toast">
      <div
        className="toast__icon"
        style={{
          background: `linear-gradient(135deg, ${agentColor}33, ${agentColor}11)`,
          borderColor: `${agentColor}44`,
        }}
      >
        <HermesMark size={18} color={agentColor} />
      </div>
      <div className="toast__body">
        <div className="toast__title">
          <span className="toast__title-agent" style={{ color: agentColor }}>
            {toast.title}
          </span>
          <span style={{ color: "var(--fg-4)" }}>—</span>
          <span style={{ color: "var(--fg-2)", fontWeight: 500 }}>{toast.app}</span>
          <span className="toast__title-app">HERMES</span>
        </div>
        <div className="toast__msg">{toast.msg}</div>
      </div>
      <button className="toast__close" onClick={onClose}>
        <Icon.close size={12} />
      </button>
    </div>
  );
}

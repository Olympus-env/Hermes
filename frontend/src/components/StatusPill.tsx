import { RESPONSE_STATUS, type ResponseStatus } from "../lib/data";

type Props = { status: ResponseStatus };

export function StatusPill({ status }: Props) {
  const s = RESPONSE_STATUS[status];
  return (
    <span
      className="status-pill"
      style={{ color: s.color, background: s.bg, borderColor: s.color + "33" }}
    >
      <span className="status-pill__dot" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

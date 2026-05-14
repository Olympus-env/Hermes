import type { TagTone } from "../lib/data";

type Props = { label: string; tone?: TagTone };

export function Tag({ label, tone = "gold" }: Props) {
  return <span className={`tag tag--${tone}`}>{label}</span>;
}

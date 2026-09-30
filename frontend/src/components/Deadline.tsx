import { deadlineInfo } from "../lib/data";
import { Icon } from "./Icon";

type Props = { date: string | null };

export function Deadline({ date }: Props) {
  const { formatted, days, urgent, echu } = deadlineInfo(date);
  return (
    <div className={`deadline${urgent ? " deadline--urgent" : ""}`}>
      <Icon.clock size={12} />
      <span>{formatted}</span>
      {urgent && <span className="deadline__days">J−{days}</span>}
      {echu && <span className="deadline__echu">Échu</span>}
    </div>
  );
}

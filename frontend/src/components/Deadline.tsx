import { deadlineInfo } from "../lib/data";
import { Icon } from "./Icon";

type Props = { date: string };

export function Deadline({ date }: Props) {
  const { formatted, days, urgent } = deadlineInfo(date);
  return (
    <div className={`deadline${urgent ? " deadline--urgent" : ""}`}>
      <Icon.clock size={12} />
      <span>{formatted}</span>
      {urgent && <span className="deadline__days">J−{days}</span>}
    </div>
  );
}

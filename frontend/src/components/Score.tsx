type Props = { value: number; large?: boolean };

export function Score({ value, large = false }: Props) {
  const tone = value >= 70 ? "high" : value >= 40 ? "mid" : "low";
  return (
    <div className={`score score--${tone}${large ? " score--lg" : ""}`}>
      <span className="score__val">{value}</span>
      {large && <span className="score__max">/100</span>}
    </div>
  );
}

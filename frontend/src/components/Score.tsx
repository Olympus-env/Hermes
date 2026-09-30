import { motion } from "motion/react";
import { COURBE, DUREE } from "../lib/motion";

type Props = { value: number; large?: boolean };

export function Score({ value, large = false }: Props) {
  const tone = value >= 70 ? "high" : value >= 40 ? "mid" : "low";
  const ratio = Math.min(1, Math.max(0, value / 100));
  return (
    <div className={`score score--${tone}${large ? " score--lg" : ""}`}>
      <span className="score__val">{value}</span>
      {large && <span className="score__max">/100</span>}
      {/* Jauge KRINOS : se remplit à l'apparition et suit le score s'il change */}
      <motion.span
        className="score__jauge"
        aria-hidden="true"
        initial={{ scaleX: 0 }}
        animate={{ scaleX: ratio }}
        transition={{ duration: DUREE.lente, ease: [...COURBE.sortie] }}
      />
    </div>
  );
}

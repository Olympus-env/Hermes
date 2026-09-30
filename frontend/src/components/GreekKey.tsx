import { motion } from "motion/react";

type Props = {
  width?: number;
  color?: string;
  opacity?: number;
  strokeWidth?: number;
  /** Trace la clé en or (ouverture) : le filet puis chaque méandre se dessinent. */
  trace?: boolean;
  /** Retard avant le début du tracé, en secondes (avec `trace`). */
  retard?: number;
};

const MEANDRES = [2, 22, 42, 62].map(
  (x) => `M${x} 15 L${x} 3 L${x + 11} 3 L${x + 11} 12 L${x + 4} 12 L${x + 4} 6 L${x + 8} 6 L${x + 8} 9`,
);

// Motif greek key fixe (4 unités) — pour l'état vide.
export function GreekKey({
  width = 96,
  color = "#C8A951",
  opacity = 0.65,
  strokeWidth = 1.6,
  trace = false,
  retard = 0,
}: Props) {
  const height = width * (16 / 80);
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 80 16"
      fill="none"
      stroke={color}
      strokeWidth={strokeWidth}
      strokeLinejoin="miter"
      strokeLinecap="square"
      opacity={opacity}
      style={{ display: "block" }}
    >
      {trace ? (
        <>
          <motion.line
            x1="0"
            y1="15"
            x2="80"
            y2="15"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.5, delay: retard, ease: "easeOut" }}
          />
          {MEANDRES.map((d, i) => (
            <motion.path
              key={d}
              d={d}
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.35, delay: retard + 0.12 + i * 0.1, ease: "easeOut" }}
            />
          ))}
        </>
      ) : (
        <>
          <line x1="0" y1="15" x2="80" y2="15" />
          {MEANDRES.map((d) => (
            <path key={d} d={d} />
          ))}
        </>
      )}
    </svg>
  );
}

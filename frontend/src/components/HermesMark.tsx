import { motion } from "motion/react";

type Props = {
  size?: number;
  color?: string;
  /** Anime le tracé du logo (ouverture) : les traits se dessinent puis les points apparaissent. */
  trace?: boolean;
  /** Durée du tracé en secondes (avec `trace`). */
  duree?: number;
};

const TRAITS = [
  "M16 3 L16 29",
  "M16 8 C 11 7, 8 8.5, 6 11",
  "M16 8 C 21 7, 24 8.5, 26 11",
  "M16 10 C 12 10, 9.5 11, 8 13",
  "M16 10 C 20 10, 22.5 11, 24 13",
  "M11 14 C 14 17, 18 17, 21 20 C 18 23, 14 23, 11 26",
  "M21 14 C 18 17, 14 17, 11 20 C 14 23, 18 23, 21 26",
];
const POINTS = [
  { cx: 16, cy: 4, r: 1.4 },
  { cx: 10.6, cy: 13.6, r: 0.9 },
  { cx: 21.4, cy: 13.6, r: 0.9 },
];

export function HermesMark({ size = 28, color = "#C8A951", trace = false, duree = 0.8 }: Props) {
  if (trace) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {TRAITS.map((d, i) => (
          <motion.path
            key={d}
            d={d}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: duree * 0.7, delay: i * (duree * 0.05), ease: "easeOut" }}
          />
        ))}
        {POINTS.map((p, i) => (
          <motion.circle
            key={i}
            {...p}
            fill={color}
            stroke="none"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.2, delay: duree * 0.8 }}
          />
        ))}
      </svg>
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="16" y1="3" x2="16" y2="29" />
      <circle cx="16" cy="4" r="1.4" fill={color} stroke="none" />
      <path d="M16 8 C 11 7, 8 8.5, 6 11" />
      <path d="M16 8 C 21 7, 24 8.5, 26 11" />
      <path d="M16 10 C 12 10, 9.5 11, 8 13" />
      <path d="M16 10 C 20 10, 22.5 11, 24 13" />
      <path d="M11 14 C 14 17, 18 17, 21 20 C 18 23, 14 23, 11 26" />
      <path d="M21 14 C 18 17, 14 17, 11 20 C 14 23, 18 23, 21 26" />
      <circle cx="10.6" cy="13.6" r="0.9" fill={color} stroke="none" />
      <circle cx="21.4" cy="13.6" r="0.9" fill={color} stroke="none" />
    </svg>
  );
}

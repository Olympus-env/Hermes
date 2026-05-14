import { useId } from "react";

type Props = {
  height?: number;
  color?: string;
  opacity?: number;
  strokeWidth?: number;
};

// Bandeau de clé grecque tilable — séparateur de section pleine largeur.
export function GreekFrieze({
  height = 20,
  color = "#C8A951",
  opacity = 0.55,
  strokeWidth = 1.3,
}: Props) {
  const id = "frieze-" + useId().replace(/[:]/g, "");
  const cellW = height * (20 / 16);
  return (
    <svg width="100%" height={height} style={{ display: "block" }}>
      <defs>
        <pattern
          id={id}
          width={cellW}
          height={height}
          patternUnits="userSpaceOnUse"
        >
          <g
            stroke={color}
            strokeWidth={strokeWidth}
            fill="none"
            strokeLinejoin="miter"
            strokeLinecap="square"
            opacity={opacity}
            transform={`scale(${height / 16})`}
          >
            <path d="M2 15 L2 3 L13 3 L13 12 L6 12 L6 6 L10 6 L10 9" />
            <line x1="0" y1="15" x2="20" y2="15" />
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}

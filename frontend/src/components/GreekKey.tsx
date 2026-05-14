type Props = {
  width?: number;
  color?: string;
  opacity?: number;
  strokeWidth?: number;
};

// Motif greek key fixe (4 unités) — pour l'état vide.
export function GreekKey({
  width = 96,
  color = "#C8A951",
  opacity = 0.65,
  strokeWidth = 1.6,
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
      <line x1="0" y1="15" x2="80" y2="15" />
      <path d="M2 15 L2 3 L13 3 L13 12 L6 12 L6 6 L10 6 L10 9" />
      <path d="M22 15 L22 3 L33 3 L33 12 L26 12 L26 6 L30 6 L30 9" />
      <path d="M42 15 L42 3 L53 3 L53 12 L46 12 L46 6 L50 6 L50 9" />
      <path d="M62 15 L62 3 L73 3 L73 12 L66 12 L66 6 L70 6 L70 9" />
    </svg>
  );
}

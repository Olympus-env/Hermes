type Props = { size?: number; color?: string };

export function HermesMark({ size = 28, color = "#C8A951" }: Props) {
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

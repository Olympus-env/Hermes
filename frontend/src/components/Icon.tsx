// Icônes line-glyph (vocabulaire Linear / Raycast).
import type { JSX } from "react";

type IconProps = { size?: number };

const wrap = (size: number, children: JSX.Element) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    {children}
  </svg>
);

export const Icon = {
  home: ({ size = 16 }: IconProps) =>
    wrap(size, <path d="M2 7 L8 2 L14 7 L14 14 L10 14 L10 9 L6 9 L6 14 L2 14 Z" />),

  document: ({ size = 16 }: IconProps) =>
    wrap(
      size,
      <>
        <path d="M3 2 L10 2 L13 5 L13 14 L3 14 Z" />
        <path d="M10 2 L10 5 L13 5" />
        <line x1="5.5" y1="8" x2="10.5" y2="8" />
        <line x1="5.5" y1="11" x2="10.5" y2="11" />
      </>,
    ),

  reply: ({ size = 16 }: IconProps) =>
    wrap(
      size,
      <>
        <path d="M6 4 L2 8 L6 12" />
        <path d="M2 8 L11 8 C 13 8, 14 9.5, 14 11.5 L14 13" />
      </>,
    ),

  settings: ({ size = 16 }: IconProps) =>
    wrap(
      size,
      <>
        <circle cx="8" cy="8" r="2" />
        <path d="M8 1.5 L8 3.5 M8 12.5 L8 14.5 M1.5 8 L3.5 8 M12.5 8 L14.5 8 M3.4 3.4 L4.8 4.8 M11.2 11.2 L12.6 12.6 M3.4 12.6 L4.8 11.2 M11.2 4.8 L12.6 3.4" />
      </>,
    ),

  search: ({ size = 14 }: IconProps) =>
    wrap(
      size,
      <>
        <circle cx="7" cy="7" r="4.5" />
        <line x1="10.5" y1="10.5" x2="14" y2="14" />
      </>,
    ),

  download: ({ size = 14 }: IconProps) =>
    wrap(
      size,
      <>
        <path d="M8 2 L8 11 M4.5 7.5 L8 11 L11.5 7.5" />
        <path d="M2.5 13.5 L13.5 13.5" />
      </>,
    ),

  mail: ({ size = 14 }: IconProps) =>
    wrap(
      size,
      <>
        <rect x="2" y="3.5" width="12" height="9" rx="1" />
        <path d="M2.5 4.5 L8 9 L13.5 4.5" />
      </>,
    ),

  check: ({ size = 14 }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 8.5 L6.5 12 L13 4" />
    </svg>
  ),

  close: ({ size = 14 }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="4" y1="4" x2="12" y2="12" />
      <line x1="12" y1="4" x2="4" y2="12" />
    </svg>
  ),

  warning: ({ size = 14 }: IconProps) =>
    wrap(
      size,
      <>
        <path d="M8 2 L14.5 13.5 L1.5 13.5 Z" />
        <line x1="8" y1="6" x2="8" y2="9.5" />
        <circle cx="8" cy="11.5" r="0.5" fill="currentColor" />
      </>,
    ),

  plus: ({ size = 14 }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="8" y1="3" x2="8" y2="13" />
      <line x1="3" y1="8" x2="13" y2="8" />
    </svg>
  ),

  filter: ({ size = 14 }: IconProps) =>
    wrap(size, <path d="M2 3 L14 3 L10 8 L10 13 L6 11 L6 8 Z" />),

  chevron: ({ size = 12 }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 4 L10 8 L6 12" />
    </svg>
  ),

  refresh: ({ size = 14 }: IconProps) =>
    wrap(
      size,
      <>
        <path d="M2.5 8 A 5.5 5.5 0 0 1 13 5.5" />
        <path d="M13.5 8 A 5.5 5.5 0 0 1 3 10.5" />
        <path d="M11 2.5 L13.2 5.5 L10 6" />
        <path d="M5 13.5 L2.8 10.5 L6 10" />
      </>,
    ),

  clock: ({ size = 14 }: IconProps) =>
    wrap(
      size,
      <>
        <circle cx="8" cy="8" r="6" />
        <path d="M8 4.5 L8 8 L10.5 9.5" />
      </>,
    ),

  inbox: ({ size = 14 }: IconProps) =>
    wrap(
      size,
      <>
        <path d="M2 9 L5 9 L6 11 L10 11 L11 9 L14 9" />
        <path d="M2 9 L4 3 L12 3 L14 9 L14 13 L2 13 Z" />
      </>,
    ),
};

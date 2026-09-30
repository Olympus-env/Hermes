// Tokens de mouvement HERMES — miroir TypeScript des variables --dur-* / --ease-*
// de index.css. Un seul vocabulaire : mouvements courts (150–400 ms), ressorts
// discrets, uniquement transform/opacity (60 i/s). `prefers-reduced-motion` est
// géré globalement par <MotionConfig reducedMotion="user"> dans App.tsx.
import type { Transition, Variants } from "motion/react";

/** Durées en secondes. */
export const DUREE = {
  rapide: 0.15,
  base: 0.24,
  lente: 0.4,
} as const;

/** Courbes cubic-bezier (identiques à --ease-sortie / --ease-entree / --ease-doux). */
export const COURBE = {
  sortie: [0.2, 0.7, 0.2, 1],
  entree: [0.5, 0, 0.9, 0.4],
  doux: [0.4, 0, 0.2, 1],
} as const;

/** Ressorts discrets : peu de rebond, pas d'effet gadget. */
export const RESSORT = {
  doux: { type: "spring", stiffness: 380, damping: 34, mass: 0.9 },
  net: { type: "spring", stiffness: 520, damping: 38 },
  pastille: { type: "spring", stiffness: 600, damping: 22 },
} as const satisfies Record<string, Transition>;

export const TR_BASE: Transition = { duration: DUREE.base, ease: [...COURBE.sortie] };
export const TR_RAPIDE: Transition = { duration: DUREE.rapide, ease: [...COURBE.sortie] };
export const TR_SORTIE: Transition = { duration: DUREE.rapide, ease: [...COURBE.entree] };

/** Transition entre vues : sortie courte puis entrée (mode "wait"). */
export const VARIANTES_VUE: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: TR_BASE },
  exit: { opacity: 0, y: -4, transition: TR_SORTIE },
};

/** Apparition depuis le bas (toasts). */
export const VARIANTES_TOAST: Variants = {
  initial: { opacity: 0, y: 20, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1, transition: RESSORT.doux },
  exit: { opacity: 0, y: 12, scale: 0.98, transition: TR_SORTIE },
};

/** Fond de modale. */
export const VARIANTES_FOND: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: DUREE.base } },
  exit: { opacity: 0, transition: { duration: DUREE.rapide } },
};

/** Panneau de modale : léger zoom en ressort. */
export const VARIANTES_MODALE: Variants = {
  initial: { opacity: 0, y: 14, scale: 0.97 },
  animate: { opacity: 1, y: 0, scale: 1, transition: RESSORT.doux },
  exit: { opacity: 0, y: 8, scale: 0.98, transition: TR_SORTIE },
};

/** Panneau déroulant ancré en haut à droite (centre de notifications). */
export const VARIANTES_POPOVER: Variants = {
  initial: { opacity: 0, y: -6, scale: 0.97 },
  animate: { opacity: 1, y: 0, scale: 1, transition: RESSORT.net },
  exit: { opacity: 0, y: -4, scale: 0.98, transition: TR_SORTIE },
};

/** Conteneur + enfants décalés (état vide). */
export const VARIANTES_LISTE: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.06, delayChildren: 0.05 } },
};
export const VARIANTES_ELEMENT: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: TR_BASE },
};

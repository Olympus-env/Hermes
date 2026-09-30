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
  /** Compteurs et jauges qui se remplissent (miroir de --dur-compteur). */
  compteur: 0.8,
  /** Filet de tuile (Accueil) et frise de l'en-tête (App.tsx) qui se tracent. */
  frise: 0.7,
  /** Respiration de l'agent « en cours » (miroir de --dur-souffle). */
  souffle: 1.4,
} as const;

/** Accueil : décalage entre tuiles, délai des filets et de la liste d'activité. */
export const DECALAGE_TUILES = 0.05;
export const DELAI_FILET = 0.2;
export const DELAI_ACTIVITE = 0.3;

/** Cascade des listes : décalage entre deux éléments, plafonné pour rester vif. */
export const DECALAGE_CASCADE = 0.04;
export const CASCADE_MAX = 8;
/** Délai d'entrée d'un élément de liste selon son rang (plafonné). */
export const delaiCascade = (rang: number): number => Math.min(rang, CASCADE_MAX) * DECALAGE_CASCADE;

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

/** Carte de liste (Veille, Réponses) : entrée en cascade via `custom` = rang. */
export const VARIANTES_CARTE: Variants = {
  initial: { opacity: 0, y: 10 },
  animate: (rang: number = 0) => ({
    opacity: 1,
    y: 0,
    transition: { ...TR_BASE, delay: delaiCascade(rang) },
  }),
  exit: { opacity: 0, transition: TR_SORTIE },
};

/** Panneau de détail en maître-détail : glisse depuis la droite. */
export const VARIANTES_PANNEAU: Variants = {
  initial: { opacity: 0, x: 28 },
  animate: { opacity: 1, x: 0, transition: RESSORT.doux },
  exit: { opacity: 0, x: 12, transition: TR_SORTIE },
};

/** Badge qui apparaît (À vérifier, Hors profil, statut de validation). */
export const VARIANTES_BADGE: Variants = {
  initial: { opacity: 0, scale: 0.8 },
  animate: { opacity: 1, scale: 1, transition: RESSORT.pastille },
  exit: { opacity: 0, scale: 0.9, transition: TR_SORTIE },
};

/** Nouvelle entrée de journal : glisse en tête depuis le haut. */
export const VARIANTES_ENTREE_JOURNAL: Variants = {
  initial: { opacity: 0, y: -12 },
  animate: { opacity: 1, y: 0, transition: TR_BASE },
  exit: { opacity: 0, transition: TR_SORTIE },
};

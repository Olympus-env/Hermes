import { motion } from "motion/react";
import { useEffect } from "react";
import { COURBE } from "../lib/motion";
import { GreekKey } from "./GreekKey";
import { HermesMark } from "./HermesMark";

/** Durée d'affichage avant fondu de sortie (ms) — total < 1,2 s avec le fondu. */
const DUREE_MS = 950;

/**
 * Animation d'ouverture HERMES : logo et clé grecque se tracent en or sur fond
 * nuit. Jouée une fois par lancement (voir App.tsx), passable au clic ou à une
 * touche, ignorée si `prefers-reduced-motion`.
 */
export function Ouverture({ onFin }: { onFin: () => void }) {
  useEffect(() => {
    const t = setTimeout(onFin, DUREE_MS);
    const touche = () => onFin();
    window.addEventListener("keydown", touche);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", touche);
    };
  }, [onFin]);

  return (
    <motion.div
      className="ouverture"
      role="presentation"
      onClick={onFin}
      initial={{ opacity: 1 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.22, ease: [...COURBE.doux] } }}
    >
      <HermesMark size={72} trace duree={0.7} />
      <motion.span
        className="ouverture__nom"
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.45, ease: [...COURBE.sortie] }}
      >
        HERMES
      </motion.span>
      <GreekKey width={200} opacity={0.7} strokeWidth={1.4} trace retard={0.2} />
      <span className="ouverture__passer">Cliquer pour passer</span>
    </motion.div>
  );
}

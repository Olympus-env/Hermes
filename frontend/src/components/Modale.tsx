import { motion, type HTMLMotionProps } from "motion/react";
import { VARIANTES_FOND, VARIANTES_MODALE } from "../lib/motion";

/** Fond de modale : fondu ; la sortie n'est jouée que sous un <AnimatePresence>. */
export function ModaleFond(props: HTMLMotionProps<"div">) {
  return (
    <motion.div
      className="modal-backdrop"
      variants={VARIANTES_FOND}
      initial="initial"
      animate="animate"
      exit="exit"
      {...props}
    />
  );
}

/** Panneau de modale : apparition en ressort discret. */
export function ModalePanneau(props: HTMLMotionProps<"div">) {
  return (
    <motion.div
      className="modal"
      variants={VARIANTES_MODALE}
      initial="initial"
      animate="animate"
      exit="exit"
      {...props}
    />
  );
}

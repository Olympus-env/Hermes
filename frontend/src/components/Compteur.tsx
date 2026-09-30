import { animate, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { COURBE, DUREE } from "../lib/motion";

type Props = {
  valeur: number;
  /** Mise en forme du nombre affiché (ex. séparateurs fr-FR). */
  formater?: (n: number) => string;
};

/** Nombre qui monte jusqu'à sa valeur (compteurs d'Accueil). Direct si reduced-motion. */
export function Compteur({ valeur, formater = (n) => String(n) }: Props) {
  const reduire = useReducedMotion();
  const [affiche, setAffiche] = useState(reduire ? valeur : 0);
  const depart = useRef(reduire ? valeur : 0);

  useEffect(() => {
    if (reduire) {
      depart.current = valeur;
      setAffiche(valeur);
      return;
    }
    const anim = animate(depart.current, valeur, {
      duration: DUREE.compteur,
      ease: [...COURBE.sortie],
      onUpdate: (v) => {
        depart.current = v;
        setAffiche(Math.round(v));
      },
    });
    return () => anim.stop();
  }, [valeur, reduire]);

  return <>{formater(affiche)}</>;
}

// Comportements « desktop natif » de HERMES : l'app packagée ne doit pas se
// comporter comme une page web (menu contextuel, F5, zoom, glisser-déposer…).
// En mode dev (`npm run dev`) tout reste permis pour pouvoir inspecter.
// La mémorisation de la fenêtre relève du plugin Tauri (hors de ce module).
import type { ViewKey } from "../components/Sidebar";

/** Vrai dans l'app packagée (build de production). */
const EST_PROD = import.meta.env.PROD;

/** Ordre des vues pour Ctrl/Cmd+1…5. */
export const VUES_RACCOURCIS: ViewKey[] = ["accueil", "tenders", "responses", "journal", "settings"];

/** Évènement émis par Ctrl/Cmd+K : la vue Veille peut s'y abonner pour focaliser sa recherche. */
export const EVT_RECHERCHE = "hermes:recherche";

function estChampSaisie(cible: EventTarget | null): boolean {
  if (!(cible instanceof HTMLElement)) return false;
  if (cible.isContentEditable) return true;
  if (cible instanceof HTMLTextAreaElement) return true;
  if (cible instanceof HTMLInputElement) {
    return !["button", "checkbox", "radio", "submit", "reset", "range", "file"].includes(
      cible.type,
    );
  }
  return cible instanceof HTMLSelectElement;
}

type Options = {
  /** Navigation par raccourci clavier. */
  onNaviguer: (vue: ViewKey) => void;
};

/**
 * Installe les garde-fous natifs et les raccourcis d'app ; renvoie la fonction
 * de désinstallation (utile à StrictMode).
 */
export function installerComportementsNatifs({ onNaviguer }: Options): () => void {
  const ecouteurs: Array<[keyof DocumentEventMap, (e: never) => void, AddEventListenerOptions?]> = [];
  const ecouter = <K extends keyof DocumentEventMap>(
    type: K,
    fn: (e: DocumentEventMap[K]) => void,
    options?: AddEventListenerOptions,
  ) => {
    document.addEventListener(type, fn, options);
    ecouteurs.push([type, fn as (e: never) => void, options]);
  };

  // Raccourcis d'app (actifs aussi en dev).
  ecouter("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (!mod || e.altKey) return;
    if (/^[1-5]$/.test(e.key)) {
      e.preventDefault();
      onNaviguer(VUES_RACCOURCIS[Number(e.key) - 1]);
    } else if (e.key === ",") {
      e.preventDefault();
      onNaviguer("settings");
    } else if (e.key.toLowerCase() === "k") {
      e.preventDefault();
      onNaviguer("tenders");
      // Laisse la vue se monter avant de prévenir ses abonnés éventuels.
      window.setTimeout(() => window.dispatchEvent(new Event(EVT_RECHERCHE)), 50);
    }
  });

  // Toujours : pas de glisser-déposer natif d'images/liens.
  ecouter("dragstart", (e) => {
    if (e.target instanceof HTMLElement && e.target.closest("img, a")) e.preventDefault();
  });

  if (EST_PROD) {
    ecouter("contextmenu", (e) => {
      if (!estChampSaisie(e.target)) e.preventDefault();
    });

    ecouter("keydown", (e) => {
      const mod = e.ctrlKey || e.metaKey;
      const touche = e.key.toLowerCase();
      const bloque =
        e.key === "F5" ||
        (mod && ["r", "p"].includes(touche)) ||
        (mod && ["+", "-", "=", "0"].includes(e.key)) ||
        (e.key === "Backspace" && !estChampSaisie(e.target)) ||
        (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight"));
      if (bloque) e.preventDefault();
    });

    // Pas de zoom Ctrl+molette ni de pinch (trackpad : wheel + ctrlKey).
    ecouter("wheel", (e) => {
      if (e.ctrlKey) e.preventDefault();
    }, { passive: false });
    for (const geste of ["gesturestart", "gesturechange"] as const) {
      document.addEventListener(geste, prevenir as EventListener);
      ecouteurs.push([geste as keyof DocumentEventMap, prevenir as (e: never) => void]);
    }
  }

  return () => {
    for (const [type, fn, options] of ecouteurs) {
      document.removeEventListener(type, fn as EventListener, options);
    }
  };
}

function prevenir(e: Event) {
  e.preventDefault();
}

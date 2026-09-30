/**
 * Intégration système (Tauri) : notifications, zone de notification, dialogues natifs.
 *
 * Tout est détecté à l'exécution : hors Tauri (`npm run dev` dans un navigateur),
 * chaque fonction se replie sur un équivalent web ou ne fait rien. Aucun appel
 * externe — les notifications sont locales, générées par le frontend.
 */

// --------------------------------------------------------------------------- //
// Détection de l'environnement
// --------------------------------------------------------------------------- //

export function estTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

// --------------------------------------------------------------------------- //
// Préférences (localStorage, comme le profil utilisateur)
// --------------------------------------------------------------------------- //

export type TypeNotification = "nouvel_ao" | "reponse_prete" | "panne_argos";

export type PreferencesBureau = {
  nouvelAo: boolean;
  reponsePrete: boolean;
  panneArgos: boolean;
  /** Fermer la fenêtre réduit HERMES dans la zone de notification. */
  reduireDansTray: boolean;
  /** Silence temporaire (menu « Mettre en pause » du tray). */
  pause: boolean;
};

const PREFS_KEY = "hermes.preferencesBureau";
export const EVENT_PREFS = "hermes:preferences-bureau";

const PREFS_DEFAUT: PreferencesBureau = {
  nouvelAo: true,
  reponsePrete: true,
  panneArgos: true,
  reduireDansTray: false,
  pause: false,
};

export function chargerPreferencesBureau(): PreferencesBureau {
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    return { ...PREFS_DEFAUT, ...(raw ? JSON.parse(raw) : {}) };
  } catch {
    return { ...PREFS_DEFAUT };
  }
}

export function enregistrerPreferencesBureau(prefs: PreferencesBureau): void {
  window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  window.dispatchEvent(new CustomEvent(EVENT_PREFS));
  void synchroniserReductionTray(prefs.reduireDansTray);
}

// --------------------------------------------------------------------------- //
// Tauri : commandes et événements (imports dynamiques → aucun coût en mode web)
// --------------------------------------------------------------------------- //

/** Informe le Rust du réglage « réduire à la fermeture » (faux par défaut côté Rust). */
export async function synchroniserReductionTray(actif: boolean): Promise<void> {
  if (!estTauri()) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("definir_reduire_dans_tray", { actif });
  } catch {
    // Pas critique : la fermeture de la fenêtre quitte alors normalement l'app.
  }
}

/** Écoute un événement émis par le tray ; renvoie la fonction de désabonnement. */
export async function ecouterEvenementTray(
  nom: "hermes-tray-veille" | "hermes-tray-pause",
  action: () => void,
): Promise<() => void> {
  if (!estTauri()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen(nom, action);
}

// --------------------------------------------------------------------------- //
// Notifications système
// --------------------------------------------------------------------------- //

function typeActif(prefs: PreferencesBureau, type: TypeNotification): boolean {
  if (prefs.pause) return false;
  return type === "nouvel_ao"
    ? prefs.nouvelAo
    : type === "reponse_prete"
      ? prefs.reponsePrete
      : prefs.panneArgos;
}

async function permissionAccordee(): Promise<boolean> {
  const { isPermissionGranted, requestPermission } = await import(
    "@tauri-apps/plugin-notification"
  );
  if (await isPermissionGranted()) return true;
  return (await requestPermission()) === "granted";
}

/**
 * Affiche une notification système si le type est activé. Hors Tauri : rien
 * (le centre de notifications in-app et les toasts couvrent le mode web).
 * Renvoie vrai si elle a été émise.
 */
export async function notifierBureau(
  type: TypeNotification,
  titre: string,
  corps: string,
): Promise<boolean> {
  if (!estTauri() || !typeActif(chargerPreferencesBureau(), type)) return false;
  try {
    if (!(await permissionAccordee())) return false;
    const { sendNotification } = await import("@tauri-apps/plugin-notification");
    sendNotification({ title: titre, body: corps });
    return true;
  } catch {
    return false;
  }
}

// --------------------------------------------------------------------------- //
// Dialogues natifs
// --------------------------------------------------------------------------- //

function telechargerViaNavigateur(blob: Blob, nomFichier: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nomFichier;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * Enregistre un PDF : dialogue « Enregistrer sous » natif dans Tauri, téléchargement
 * navigateur sinon. Renvoie le chemin choisi, `null` si annulé (ou en mode web).
 */
export async function enregistrerPdf(blob: Blob, nomFichier: string): Promise<string | null> {
  if (!estTauri()) {
    telechargerViaNavigateur(blob, nomFichier);
    return null;
  }
  const { save } = await import("@tauri-apps/plugin-dialog");
  const chemin = await save({
    defaultPath: nomFichier,
    filters: [{ name: "Document PDF", extensions: ["pdf"] }],
  });
  if (!chemin) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("enregistrer_fichier", new Uint8Array(await blob.arrayBuffer()), {
    headers: { chemin: encodeURIComponent(chemin) },
  });
  return chemin;
}

/**
 * Choix de fichiers : dialogue natif dans Tauri (chemins), sélecteur `<input>` sinon
 * (objets `File`). Liste vide si annulé.
 */
export async function choisirFichiers(
  options: { extensions?: string[]; multiple?: boolean } = {},
): Promise<(string | File)[]> {
  if (estTauri()) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const choix = await open({
      multiple: options.multiple ?? false,
      filters: options.extensions ? [{ name: "Fichiers", extensions: options.extensions }] : [],
    });
    return choix === null ? [] : Array.isArray(choix) ? choix : [choix];
  }
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = options.multiple ?? false;
    if (options.extensions) input.accept = options.extensions.map((e) => `.${e}`).join(",");
    input.onchange = () => resolve(Array.from(input.files ?? []));
    input.oncancel = () => resolve([]);
    input.click();
  });
}

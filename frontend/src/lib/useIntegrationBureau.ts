import { useEffect, useRef } from "react";
import type { ViewKey } from "../components/Sidebar";
import { api } from "./api";
import {
  chargerPreferencesBureau,
  ecouterEvenementTray,
  enregistrerPreferencesBureau,
  estTauri,
  notifierBureau,
  synchroniserReductionTray,
} from "./desktop";

const SONDAGE_MS = 60_000;
// Le plugin de notification ne remonte pas le clic sur desktop : on retient la vue
// de la dernière notification et on y navigue quand la fenêtre reprend le focus.
const FENETRE_CLIC_MS = 5 * 60_000;

type Options = {
  naviguer: (vue: ViewKey) => void;
  lancerVeille: () => void;
};

/**
 * Pont entre HERMES et le système (Tauri uniquement, inerte en mode web) :
 * notifications (nouvel AO pertinent, réponse prête, panne ARGOS), événements du
 * menu du tray et synchronisation du réglage « réduire à la fermeture ».
 */
export function useIntegrationBureau({ naviguer, lancerVeille }: Options) {
  const rappels = useRef({ naviguer, lancerVeille });
  rappels.current = { naviguer, lancerVeille };

  useEffect(() => {
    if (!estTauri()) return;
    let annule = false;
    let derniereNotif: { vue: ViewKey; le: number } | null = null;

    // Identifiants déjà signalés ; null tant que le premier sondage (amorçage
    // silencieux, pour ne pas notifier tout l'existant au démarrage) n'a pas eu lieu.
    let aoSignales: Set<number> | null = null;
    let reponsesSignalees: Set<number> | null = null;
    let dernierLogPanne: number | null = null;

    const signaler = async (
      type: Parameters<typeof notifierBureau>[0],
      titre: string,
      corps: string,
      vue: ViewKey,
    ) => {
      if (await notifierBureau(type, titre, corps)) derniereNotif = { vue, le: Date.now() };
    };

    const sonder = async () => {
      try {
        const [page, cfg] = await Promise.all([
          api.listerAO(),
          api.lireConfigOrchestration().catch(() => null),
        ]);
        const seuil = cfg?.seuil_score ?? 70;
        const pertinents = page.items.filter((a) => a.score !== null && a.score >= seuil);
        if (aoSignales === null) {
          aoSignales = new Set(pertinents.map((a) => a.id));
        } else {
          const nouveaux = pertinents.filter((a) => !aoSignales!.has(a.id));
          nouveaux.forEach((a) => aoSignales!.add(a.id));
          if (nouveaux.length > 0) {
            await signaler(
              "nouvel_ao",
              nouveaux.length === 1 ? "Nouvel appel d'offre pertinent" : "Nouveaux appels d'offre",
              nouveaux.length === 1
                ? `${nouveaux[0].titre} — score ${nouveaux[0].score}`
                : `${nouveaux.length} AO au-dessus du seuil KRINOS (${seuil}).`,
              "tenders",
            );
          }
        }
      } catch {
        // Backend injoignable : on réessaiera au prochain sondage.
      }

      try {
        const prets = (await api.listerReponsesHermion("en_attente"));
        if (reponsesSignalees === null) {
          reponsesSignalees = new Set(prets.map((r) => r.id));
        } else {
          const nouvelles = prets.filter((r) => !reponsesSignalees!.has(r.id));
          nouvelles.forEach((r) => reponsesSignalees!.add(r.id));
          if (nouvelles.length > 0) {
            await signaler(
              "reponse_prete",
              "Réponse HERMION à valider",
              nouvelles.length === 1
                ? `${nouvelles[0].appel_offre_titre} — v${nouvelles[0].version}`
                : `${nouvelles.length} réponses en attente de validation.`,
              "responses",
            );
          }
        }
      } catch {
        // idem
      }

      try {
        const pannes = (await api.listerLogs({ agent: "argos", niveau: "error", limit: 5 })).items;
        const plusRecent = pannes.reduce((m, l) => Math.max(m, l.id), 0);
        if (dernierLogPanne === null) {
          dernierLogPanne = plusRecent;
        } else if (plusRecent > dernierLogPanne) {
          const derniere = pannes.find((l) => l.id === plusRecent);
          dernierLogPanne = plusRecent;
          await signaler(
            "panne_argos",
            "ARGOS : panne de collecte",
            derniere?.message ?? "Une collecte a échoué.",
            "journal",
          );
        }
      } catch {
        // idem
      }
    };

    void sonder();
    const timer = window.setInterval(() => void sonder(), SONDAGE_MS);

    const auFocus = () => {
      if (derniereNotif && Date.now() - derniereNotif.le < FENETRE_CLIC_MS) {
        rappels.current.naviguer(derniereNotif.vue);
      }
      derniereNotif = null;
    };
    window.addEventListener("focus", auFocus);

    void synchroniserReductionTray(chargerPreferencesBureau().reduireDansTray);

    const desabonnements: (() => void)[] = [];
    void ecouterEvenementTray("hermes-tray-veille", () => rappels.current.lancerVeille()).then(
      (off) => (annule ? off() : desabonnements.push(off)),
    );
    void ecouterEvenementTray("hermes-tray-pause", () => {
      const prefs = chargerPreferencesBureau();
      enregistrerPreferencesBureau({ ...prefs, pause: !prefs.pause });
    }).then((off) => (annule ? off() : desabonnements.push(off)));

    return () => {
      annule = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", auFocus);
      desabonnements.forEach((off) => off());
    };
  }, []);
}

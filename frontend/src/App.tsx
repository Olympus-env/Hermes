import {
  AnimatePresence,
  MotionConfig,
  MotionGlobalConfig,
  motion,
  useReducedMotion,
} from "motion/react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { GreekFrieze } from "./components/GreekFrieze";
import { GreekKey } from "./components/GreekKey";
import { HermesMark } from "./components/HermesMark";
import { Icon } from "./components/Icon";
import { ModelDownloader } from "./components/ModelDownloader";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { DUREE_OUVERTURE_MS, Ouverture } from "./components/Ouverture";
import { Sidebar, type ViewKey } from "./components/Sidebar";
import { Toast } from "./components/Toast";
import { Topbar } from "./components/Topbar";
import { api } from "./lib/api";
import { COURBE, VARIANTES_ELEMENT, VARIANTES_LISTE, VARIANTES_VUE } from "./lib/motion";
import { installerComportementsNatifs } from "./lib/natif";
import { type AgentKey, type AgentState } from "./lib/data";
import type { ToastInput } from "./lib/toast";
import { useIntegrationBureau } from "./lib/useIntegrationBureau";
import {
  isOnboardingDone,
  loadUserProfile,
  saveUserProfile,
  type UserProfile,
} from "./lib/userProfile";
// Vues chargées à la demande : le squelette sert de repli pendant le chargement.
const Accueil = lazy(() => import("./views/Accueil").then((m) => ({ default: m.Accueil })));
const Journal = lazy(() => import("./views/Journal").then((m) => ({ default: m.Journal })));
const Responses = lazy(() => import("./views/Responses").then((m) => ({ default: m.Responses })));
const Settings = lazy(() => import("./views/Settings").then((m) => ({ default: m.Settings })));
const Tenders = lazy(() => import("./views/Tenders").then((m) => ({ default: m.Tenders })));

// L'animation d'ouverture n'est jouée qu'une fois par lancement de l'app.
let ouvertureDejaJouee = false;

/** « mm:ss » (ou « h:mm:ss ») avant l'échéance ; « — » si aucun cycle n'est programmé. */
function formaterCompteARebours(cibleMs: number | null, maintenantMs: number): string {
  if (cibleMs === null) return "—";
  const total = Math.max(0, Math.round((cibleMs - maintenantMs) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60)
    .toString()
    .padStart(2, "0");
  const s = (total % 60).toString().padStart(2, "0");
  return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
}

/**
 * `reducedMotion="user"` ne coupe que les transformations : les fondus d'opacité
 * subsistent. Sous `prefers-reduced-motion`, on coupe donc toutes les animations
 * Motion (les vues apparaissent d'un coup, sans fondu) ; réversible à chaud.
 */
const REDUIRE_MOUVEMENT = "(prefers-reduced-motion: reduce)";
function appliquerReducedMotion(reduit: boolean) {
  MotionGlobalConfig.skipAnimations = reduit;
}
if (typeof window !== "undefined" && window.matchMedia) {
  const mq = window.matchMedia(REDUIRE_MOUVEMENT);
  appliquerReducedMotion(mq.matches);
  mq.addEventListener("change", (e) => appliquerReducedMotion(e.matches));
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <Coque />
    </MotionConfig>
  );
}

function Coque() {
  const reduire = useReducedMotion();
  const [ouverture, setOuverture] = useState(!ouvertureDejaJouee && !reduire);
  const finOuverture = useCallback(() => {
    ouvertureDejaJouee = true;
    setOuverture(false);
  }, []);
  const [active, setActive] = useState<ViewKey>("tenders");
  const [toast, setToast] = useState<ToastInput | null>(null);
  const [emptyState, setEmptyState] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [modeleReady, setModeleReady] = useState(false);
  const [profile, setProfile] = useState<UserProfile | null>(() => loadUserProfile());
  const [onboardingDone, setOnboardingDone] = useState(() => isOnboardingDone());
  const [agents, setAgents] = useState<Record<AgentKey, AgentState>>({
    argos: "active",
    krinos: "active",
    hermion: "active",
  });
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [prochainCycleMs, setProchainCycleMs] = useState<number | null>(null);
  const [maintenant, setMaintenant] = useState(() => Date.now());
  const [tendersRefreshKey, setTendersRefreshKey] = useState(0);
  const [tenderCount, setTenderCount] = useState(0);
  const [responseCount, setResponseCount] = useState(0);
  const [pendingValidationCount, setPendingValidationCount] = useState(0);

  // Comportements natifs (menu contextuel, raccourcis…) et raccourcis d'app.
  useEffect(() => installerComportementsNatifs({ onNaviguer: setActive }), []);

  // Recharge périodique des compteurs sidebar (réponses HERMION)
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const data = await api.listerReponsesHermion();
        if (cancelled) return;
        setResponseCount(data.length);
        setPendingValidationCount(
          data.filter((r) => r.statut === "en_attente" || r.statut === "a_modifier").length,
        );
      } catch {
        // Pas critique — on garde les anciennes valeurs
      }
    };
    refresh();
    const id = setInterval(refresh, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Backend joignable ? Sonde /health (rapide tant qu'il démarre, lente ensuite)
  // pour afficher un bandeau global plutôt qu'une erreur dans chaque vue.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let etaitJoignable: boolean | null = null;
    const sonder = async () => {
      let ok = false;
      try {
        await api.health();
        ok = true;
      } catch {
        ok = false;
      }
      if (cancelled) return;
      setBackendUp(ok);
      // Retour du backend après une panne/un démarrage : les vues se rechargent.
      if (ok && etaitJoignable === false) setTendersRefreshKey((k) => k + 1);
      etaitJoignable = ok;
      timer = setTimeout(sonder, ok ? 30_000 : 2_000);
    };
    void sonder();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  // Prochain cycle ARGOS : vraie échéance APScheduler (`/argos/scheduler`).
  const rafraichirScheduler = useCallback(async () => {
    try {
      const etat = await api.etatSchedulerArgos();
      const echeances = etat.jobs
        .map((j) => (j.prochaine_execution ? Date.parse(j.prochaine_execution) : NaN))
        .filter((t) => !Number.isNaN(t));
      setProchainCycleMs(etat.en_marche && echeances.length ? Math.min(...echeances) : null);
    } catch {
      // Pas critique — on garde l'échéance précédente
    }
  }, []);

  useEffect(() => {
    void rafraichirScheduler();
    const id = setInterval(rafraichirScheduler, 30_000);
    return () => clearInterval(id);
  }, [rafraichirScheduler, backendUp]);

  useEffect(() => {
    const id = setInterval(() => setMaintenant(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const nextCycle = formaterCompteARebours(prochainCycleMs, maintenant);

  const triggerCycle = useCallback(async () => {
    setIsLoading(true);
    setAgents((a) => ({ ...a, argos: "running", krinos: "running" }));
    setToast({
      title: "ARGOS",
      app: "Cycle de collecte lancé",
      msg: "Collecte réelle des scrapers ARGOS enregistrés — résultats dans quelques instants.",
      agent: "argos",
    });
    try {
      const result = await api.collecterArgos(30);
      const pipeline = await api.lancerPipeline();
      setTendersRefreshKey((key) => key + 1);
      setIsLoading(false);
      setAgents((a) => ({ ...a, argos: "active", krinos: "active" }));
      void rafraichirScheduler();
      const filtres = result.ao_filtres
        ? ` · ${result.ao_filtres} filtrés (hors critères)`
        : "";
      const pipelineMsg = pipeline.actif
        ? ` · ${pipeline.ao_analyses} analysés · ${pipeline.ao_rediges} réponses générées`
        : " · pipeline autonome désactivé";
      const echecs = pipeline.ao_echecs ? ` · ${pipeline.ao_echecs} échecs pipeline` : "";
      setToast({
        title: "ARGOS",
        app: "Cycle terminé",
        msg: `${result.ao_nouveaux} nouveaux AO · ${result.ao_trouves} trouvés · ${result.ao_dedoublonnes} dédoublonnés${filtres}${pipelineMsg}${echecs}.`,
        agent: "argos",
      });
    } catch (error) {
      setIsLoading(false);
      setAgents((a) => ({ ...a, argos: "inactive", krinos: "active" }));
      setToast({
        title: "ARGOS",
        app: "Cycle en échec",
        msg: error instanceof Error ? error.message : "Erreur inconnue pendant la collecte.",
        agent: "argos",
      });
    }
  }, [rafraichirScheduler]);

  // Intégration système (Tauri) : notifications, menu du tray. Inerte en mode web.
  useIntegrationBureau({ naviguer: setActive, lancerVeille: triggerCycle });

  return (
    <div className="app">
      <AnimatePresence>{ouverture && <Ouverture onFin={finOuverture} />}</AnimatePresence>

      <div className="app__frieze">
        {/* La frise se révèle de gauche à droite (transform seulement) */}
        <motion.div
          className="app__frieze-inner"
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.7, delay: ouverture ? DUREE_OUVERTURE_MS / 1000 : 0, ease: [...COURBE.sortie] }}
        >
          <GreekFrieze height={20} color="#C8A951" opacity={0.55} strokeWidth={1.3} />
        </motion.div>
      </div>

      <Sidebar
        active={active}
        onChange={setActive}
        agents={agents}
        tenderCount={tenderCount}
        responseCount={responseCount}
        pendingValidationCount={pendingValidationCount}
      />
      {profile && (
        <Topbar
          active={active}
          agents={agents}
          nextCycle={nextCycle}
          profile={profile}
          isLoading={isLoading}
          onLaunchArgos={triggerCycle}
          onOpenJournal={() => setActive("journal")}
        />
      )}

      <main className="app__main">
        <AnimatePresence>
          {backendUp === false && (
            <motion.div
              className="loading-banner"
              role="status"
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
            >
              <span className="loading-banner__icon" />
              <span>
                <strong style={{ color: "var(--argos)", letterSpacing: "0.08em" }}>HERMES</strong>{" "}
                Le backend démarre ou est injoignable — nouvelle tentative en cours…
              </span>
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={emptyState ? "vide" : active}
            className="view-transition"
            variants={VARIANTES_VUE}
            initial="initial"
            animate="animate"
            exit="exit"
          >
            <Suspense fallback={<SqueletteVue />}>
              {emptyState ? (
                <EmptyView
                  onConfigure={() => {
                    setEmptyState(false);
                    setActive("settings");
                  }}
                  onStart={() => {
                    setEmptyState(false);
                    triggerCycle();
                  }}
                />
              ) : (
                <>
                  {active === "accueil" && (
                    <Accueil
                      onNavigate={setActive}
                      agents={agents}
                      isLoading={isLoading}
                      onTriggerCycle={triggerCycle}
                    />
                  )}
                  {active === "tenders" && (
                    <Tenders
                      isLoading={isLoading}
                      refreshKey={tendersRefreshKey}
                      onCountChange={setTenderCount}
                      onToast={setToast}
                    />
                  )}
                  {active === "responses" && (
                    <Responses onToast={setToast} externalRefreshKey={tendersRefreshKey} />
                  )}
                  {active === "journal" && <Journal refreshKey={tendersRefreshKey} />}
                  {active === "settings" && (
                    <Settings
                      profile={profile}
                      onSaveProfile={(nextProfile) => {
                        setProfile(saveUserProfile(nextProfile));
                        setToast({
                          title: "HERMION",
                          app: "Profil utilisateur",
                          msg: "Identité enregistrée. HERMION utilisera ces informations dans les réponses générées.",
                          agent: "hermion",
                        });
                      }}
                    />
                  )}
                </>
              )}
            </Suspense>
          </motion.div>
        </AnimatePresence>
      </main>

      <Toast toast={toast} onClose={() => setToast(null)} />

      <AnimatePresence>
      {(!profile || !onboardingDone) && modeleReady && (
        <OnboardingWizard
          onDone={(nextProfile) => {
            setProfile(nextProfile);
            setOnboardingDone(true);
            setToast({
              title: "HERMES",
              app: "Onboarding terminé",
              msg: `Bienvenue ${nextProfile.firstName}. Tu peux lancer ARGOS dès maintenant.`,
              agent: "argos",
            });
          }}
        />
      )}

      </AnimatePresence>

      {!modeleReady && <ModelDownloader onReady={() => setModeleReady(true)} />}
    </div>
  );
}

function EmptyView({
  onConfigure,
  onStart,
}: {
  onConfigure: () => void;
  onStart: () => void;
}) {
  return (
    <motion.div
      className="empty"
      variants={VARIANTES_LISTE}
      initial="initial"
      animate="animate"
    >
      <motion.div className="empty__art" variants={VARIANTES_ELEMENT}>
        <div className="empty__art-ring" />
        <div className="empty__art-ring empty__art-ring--inner" />
        <HermesMark size={56} color="#C8A951" />
      </motion.div>
      <motion.h2 className="empty__title" variants={VARIANTES_ELEMENT}>
        Aucun appel d'offre collecté
      </motion.h2>
      <motion.p className="empty__desc" variants={VARIANTES_ELEMENT}>
        HERMES est prêt. Configurez au moins un portail dans les paramètres puis lancez
        votre premier cycle ARGOS — les AO pertinents apparaîtront ici.
      </motion.p>
      <motion.div style={{ display: "flex", gap: 10 }} variants={VARIANTES_ELEMENT}>
        <button className="btn btn--gold" onClick={onStart}>
          <Icon.refresh size={13} /> Lancer un premier cycle ARGOS
        </button>
        <button className="btn btn--ghost" onClick={onConfigure}>
          <Icon.settings size={13} /> Configurer les portails
        </button>
      </motion.div>

      <motion.div style={{ marginTop: 36, opacity: 0.6 }} variants={VARIANTES_ELEMENT}>
        <GreekKey width={180} color="#C8A951" opacity={0.55} strokeWidth={1.4} />
      </motion.div>
    </motion.div>
  );
}

/** Squelette affiché pendant le chargement d'une vue (plutôt qu'un écran vide). */
function SqueletteVue() {
  return (
    <div className="squelette-vue" aria-busy="true" aria-label="Chargement">
      <span className="skel" style={{ width: 220, height: 16, marginBottom: 22 }} />
      {[0, 1, 2, 3].map((i) => (
        <div className="skeleton-card" key={i}>
          <span className="skel" style={{ width: `${70 - i * 8}%`, marginBottom: 10 }} />
          <span className="skel" style={{ width: "40%" }} />
        </div>
      ))}
    </div>
  );
}

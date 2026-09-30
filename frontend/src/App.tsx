import { useCallback, useEffect, useState } from "react";
import { GreekFrieze } from "./components/GreekFrieze";
import { GreekKey } from "./components/GreekKey";
import { HermesMark } from "./components/HermesMark";
import { Icon } from "./components/Icon";
import { ModelDownloader } from "./components/ModelDownloader";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { Sidebar, type ViewKey } from "./components/Sidebar";
import { Toast } from "./components/Toast";
import { Topbar } from "./components/Topbar";
import { api } from "./lib/api";
import { type AgentKey, type AgentState } from "./lib/data";
import type { ToastInput } from "./lib/toast";
import { useIntegrationBureau } from "./lib/useIntegrationBureau";
import {
  isOnboardingDone,
  loadUserProfile,
  saveUserProfile,
  type UserProfile,
} from "./lib/userProfile";
import { Accueil } from "./views/Accueil";
import { Journal } from "./views/Journal";
import { Responses } from "./views/Responses";
import { Settings } from "./views/Settings";
import { Tenders } from "./views/Tenders";

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

export default function App() {
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
      <div className="app__frieze">
        <GreekFrieze height={20} color="#C8A951" opacity={0.55} strokeWidth={1.3} />
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
        {backendUp === false && (
          <div className="loading-banner" role="status">
            <span className="loading-banner__icon" />
            <span>
              <strong style={{ color: "var(--argos)", letterSpacing: "0.08em" }}>HERMES</strong>{" "}
              Le backend démarre ou est injoignable — nouvelle tentative en cours…
            </span>
          </div>
        )}
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
            {active === "responses" && <Responses onToast={setToast} externalRefreshKey={tendersRefreshKey} />}
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
      </main>

      <Toast toast={toast} onClose={() => setToast(null)} />

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
    <div className="empty">
      <div className="empty__art">
        <div className="empty__art-ring" />
        <div className="empty__art-ring empty__art-ring--inner" />
        <HermesMark size={56} color="#C8A951" />
      </div>
      <h2 className="empty__title">Aucun appel d'offre collecté</h2>
      <p className="empty__desc">
        HERMES est prêt. Configurez au moins un portail dans les paramètres puis lancez
        votre premier cycle ARGOS — les AO pertinents apparaîtront ici.
      </p>
      <div style={{ display: "flex", gap: 10 }}>
        <button className="btn btn--gold" onClick={onStart}>
          <Icon.refresh size={13} /> Lancer un premier cycle ARGOS
        </button>
        <button className="btn btn--ghost" onClick={onConfigure}>
          <Icon.settings size={13} /> Configurer les portails
        </button>
      </div>

      <div style={{ marginTop: 36, opacity: 0.6 }}>
        <GreekKey width={180} color="#C8A951" opacity={0.55} strokeWidth={1.4} />
      </div>
    </div>
  );
}

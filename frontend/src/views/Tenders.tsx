import { useEffect, useMemo, useState } from "react";
import {
  api,
  type AnalyseKrinos,
  type AppelOffre,
  type PonderationKrinos,
  type ProgressionHermion,
} from "../lib/api";
import { deadlineInfo, type Tender, type TenderTag } from "../lib/data";
import { AgentChip } from "../components/AgentChip";
import { Deadline } from "../components/Deadline";
import { Icon } from "../components/Icon";
import { Score } from "../components/Score";
import { Tag } from "../components/Tag";
import type { ToastInput } from "../lib/toast";
import { loadUserProfile } from "../lib/userProfile";

type Props = {
  isLoading: boolean;
  refreshKey: number;
  onCountChange: (count: number) => void;
  onToast: (t: ToastInput) => void;
};

export function Tenders({ isLoading, refreshKey, onCountChange, onToast }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [portal, setPortal] = useState("all");
  const [tag, setTag] = useState("all");
  const [tenders, setTenders] = useState<Tender[]>([]);
  const [apiLoading, setApiLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const loadTenders = async () => {
    setApiLoading(true);
    setApiError(null);
    try {
      const page = await api.listerAO();
      setTenders(page.items.map(mapAppelOffre));
      onCountChange(page.total);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Erreur inconnue");
      setTenders([]);
      onCountChange(0);
    } finally {
      setApiLoading(false);
    }
  };

  useEffect(() => {
    void loadTenders();
  }, [refreshKey]);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    tenders.forEach((t) => t.tags.forEach((tg) => set.add(tg.label)));
    return ["all", ...Array.from(set)];
  }, [tenders]);

  const allPortals = useMemo(() => {
    const set = new Set(tenders.map((t) => t.portal));
    return ["all", ...Array.from(set)];
  }, [tenders]);

  const filtered = tenders.filter((t) => {
    if (
      search &&
      !t.title.toLowerCase().includes(search.toLowerCase()) &&
      !t.issuer.toLowerCase().includes(search.toLowerCase())
    )
      return false;
    if (t.score < minScore) return false;
    if (portal !== "all" && t.portal !== portal) return false;
    if (tag !== "all" && !t.tags.some((tg) => tg.label === tag)) return false;
    return true;
  });

  const urgentCount = filtered.filter((t) => deadlineInfo(t.deadline).urgent).length;
  const selected = filtered.find((t) => t.id === selectedId);
  const loading = isLoading || apiLoading;

  return (
    <div className="view">
      {loading && (
        <div className="loading-banner">
          <span className="loading-banner__icon" />
          <span>
            <strong style={{ color: "var(--argos)", letterSpacing: "0.08em" }}>ARGOS</strong>{" "}
            collecte de nouveaux appels d'offre…
          </span>
          <div className="loading-banner__bar" />
          <span style={{ color: "var(--fg-3)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
            scrapers ARGOS
          </span>
        </div>
      )}

      <div className="filters">
        <div className="filter-input">
          <Icon.search />
          <input
            type="text"
            placeholder="Rechercher un appel d'offre, un émetteur…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          className="filter-select"
          value={portal}
          onChange={(e) => setPortal(e.target.value)}
        >
          {allPortals.map((p) => (
            <option key={p} value={p}>
              {p === "all" ? "Tous les portails" : p}
            </option>
          ))}
        </select>
        <select
          className="filter-select"
          value={tag}
          onChange={(e) => setTag(e.target.value)}
        >
          {allTags.map((t) => (
            <option key={t} value={t}>
              {t === "all" ? "Tous les tags" : t}
            </option>
          ))}
        </select>
        <div className="filter-slider">
          <span>Score min.</span>
          <input
            type="range"
            min="0"
            max="100"
            step="5"
            value={minScore}
            onChange={(e) => setMinScore(+e.target.value)}
          />
          <strong>{minScore}</strong>
        </div>
        <div style={{ flex: 1 }} />
        <button className="btn btn--ghost btn--sm" onClick={() => void loadTenders()}>
          <Icon.refresh size={11} /> Rafraîchir
        </button>
      </div>

      <div className={`tender-layout${selected ? "" : " tender-layout--no-panel"}`}>
        <div className="tender-list">
          <div className="tender-list__count">
            <strong>{filtered.length}</strong> appel{filtered.length > 1 ? "s" : ""} d'offre —{" "}
            {urgentCount} urgent{urgentCount > 1 ? "s" : ""}
          </div>

          {apiError && (
            <div className="loading-banner loading-banner--error">
              <Icon.warning size={13} />
              <span>
                Backend indisponible : {apiError}. Vérifiez que le launcher HERMES a bien
                démarré l'API locale.
              </span>
            </div>
          )}

          {loading &&
            [0, 1, 2].map((i) => (
              <div className="skeleton-card" key={"sk" + i}>
                <span className="skel" style={{ width: "30%" }} />
                <span
                  className="skel"
                  style={{ width: "70%", height: 14, marginTop: 10 }}
                />
                <span className="skel" style={{ width: "40%", marginTop: 10 }} />
              </div>
            ))}

          {filtered.map((t) => {
            const isSel = t.id === selectedId;
            return (
              <article
                key={t.id}
                className={`tender-card${isSel ? " tender-card--selected" : ""}`}
                onClick={() => setSelectedId(isSel ? null : t.id)}
              >
                <div>
                  <div className="tender-card__top">
                    <span className="tender-card__issuer">{t.issuer}</span>
                    <span>·</span>
                    <span className="tender-card__portal">{t.portal}</span>
                    <span>·</span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5 }}>
                      {t.reference}
                    </span>
                  </div>
                  <h3 className="tender-card__title">{t.title}</h3>
                  <div
                    className="tender-card__tags"
                    style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}
                  >
                    {t.tags.map((tg) => (
                      <Tag key={tg.label} label={tg.label} tone={tg.tone} />
                    ))}
                    <DocumentsBadge tender={t} />
                  </div>
                </div>
                <div className="tender-card__right">
                  {t.analyzed ? <Score value={t.score} /> : <NonAnalyse />}
                  <Deadline date={t.deadline} />
                </div>
              </article>
            );
          })}

          {!loading && filtered.length === 0 && (
            <div style={{ padding: "60px 20px", textAlign: "center", color: "var(--fg-3)" }}>
              <p>
                {apiError
                  ? "Aucun appel d'offre chargé depuis MNEMOSYNE."
                  : "Aucun appel d'offre ne correspond aux filtres."}
              </p>
              <button
                className="btn btn--ghost btn--sm"
                onClick={() => {
                  setSearch("");
                  setMinScore(0);
                  setPortal("all");
                  setTag("all");
                }}
              >
                Réinitialiser les filtres
              </button>
            </div>
          )}
        </div>

        {selected && (
          <TenderPanel
            key={selected.id}
            tender={selected}
            onClose={() => setSelectedId(null)}
            onChanged={() => {
              setSelectedId(null);
              void loadTenders();
            }}
            onToast={onToast}
          />
        )}
      </div>
    </div>
  );
}

function mapAppelOffre(ao: AppelOffre): Tender {
  const tags: TenderTag[] = [];
  if (ao.type_marche) tags.push({ label: ao.type_marche, tone: "gold" });
  if (ao.zone_geographique) tags.push({ label: ao.zone_geographique, tone: "green" });
  if (ao.code_naf) tags.push({ label: ao.code_naf, tone: "violet" });
  if (tags.length === 0) tags.push({ label: statutLabel(ao.statut), tone: "coral" });

  return {
    id: String(ao.id),
    title: ao.titre,
    issuer: ao.emetteur ?? "Émetteur non renseigné",
    portal:
      ao.portail_nom?.toUpperCase() ??
      (ao.portail_id ? `Portail #${ao.portail_id}` : "Source directe"),
    deadline: ao.date_limite ?? ao.cree_le,
    budget: formatBudget(ao.budget_estime, ao.devise),
    reference: ao.reference_externe ?? `AO-${ao.id}`,
    score: ao.score ?? 0,
    analyzed: ao.analyse_disponible,
    tags,
    summary:
      ao.objet ??
      "AO collecté par ARGOS. L'analyse KRINOS n'a pas encore produit de résumé détaillé.",
    keypoints: [
      `Statut MNEMOSYNE : ${statutLabel(ao.statut)}`,
      ao.date_publication ? `Publication : ${formatDate(ao.date_publication)}` : "Publication non renseignée",
      ao.url_source ? `Source : ${ao.url_source}` : "URL source non renseignée",
      `Documents : ${ao.documents_telecharges}/${ao.documents_detectes} téléchargé(s)`,
    ],
    status: statutLabel(ao.statut),
    documentsDetectes: ao.documents_detectes,
    documentsTelecharges: ao.documents_telecharges,
  };
}

/** Badge synthétique de l'état documents d'un AO (détectés / téléchargés). */
function DocumentsBadge({ tender }: { tender: Tender }) {
  const detectes = tender.documentsDetectes ?? 0;
  const telecharges = tender.documentsTelecharges ?? 0;
  if (detectes === 0) return null;
  const complet = telecharges >= detectes;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 10.5,
        fontFamily: "var(--font-mono)",
        color: complet ? "var(--argos)" : "var(--fg-3)",
        border: `1px solid ${complet ? "rgba(29,158,117,0.35)" : "var(--line)"}`,
        borderRadius: 4,
        padding: "2px 6px",
        whiteSpace: "nowrap",
      }}
      title={
        complet
          ? "Tous les documents détectés sont téléchargés en local"
          : "Des documents détectés ne sont pas encore téléchargés"
      }
    >
      <Icon.document size={11} />
      {telecharges}/{detectes}
    </span>
  );
}

function formatBudget(value: number | null, devise: string): string {
  if (value === null) return "Budget non renseigné";
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: devise || "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function statutLabel(statut: string): string {
  const labels: Record<string, string> = {
    brut: "Brut",
    analyse: "En analyse",
    a_repondre: "À répondre",
    en_redaction: "En rédaction",
    repondu: "Répondu",
    rejete: "Rejeté",
    expire: "Expiré",
    hors_filtre: "Hors filtre",
  };
  return labels[statut] ?? statut;
}

/** Pastille « non analysé » — distingue l'absence de score d'un score réel de 0. */
function NonAnalyse() {
  return (
    <span
      style={{
        fontSize: 11,
        color: "var(--fg-3)",
        border: "1px solid var(--line)",
        borderRadius: 6,
        padding: "3px 8px",
        whiteSpace: "nowrap",
      }}
      title="KRINOS n'a pas encore analysé cet AO"
    >
      Non analysé
    </span>
  );
}

type PanelProps = {
  tender: Tender;
  onClose: () => void;
  onChanged: () => void;
  onToast: (t: ToastInput) => void;
};

function TenderPanel({ tender, onClose, onChanged, onToast }: PanelProps) {
  const { formatted, urgent, days } = deadlineInfo(tender.deadline);
  const [redigerEnCours, setRedigerEnCours] = useState(false);
  const [progression, setProgression] = useState<ProgressionHermion | null>(null);
  const [analyse, setAnalyse] = useState<AnalyseKrinos | null>(null);
  const [ponderation, setPonderation] = useState<PonderationKrinos | null>(null);
  const [analyseLoading, setAnalyseLoading] = useState(true);
  const [recalculEnCours, setRecalculEnCours] = useState(false);
  const [relanceEnCours, setRelanceEnCours] = useState(false);
  const [dceEnCours, setDceEnCours] = useState(false);
  const aAnalyse = analyse !== null || tender.analyzed === true;
  const aDimensions = !!analyse && Object.keys(analyse.scores_dimensions).length > 0;
  const scoreAffiche = analyse?.score ?? tender.score;

  useEffect(() => {
    let cancelled = false;
    setAnalyseLoading(true);
    Promise.all([
      api.lireAnalyseKrinos(Number(tender.id)).catch(() => null),
      api.lirePonderation().catch(() => null),
    ])
      .then(([analyseData, ponderationData]) => {
        if (cancelled) return;
        setAnalyse(analyseData);
        setPonderation(ponderationData);
      })
      .finally(() => {
        if (!cancelled) setAnalyseLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tender.id]);

  const rediger = async () => {
    setRedigerEnCours(true);
    setProgression(null);
    onToast({
      title: "HERMION",
      app: "Rédaction lancée",
      msg: "PYTHIA prépare la réponse — comptez 30 à 90 s selon la longueur du dossier.",
      agent: "hermion",
    });
    const aoId = Number(tender.id);
    // Polling de l'avancement pendant la génération (issue #7).
    const poll = window.setInterval(() => {
      api
        .progressionHermion(aoId)
        .then((p) => {
          if (p.connue) setProgression(p);
        })
        .catch(() => {
          /* transitoire : on retentera au prochain tick */
        });
    }, 1200);
    try {
      const profile = loadUserProfile();
      const result = await api.rediger(aoId, {
        profil: profile
          ? {
              prenom: profile.firstName,
              nom: profile.lastName,
              email: profile.email,
              entreprise: profile.entreprise,
              activite: [profile.activite, profile.infosUtiles].filter(Boolean).join("\n"),
            }
          : undefined,
      });
      onChanged();
      onToast({
        title: "HERMION",
        app: `Réponse v${result.reponse.version} générée`,
        msg: `${result.reponse.longueur_mots ?? "?"} mots — disponible dans l'onglet « Réponses ».`,
        agent: "hermion",
      });
    } catch (error) {
      onToast({
        title: "HERMION",
        app: "Rédaction en échec",
        msg: error instanceof Error ? error.message : "Erreur inconnue.",
        agent: "hermion",
      });
    } finally {
      window.clearInterval(poll);
      setRedigerEnCours(false);
      setProgression(null);
    }
  };

  const updateStatus = async (status: "a_repondre" | "rejete") => {
    try {
      await api.modifierStatutAO(Number(tender.id), status);
      onToast({
        title: status === "a_repondre" ? "HERMION" : "ARGOS",
        app: status === "a_repondre" ? "AO marqué à répondre" : "Appel d'offre exclu",
        msg:
          status === "a_repondre"
            ? "Le statut a été enregistré dans MNEMOSYNE. HERMION pourra préparer un brouillon."
            : "Le statut rejeté a été enregistré dans MNEMOSYNE.",
        agent: status === "a_repondre" ? "hermion" : "argos",
      });
      onChanged();
    } catch (error) {
      onToast({
        title: "HERMES",
        app: "Action impossible",
        msg: error instanceof Error ? error.message : "Erreur inconnue pendant la mise à jour.",
        agent: "krinos",
      });
    }
  };

  const recalculerScore = async () => {
    setRecalculEnCours(true);
    try {
      const next = await api.recalculerScoreKrinos(Number(tender.id));
      setAnalyse(next);
      onToast({
        title: "KRINOS",
        app: "Score recalculé",
        msg: `Nouveau score pondéré : ${Math.round(next.score)}/100.`,
        agent: "krinos",
      });
    } catch (error) {
      onToast({
        title: "KRINOS",
        app: "Recalcul impossible",
        msg: error instanceof Error ? error.message : "Erreur inconnue pendant le recalcul.",
        agent: "krinos",
      });
    } finally {
      setRecalculEnCours(false);
    }
  };

  // Relance une analyse KRINOS complète (PYTHIA) : produit résumé, ventilation
  // par dimension et score. À utiliser quand aucune analyse n'existe encore.
  const relancerAnalyse = async () => {
    setRelanceEnCours(true);
    onToast({
      title: "KRINOS",
      app: "Analyse lancée",
      msg: "PYTHIA analyse l'AO — résumé, ventilation et score à venir.",
      agent: "krinos",
    });
    try {
      const { analyse: next } = await api.analyserKrinos(Number(tender.id), true);
      setAnalyse(next);
      onToast({
        title: "KRINOS",
        app: "Analyse terminée",
        msg: `Score : ${Math.round(next.score)}/100.`,
        agent: "krinos",
      });
    } catch (error) {
      onToast({
        title: "KRINOS",
        app: "Analyse impossible",
        msg: error instanceof Error ? error.message : "PYTHIA est-il démarré ?",
        agent: "krinos",
      });
    } finally {
      setRelanceEnCours(false);
    }
  };

  // Télécharge en local les documents publics détectés (TED HTML/PDF/XML,
  // sinon url_source). Best-effort côté backend ; on remonte le bilan.
  const telechargerDce = async () => {
    setDceEnCours(true);
    onToast({
      title: "KRINOS",
      app: "Téléchargement des documents",
      msg: "Récupération des avis/documents publics détectés…",
      agent: "krinos",
    });
    try {
      const res = await api.telechargerDocumentsAO(Number(tender.id));
      onToast({
        title: "KRINOS",
        app: "Documents téléchargés",
        msg:
          res.documents.length === 0
            ? "Aucun document public exploitable pour cet AO."
            : `${res.documents.length} document(s) en local (${res.nouveaux} nouveau(x)).`,
        agent: "krinos",
      });
      onChanged();
    } catch (error) {
      onToast({
        title: "KRINOS",
        app: "Téléchargement impossible",
        msg: error instanceof Error ? error.message : "Erreur inconnue.",
        agent: "krinos",
      });
    } finally {
      setDceEnCours(false);
    }
  };

  return (
    <aside className="tender-panel">
      <div className="tender-panel__head">
        <button className="tender-panel__close" onClick={onClose} title="Fermer">
          <Icon.close />
        </button>
        <div className="tender-panel__eyebrow">
          <span style={{ fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>
            {tender.reference}
          </span>
          <span style={{ color: "var(--fg-4)", margin: "0 8px" }}>·</span>
          {tender.portal}
        </div>
        <h2 className="tender-panel__title">{tender.title}</h2>
        <div className="tender-panel__meta">
          {aAnalyse ? <Score value={Math.round(scoreAffiche)} /> : <NonAnalyse />}
          <span style={{ color: "var(--fg-4)" }}>·</span>
          <Deadline date={tender.deadline} />
          <span style={{ color: "var(--fg-4)" }}>·</span>
          <span>{tender.issuer}</span>
        </div>
      </div>

      <div className="tender-panel__body">
        <div className="tender-panel__section">
          <div className="tender-panel__section-title">
            <AgentChip agent="krinos" state="active" compact /> Résumé d'analyse
          </div>
          <p className="tender-panel__summary">{analyse?.resume ?? tender.summary}</p>
        </div>

        <div className="tender-panel__section">
          <div className="tender-panel__section-title">Informations clés</div>
          <dl className="kv">
            <dt>Émetteur</dt>
            <dd>{tender.issuer}</dd>
            <dt>Référence</dt>
            <dd style={{ fontFamily: "var(--font-mono)" }}>{tender.reference}</dd>
            <dt>Budget</dt>
            <dd>{tender.budget}</dd>
            <dt>Portail</dt>
            <dd>{tender.portal}</dd>
            <dt>Date limite</dt>
            <dd>
              {formatted}
              {urgent && (
                <span style={{ color: "var(--hermion)", marginLeft: 8 }}>J−{days}</span>
              )}
            </dd>
          </dl>
        </div>

        <div className="tender-panel__section">
          <div className="tender-panel__section-title">Points d'attention</div>
          <ul className="keypoints">
            {tender.keypoints.map((k, i) => (
              <li key={i}>{k}</li>
            ))}
          </ul>
        </div>

        <div className="tender-panel__section">
          <div className="tender-panel__section-title">Pondération du score</div>
          <ScoreBreakdown
            loading={analyseLoading}
            scores={analyse?.scores_dimensions ?? null}
            ponderation={ponderation}
          />
        </div>
      </div>

      {redigerEnCours && (
        <div
          style={{
            margin: "0 20px 8px",
            padding: "10px 14px",
            background: "rgba(216,90,48,0.10)",
            border: "1px solid rgba(216,90,48,0.30)",
            borderRadius: 6,
            fontSize: 12,
            color: "var(--fg-2)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span className="loading-banner__icon" />
          <span style={{ flex: 1 }}>
            <strong style={{ color: "var(--hermion)", letterSpacing: "0.04em" }}>
              HERMION
            </strong>{" "}
            {progression
              ? progression.libelle +
                (progression.etape === "redaction" && progression.total
                  ? ` — section ${progression.index}/${progression.total}`
                  : "") +
                (progression.message ? ` · ${progression.message}` : "")
              : "Initialisation…"}
          </span>
          {progression && (
            <span
              style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-3)" }}
            >
              {Math.round(progression.secondes_ecoulees)}s
            </span>
          )}
        </div>
      )}

      <div className="tender-panel__actions">
        <button
          className="btn btn--gold"
          onClick={() => void updateStatus("a_repondre")}
        >
          <Icon.check size={13} /> Marquer à répondre
        </button>
        <button
          className="btn btn--ghost"
          onClick={() => void updateStatus("rejete")}
        >
          <Icon.close size={13} /> Exclure
        </button>
        <button
          className="btn"
          onClick={() => void rediger()}
          disabled={redigerEnCours}
          title="Lance HERMION pour rédiger une réponse à cet AO (statut a_repondre requis)"
        >
          <Icon.refresh size={13} />
          {redigerEnCours ? "Rédaction…" : "Rédiger une réponse"}
        </button>
        {aDimensions ? (
          <button
            className="btn"
            onClick={() => void recalculerScore()}
            disabled={recalculEnCours}
            title="Recalcule le score avec la pondération KRINOS actuelle, sans relancer PYTHIA"
          >
            <Icon.refresh size={13} />
            {recalculEnCours ? "Recalcul…" : "Recalculer score"}
          </button>
        ) : (
          <button
            className="btn"
            onClick={() => void relancerAnalyse()}
            disabled={relanceEnCours || analyseLoading}
            title="Lance une analyse KRINOS complète (PYTHIA) : résumé, ventilation et score"
          >
            <Icon.refresh size={13} />
            {relanceEnCours ? "Analyse…" : "Lancer l'analyse"}
          </button>
        )}
        <button
          className="btn"
          onClick={() => void telechargerDce()}
          disabled={dceEnCours}
          title="Télécharge en local les documents/avis publics détectés (best-effort)"
        >
          <Icon.download size={13} />
          {dceEnCours ? "Téléchargement…" : "Télécharger DCE"}
        </button>
      </div>
    </aside>
  );
}

type DimensionScore = keyof Omit<PonderationKrinos, "total">;

const SCORE_DIMENSIONS: { id: DimensionScore; label: string }[] = [
  { id: "affinite_metier", label: "Affinité métier" },
  { id: "references", label: "Références" },
  { id: "adequation_budget", label: "Adéquation budget" },
  { id: "capacite_equipe", label: "Capacité équipe" },
  { id: "calendrier", label: "Risque calendrier" },
];

function ScoreBreakdown({
  loading,
  scores,
  ponderation,
}: {
  loading: boolean;
  scores: AnalyseKrinos["scores_dimensions"] | null;
  ponderation: PonderationKrinos | null;
}) {
  if (loading) {
    return <div style={{ color: "var(--fg-3)", fontSize: 12 }}>Chargement KRINOS…</div>;
  }
  if (!scores || Object.keys(scores).length === 0) {
    return (
      <div style={{ color: "var(--fg-3)", fontSize: 12, lineHeight: 1.5 }}>
        Aucune ventilation disponible. Utilise le bouton « Lancer l'analyse » ci-dessous
        pour que KRINOS produise les scores par dimension.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {SCORE_DIMENSIONS.map((d) => {
        const value = scores[d.id];
        const weight = ponderation ? ponderation[d.id] : null;
        const ratio = (value ?? 0) / 100;
        const color =
          ratio > 0.7 ? "var(--argos)" : ratio > 0.4 ? "var(--warn)" : "var(--err)";
        return (
          <div
            key={d.label}
            style={{
              display: "grid",
              gridTemplateColumns: "140px 1fr 64px",
              alignItems: "center",
              gap: 12,
              fontSize: 12,
            }}
          >
            <span style={{ color: "var(--fg-3)" }}>{d.label}</span>
            <div
              style={{
                height: 6,
                background: "var(--bg-2)",
                borderRadius: 3,
                overflow: "hidden",
                border: "1px solid var(--line)",
              }}
            >
              <div
                style={{
                  width: `${ratio * 100}%`,
                  height: "100%",
                  background: color,
                }}
              />
            </div>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                textAlign: "right",
                color: "var(--fg-2)",
              }}
            >
              {value === undefined ? "—" : `${Math.round(value)}`}
              {weight !== null ? ` · ${weight}%` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

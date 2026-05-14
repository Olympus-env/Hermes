import { useEffect, useMemo, useState } from "react";
import { api, type AppelOffre } from "../lib/api";
import { deadlineInfo, type Tender, type TenderTag } from "../lib/data";
import { AgentChip } from "../components/AgentChip";
import { Deadline } from "../components/Deadline";
import { Icon } from "../components/Icon";
import { Score } from "../components/Score";
import { Tag } from "../components/Tag";
import type { ToastInput } from "../lib/toast";

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
            3 / 4 portails
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
                  <div className="tender-card__tags">
                    {t.tags.map((tg) => (
                      <Tag key={tg.label} label={tg.label} tone={tg.tone} />
                    ))}
                  </div>
                </div>
                <div className="tender-card__right">
                  <Score value={t.score} />
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
    portal: ao.portail_id ? `Portail #${ao.portail_id}` : "Source directe",
    deadline: ao.date_limite ?? ao.cree_le,
    budget: formatBudget(ao.budget_estime, ao.devise),
    reference: ao.reference_externe ?? `AO-${ao.id}`,
    score: defaultScore(ao.statut),
    tags,
    summary:
      ao.objet ??
      "AO collecté par ARGOS. L'analyse KRINOS n'a pas encore produit de résumé détaillé.",
    keypoints: [
      `Statut MNEMOSYNE : ${statutLabel(ao.statut)}`,
      ao.date_publication ? `Publication : ${formatDate(ao.date_publication)}` : "Publication non renseignée",
      ao.url_source ? `Source : ${ao.url_source}` : "URL source non renseignée",
    ],
    status: statutLabel(ao.statut),
  };
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

function defaultScore(statut: string): number {
  if (statut === "a_repondre" || statut === "en_redaction") return 75;
  if (statut === "rejete" || statut === "expire") return 20;
  if (statut === "analyse") return 50;
  return 0;
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
  };
  return labels[statut] ?? statut;
}

type PanelProps = {
  tender: Tender;
  onClose: () => void;
  onToast: (t: ToastInput) => void;
};

function TenderPanel({ tender, onClose, onToast }: PanelProps) {
  const { formatted, urgent, days } = deadlineInfo(tender.deadline);

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
          <Score value={tender.score} />
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
          <p className="tender-panel__summary">{tender.summary}</p>
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
          <ScoreBreakdown total={tender.score} />
        </div>
      </div>

      <div className="tender-panel__actions">
        <button
          className="btn btn--gold"
          onClick={() =>
            onToast({
              title: "HERMION",
              app: "Réponse en cours de génération",
              msg: `Brouillon en préparation pour « ${tender.title.slice(0, 56)}${
                tender.title.length > 56 ? "…" : ""
              } »`,
              agent: "hermion",
            })
          }
        >
          <Icon.check size={13} /> Marquer à répondre
        </button>
        <button
          className="btn btn--ghost"
          onClick={() =>
            onToast({
              title: "ARGOS",
              app: "Appel d'offre exclu",
              msg: "Cet AO ne sera plus proposé dans les prochains cycles.",
              agent: "argos",
            })
          }
        >
          <Icon.close size={13} /> Exclure
        </button>
        <button className="btn">
          <Icon.download size={13} /> Télécharger DCE
        </button>
        <button className="btn">
          <Icon.mail size={13} /> Envoyer par mail
        </button>
      </div>
    </aside>
  );
}

function ScoreBreakdown({ total }: { total: number }) {
  const dims = [
    { label: "Affinité métier",   value: Math.min(25, Math.round(total * 0.3)),  max: 25 },
    { label: "Références",        value: Math.min(20, Math.round(total * 0.24)), max: 20 },
    { label: "Adéquation budget", value: Math.min(20, Math.round(total * 0.22)), max: 20 },
    { label: "Capacité équipe",   value: Math.min(15, Math.round(total * 0.16)), max: 15 },
    { label: "Risque calendrier", value: Math.min(20, Math.round(total * 0.2)),  max: 20 },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {dims.map((d) => {
        const ratio = d.value / d.max;
        const color =
          ratio > 0.7 ? "var(--argos)" : ratio > 0.4 ? "var(--warn)" : "var(--err)";
        return (
          <div
            key={d.label}
            style={{
              display: "grid",
              gridTemplateColumns: "140px 1fr 36px",
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
              {d.value}/{d.max}
            </span>
          </div>
        );
      })}
    </div>
  );
}

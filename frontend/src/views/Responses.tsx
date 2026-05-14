import { useCallback, useEffect, useMemo, useState } from "react";
import { AgentChip } from "../components/AgentChip";
import { Icon } from "../components/Icon";
import { Score } from "../components/Score";
import { StatusPill } from "../components/StatusPill";
import {
  api,
  type ReponseAvecAO,
  type ReponseHermion,
  type StatutReponseHermion,
} from "../lib/api";
import { type ResponseStatus } from "../lib/data";
import type { ToastInput } from "../lib/toast";
import { loadUserProfile } from "../lib/userProfile";

type Props = { onToast: (t: ToastInput) => void };

const STATUS_FILTERS: { id: StatutReponseHermion | "all"; label: string }[] = [
  { id: "all",          label: "Toutes" },
  { id: "en_attente",   label: "En attente" },
  { id: "a_modifier",   label: "À modifier" },
  { id: "validee",      label: "Validées" },
  { id: "rejetee",      label: "Rejetées" },
  { id: "exportee",     label: "Exportées" },
];

/** Mapping du statut backend vers le code utilisé par StatusPill (data.ts). */
function toUiStatus(s: StatutReponseHermion): ResponseStatus {
  if (s === "en_generation" || s === "en_attente") return "en-attente";
  if (s === "a_modifier") return "a-modifier";
  if (s === "validee") return "validee";
  if (s === "rejetee") return "rejetee";
  return "exportee";
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatDuree(ms: number | null): string {
  if (!ms || ms <= 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function Responses({ onToast }: Props) {
  const [filter, setFilter] = useState<StatutReponseHermion | "all">("all");
  const [reponses, setReponses] = useState<ReponseAvecAO[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ReponseHermion | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // Charge la liste
  useEffect(() => {
    let cancelled = false;
    setLoadingList(true);
    api
      .listerReponsesHermion()
      .then((data) => {
        if (cancelled) return;
        setReponses(data);
        if (data.length > 0 && selectedId === null) {
          setSelectedId(data[0].id);
        }
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  // Charge le détail de la réponse sélectionnée
  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    api
      .lireReponseHermion(selectedId)
      .then((r) => {
        if (!cancelled) setDetail(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const filtered = useMemo(
    () => (filter === "all" ? reponses : reponses.filter((r) => r.statut === filter)),
    [reponses, filter],
  );

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  const selectedSummary = reponses.find((r) => r.id === selectedId);

  const onStatusChange = async (
    next: StatutReponseHermion,
    commentaire?: string,
    toast?: ToastInput,
  ) => {
    if (selectedId === null) return;
    try {
      const updated = await api.modifierStatutReponse(selectedId, next, commentaire);
      setDetail(updated);
      // Synchronise la liste localement
      setReponses((rs) =>
        rs.map((r) => (r.id === selectedId ? { ...r, statut: updated.statut } : r)),
      );
      if (toast) onToast(toast);
    } catch (e) {
      onToast({
        title: "HERMION",
        app: "Erreur",
        msg: e instanceof Error ? e.message : String(e),
        agent: "hermion",
      });
    }
  };

  const onSaveContent = async (contenu: string, commentaire?: string) => {
    if (selectedId === null) return;
    try {
      const updated = await api.modifierContenuReponse(selectedId, contenu, commentaire);
      setDetail(updated);
      setReponses((rs) =>
        rs.map((r) =>
          r.id === selectedId
            ? {
                ...r,
                statut: updated.statut,
                longueur_mots: updated.longueur_mots,
              }
            : r,
        ),
      );
      onToast({
        title: "HERMION",
        app: "Réponse mise à jour",
        msg: "Contenu enregistré, statut passé à « à modifier ».",
        agent: "hermion",
      });
    } catch (e) {
      onToast({
        title: "HERMION",
        app: "Erreur de sauvegarde",
        msg: e instanceof Error ? e.message : String(e),
        agent: "hermion",
      });
    }
  };

  return (
    <div className="view">
      <div className="filters">
        {STATUS_FILTERS.map((s) => {
          const count =
            s.id === "all" ? reponses.length : reponses.filter((r) => r.statut === s.id).length;
          const active = filter === s.id;
          return (
            <button
              key={s.id}
              className={`btn ${active ? "btn--gold" : "btn--ghost"} btn--sm`}
              onClick={() => setFilter(s.id)}
            >
              {s.label}
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10.5,
                  opacity: 0.65,
                  marginLeft: 4,
                }}
              >
                {count}
              </span>
            </button>
          );
        })}
        <div style={{ flex: 1 }} />
        <button className="btn btn--ghost btn--sm" onClick={reload} disabled={loadingList}>
          <Icon.refresh size={11} /> {loadingList ? "Chargement…" : "Rafraîchir"}
        </button>
      </div>

      {error && (
        <div
          style={{
            margin: "12px 0",
            padding: "10px 14px",
            background: "rgba(220,80,80,0.10)",
            border: "1px solid rgba(220,80,80,0.30)",
            borderRadius: 6,
            fontSize: 12.5,
            color: "var(--fg-2)",
          }}
        >
          Erreur : {error}
        </div>
      )}

      <div className="responses-layout">
        <div className="responses-list">
          {loadingList && reponses.length === 0 ? (
            <div style={{ padding: 30, textAlign: "center", color: "var(--fg-3)", fontSize: 12.5 }}>
              Chargement des réponses…
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: 30, textAlign: "center", color: "var(--fg-3)", fontSize: 12.5 }}>
              {reponses.length === 0
                ? "Aucune réponse HERMION rédigée pour l'instant. Va dans l'onglet Veille, choisis un AO à répondre, puis lance la rédaction."
                : "Aucune réponse dans ce statut."}
            </div>
          ) : (
            filtered.map((r) => {
              const uiStatus = toUiStatus(r.statut);
              const isSel = r.id === selectedId;
              return (
                <article
                  key={r.id}
                  className={`response-card${isSel ? " response-card--selected" : ""}`}
                  onClick={() => setSelectedId(r.id)}
                >
                  <div className="response-card__top">
                    <span>rep-{r.id} · v{r.version}</span>
                    <StatusPill status={uiStatus} />
                  </div>
                  <h3 className="response-card__title">{r.appel_offre_titre}</h3>
                  <div className="response-card__bottom">
                    <span>{r.appel_offre_emetteur || "—"}</span>
                    <span>
                      {r.longueur_mots ? `${r.longueur_mots} mots · ` : ""}
                      {formatDate(r.cree_le).split(" ")[1] || formatDate(r.cree_le)}
                    </span>
                  </div>
                </article>
              );
            })
          )}
        </div>

        {selectedSummary && detail && (
          <ResponseDetail
            key={detail.id}
            summary={selectedSummary}
            detail={detail}
            loading={loadingDetail}
            onStatusChange={onStatusChange}
            onSaveContent={onSaveContent}
          />
        )}
        {!selectedSummary && !loadingList && reponses.length > 0 && (
          <div className="response-detail" style={{ padding: 30, color: "var(--fg-3)" }}>
            Sélectionne une réponse à gauche.
          </div>
        )}
      </div>
    </div>
  );
}

type DetailProps = {
  summary: ReponseAvecAO;
  detail: ReponseHermion;
  loading: boolean;
  onStatusChange: (
    next: StatutReponseHermion,
    commentaire?: string,
    toast?: ToastInput,
  ) => void;
  onSaveContent: (contenu: string, commentaire?: string) => void;
};

function ResponseDetail({
  summary,
  detail,
  loading,
  onStatusChange,
  onSaveContent,
}: DetailProps) {
  const [editing, setEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(detail.contenu);
  const [comment, setComment] = useState(detail.commentaire_humain ?? "");

  useEffect(() => {
    setEditedContent(detail.contenu);
    setComment(detail.commentaire_humain ?? "");
    setEditing(false);
  }, [detail.id, detail.contenu, detail.commentaire_humain]);

  const uiStatus = toUiStatus(detail.statut);
  const verrouille = detail.statut === "exportee" || detail.statut === "rejetee";
  const peutValider = detail.statut === "en_attente" || detail.statut === "a_modifier";
  const showCommentBox = detail.statut === "a_modifier" || detail.statut === "rejetee" || editing;

  const profil = loadUserProfile();
  const profilLabel = profil
    ? `${profil.firstName} ${profil.lastName}`.trim()
    : "Utilisateur non configuré";

  return (
    <div className="response-detail">
      <aside className="response-actions">
        <div
          style={{
            fontSize: 10.5,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--fg-4)",
            marginBottom: 8,
          }}
        >
          Réponse #{detail.id} · v{detail.version}
        </div>
        <h2
          style={{
            fontSize: 15,
            fontWeight: 600,
            lineHeight: 1.35,
            margin: "0 0 8px",
            letterSpacing: "-0.005em",
          }}
        >
          {summary.appel_offre_titre}
        </h2>
        <div style={{ fontSize: 12, color: "var(--fg-3)", marginBottom: 16 }}>
          {summary.appel_offre_emetteur || "Émetteur inconnu"}
        </div>

        <div style={{ marginBottom: 18 }}>
          <StatusPill status={uiStatus} />
        </div>

        <dl className="kv" style={{ marginBottom: 22 }}>
          <dt>Version</dt>
          <dd style={{ fontFamily: "var(--font-mono)" }}>v{detail.version}</dd>
          <dt>Mots</dt>
          <dd>{detail.longueur_mots ?? "—"}</dd>
          <dt>Généré</dt>
          <dd style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>
            {formatDate(detail.cree_le)}
          </dd>
          <dt>Durée</dt>
          <dd>{formatDuree(detail.duree_generation_ms)}</dd>
          <dt>Profil</dt>
          <dd style={{ fontSize: 11.5 }}>{profilLabel}</dd>
          <dt>Agent</dt>
          <dd>
            <AgentChip agent="hermion" state="active" compact />
          </dd>
          <dt>Score AO</dt>
          <dd>
            <Score value={70} />
          </dd>
        </dl>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <button
            className="btn btn--ok"
            disabled={!peutValider || loading}
            onClick={() =>
              onStatusChange("validee", undefined, {
                title: "HERMION",
                app: "Réponse validée",
                msg: `La réponse v${detail.version} a été validée — l'AO passe en « répondu ».`,
                agent: "hermion",
              })
            }
          >
            <Icon.check size={13} /> Valider
          </button>
          <button
            className="btn btn--warn"
            disabled={verrouille || loading}
            onClick={() =>
              onStatusChange("a_modifier", comment, {
                title: "HERMION",
                app: "Révision demandée",
                msg: "La réponse est passée en « à modifier ».",
                agent: "hermion",
              })
            }
          >
            <Icon.refresh size={13} /> Demander une révision
          </button>
          <button
            className="btn btn--danger"
            disabled={verrouille || loading}
            onClick={() =>
              onStatusChange("rejetee", comment, {
                title: "HERMION",
                app: "Réponse rejetée",
                msg: `La réponse v${detail.version} a été rejetée.`,
                agent: "hermion",
              })
            }
          >
            <Icon.close size={13} /> Rejeter
          </button>
          <div className="divider" />
          <button
            className="btn"
            disabled={!editing}
            onClick={() => onSaveContent(editedContent, comment)}
          >
            <Icon.check size={13} /> Enregistrer les modifications
          </button>
          <button
            className={`btn ${editing ? "btn--ghost" : ""}`}
            onClick={() => {
              if (editing) {
                setEditedContent(detail.contenu);
                setEditing(false);
              } else {
                setEditing(true);
              }
            }}
            disabled={verrouille}
          >
            <Icon.refresh size={13} /> {editing ? "Annuler l'édition" : "Éditer le contenu"}
          </button>
        </div>

        {showCommentBox && (
          <div style={{ marginTop: 22 }}>
            <div
              style={{
                fontSize: 11,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--fg-3)",
                marginBottom: 8,
              }}
            >
              Commentaire humain
            </div>
            <textarea
              className="response-comment-input"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Notes internes, raisons de la révision/rejet, points à corriger…"
            />
          </div>
        )}
      </aside>

      <div className="response-pdf">
        <div className="pdf-toolbar">
          <span style={{ fontSize: 11 }}>
            Réponse rep-{detail.id} · <strong style={{ color: "var(--fg)" }}>v{detail.version}</strong>
          </span>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 10.5 }}>
            {detail.longueur_mots ?? "—"} mots ·{" "}
            {Math.max(1, Math.ceil((detail.longueur_mots ?? 0) / 350))} p. approx.
          </span>
        </div>

        <div className="pdf-page" style={{ padding: editing ? 0 : undefined }}>
          {editing ? (
            <textarea
              value={editedContent}
              onChange={(e) => setEditedContent(e.target.value)}
              spellCheck
              style={{
                width: "100%",
                height: "100%",
                minHeight: 540,
                resize: "vertical",
                fontFamily: "var(--font-mono)",
                fontSize: 12.5,
                lineHeight: 1.6,
                padding: 20,
                border: "none",
                background: "transparent",
                color: "var(--fg)",
                outline: "none",
              }}
            />
          ) : (
            <ReponseMarkdown contenu={detail.contenu} />
          )}
        </div>
      </div>
    </div>
  );
}

/** Rendu basique du markdown HERMION : titres, paragraphes, listes simples. */
function ReponseMarkdown({ contenu }: { contenu: string }) {
  const blocks = contenu.split(/\n{2,}/);
  return (
    <div style={{ fontSize: 13.5, lineHeight: 1.6 }}>
      {blocks.map((b, i) => {
        const trimmed = b.trim();
        if (!trimmed) return null;
        if (trimmed.startsWith("# ")) {
          return (
            <h1 key={i} style={{ fontSize: 22, fontWeight: 700, marginTop: 0, marginBottom: 14 }}>
              {trimmed.slice(2)}
            </h1>
          );
        }
        if (trimmed.startsWith("## ")) {
          return (
            <h2 key={i} style={{ fontSize: 16, fontWeight: 600, marginTop: 18, marginBottom: 8 }}>
              {trimmed.slice(3)}
            </h2>
          );
        }
        if (trimmed.startsWith("### ")) {
          return (
            <h3 key={i} style={{ fontSize: 14, fontWeight: 600, marginTop: 14, marginBottom: 6 }}>
              {trimmed.slice(4)}
            </h3>
          );
        }
        // Liste numérotée ou à puces
        const lines = trimmed.split("\n");
        const isList = lines.every((l) => /^(\d+\.|-|\*)\s+/.test(l.trim()));
        if (isList) {
          const ordered = /^\d+\./.test(lines[0].trim());
          const Tag = ordered ? "ol" : "ul";
          return (
            <Tag key={i} style={{ margin: "8px 0 12px 22px" }}>
              {lines.map((l, j) => (
                <li key={j} style={{ marginBottom: 4 }}>
                  {l.trim().replace(/^(\d+\.|-|\*)\s+/, "")}
                </li>
              ))}
            </Tag>
          );
        }
        // Paragraphe italique (commence par *…* sur toute la ligne)
        if (/^\*[^*].+\*$/.test(trimmed)) {
          return (
            <p key={i} style={{ fontStyle: "italic", color: "var(--fg-3)", margin: "4px 0" }}>
              {trimmed.slice(1, -1)}
            </p>
          );
        }
        return (
          <p key={i} style={{ margin: "0 0 12px" }}>
            {trimmed}
          </p>
        );
      })}
    </div>
  );
}

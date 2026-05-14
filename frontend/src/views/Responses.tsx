import { useState } from "react";
import {
  RESPONSES,
  RESPONSE_STATUS,
  type Reponse,
  type ResponseStatus,
} from "../lib/data";
import { AgentChip } from "../components/AgentChip";
import { Icon } from "../components/Icon";
import { Score } from "../components/Score";
import { StatusPill } from "../components/StatusPill";
import type { ToastInput } from "../lib/toast";

type Props = { onToast: (t: ToastInput) => void };

const STATUS_FILTERS: { id: ResponseStatus | "all"; label: string }[] = [
  { id: "all",        label: "Toutes" },
  { id: "en-attente", label: "En attente" },
  { id: "a-modifier", label: "À modifier" },
  { id: "validee",    label: "Validées" },
  { id: "rejetee",    label: "Rejetées" },
  { id: "exportee",   label: "Exportées" },
];

export function Responses({ onToast }: Props) {
  const data = RESPONSES;
  const [filter, setFilter] = useState<ResponseStatus | "all">("all");
  const [selectedId, setSelectedId] = useState<string | undefined>(data[0]?.id);
  const [comments, setComments] = useState<Record<string, string>>(() =>
    Object.fromEntries(data.map((r) => [r.id, r.comment || ""])),
  );
  const [statuses, setStatuses] = useState<Record<string, ResponseStatus>>(() =>
    Object.fromEntries(data.map((r) => [r.id, r.status])),
  );

  const filtered = data.filter((r) =>
    filter === "all" ? true : statuses[r.id] === filter,
  );
  const selected = data.find((r) => r.id === selectedId);

  const updateStatus = (
    id: string,
    newStatus: ResponseStatus,
    toastMsg: ToastInput | null,
  ) => {
    setStatuses((s) => ({ ...s, [id]: newStatus }));
    if (toastMsg) onToast(toastMsg);
  };

  return (
    <div className="view">
      <div className="filters">
        {STATUS_FILTERS.map((s) => {
          const count =
            s.id === "all"
              ? data.length
              : data.filter((r) => statuses[r.id] === s.id).length;
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
        <button className="btn btn--ghost btn--sm">
          <Icon.download size={11} /> Tout exporter
        </button>
      </div>

      <div className="responses-layout">
        <div className="responses-list">
          {filtered.map((r) => {
            const status = statuses[r.id];
            const s = RESPONSE_STATUS[status];
            const isSel = r.id === selectedId;
            return (
              <article
                key={r.id}
                className={`response-card${isSel ? " response-card--selected" : ""}`}
                style={{ borderLeftColor: s.color }}
                onClick={() => setSelectedId(r.id)}
              >
                <div className="response-card__top">
                  <span>{r.id}</span>
                  <StatusPill status={status} />
                </div>
                <h3 className="response-card__title">{r.tender}</h3>
                <div className="response-card__bottom">
                  <span>{r.issuer}</span>
                  <span>
                    {r.pages} p. · {r.generatedAt.split(" ")[1]}
                  </span>
                </div>
              </article>
            );
          })}

          {filtered.length === 0 && (
            <div
              style={{
                padding: 30,
                textAlign: "center",
                color: "var(--fg-3)",
                fontSize: 12.5,
              }}
            >
              Aucune réponse dans ce statut.
            </div>
          )}
        </div>

        {selected && (
          <ResponseDetail
            key={selected.id}
            response={selected}
            status={statuses[selected.id]}
            comment={comments[selected.id]}
            onComment={(v) =>
              setComments((c) => ({ ...c, [selected.id]: v }))
            }
            onStatusChange={updateStatus}
            onToast={onToast}
          />
        )}
      </div>
    </div>
  );
}

type DetailProps = {
  response: Reponse;
  status: ResponseStatus;
  comment: string;
  onComment: (v: string) => void;
  onStatusChange: (
    id: string,
    next: ResponseStatus,
    toast: ToastInput | null,
  ) => void;
  onToast: (t: ToastInput) => void;
};

function ResponseDetail({
  response,
  status,
  comment,
  onComment,
  onStatusChange,
  onToast,
}: DetailProps) {
  const showCommentBox = status === "a-modifier" || status === "rejetee";
  const [page, setPage] = useState(1);
  const totalPages = response.pages;

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
          Réponse · {response.id}
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
          {response.tender}
        </h2>
        <div style={{ fontSize: 12, color: "var(--fg-3)", marginBottom: 16 }}>
          {response.issuer}
        </div>

        <div style={{ marginBottom: 18 }}>
          <StatusPill status={status} />
        </div>

        <dl className="kv" style={{ marginBottom: 22 }}>
          <dt>Pages</dt>
          <dd>{response.pages}</dd>
          <dt>Généré</dt>
          <dd style={{ fontFamily: "var(--font-mono)" }}>{response.generatedAt}</dd>
          <dt>Score AO</dt>
          <dd>
            <Score value={response.score} />
          </dd>
          <dt>Agent</dt>
          <dd>
            <AgentChip agent="hermion" state="active" compact />
          </dd>
        </dl>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <button
            className="btn btn--ok"
            onClick={() =>
              onStatusChange(response.id, "validee", {
                title: "Validation",
                app: "Réponse validée",
                msg: `La réponse ${response.id} a été validée et est prête à l'export.`,
                agent: "argos",
              })
            }
            disabled={status === "validee" || status === "exportee"}
          >
            <Icon.check size={13} /> Valider
          </button>
          <button
            className="btn btn--warn"
            onClick={() => onStatusChange(response.id, "a-modifier", null)}
            disabled={status === "exportee"}
          >
            <Icon.refresh size={13} /> Demander une révision
          </button>
          <button
            className="btn btn--danger"
            onClick={() => onStatusChange(response.id, "rejetee", null)}
            disabled={status === "exportee"}
          >
            <Icon.close size={13} /> Rejeter
          </button>
          <div className="divider" />
          <button
            className="btn"
            onClick={() =>
              onToast({
                title: "Export",
                app: "PDF téléchargé",
                msg: `${response.id}.pdf (${response.pages} p.) prêt dans le dossier d'export.`,
                agent: "hermion",
              })
            }
          >
            <Icon.download size={13} /> Télécharger le PDF
          </button>
          <button
            className="btn"
            onClick={() =>
              onToast({
                title: "Envoi mail",
                app: "Mail en file d'attente",
                msg: `Réponse envoyée à ${response.issuer}.`,
                agent: "argos",
              })
            }
          >
            <Icon.mail size={13} /> Envoyer par mail
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
              Commentaire de révision
            </div>
            <textarea
              className="response-comment-input"
              value={comment}
              onChange={(e) => onComment(e.target.value)}
              placeholder="Détaillez les modifications à apporter — HERMION régénérera les sections concernées…"
            />
            <button
              className="btn btn--ghost btn--sm"
              style={{ marginTop: 8, width: "100%" }}
              onClick={() =>
                onToast({
                  title: "HERMION",
                  app: "Régénération demandée",
                  msg: "Brouillon en cours de mise à jour selon vos remarques.",
                  agent: "hermion",
                })
              }
            >
              <Icon.refresh size={11} /> Soumettre à HERMION
            </button>
          </div>
        )}
      </aside>

      <div className="response-pdf">
        <div className="pdf-toolbar">
          <button
            className="btn btn--icon-only btn--ghost btn--sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            style={{ transform: "scaleX(-1)" }}
          >
            <Icon.chevron size={10} />
          </button>
          <span>
            Page <strong style={{ color: "var(--fg)" }}>{page}</strong> / {totalPages}
          </span>
          <button
            className="btn btn--icon-only btn--ghost btn--sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            <Icon.chevron size={10} />
          </button>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 10.5 }}>{response.id} · v1</span>
        </div>

        <div className="pdf-page">
          <div className="pdf-watermark">HERMES · HERMION</div>
          {page === 1 ? (
            <>
              <div className="pdf-meta">RÉPONSE À APPEL D'OFFRE</div>
              <h1>{response.tender}</h1>
              <div className="pdf-meta" style={{ marginTop: 6 }}>
                {response.issuer} · {response.generatedAt}
              </div>

              <h2>1. Présentation du soumissionnaire</h2>
              <p>
                Notre cabinet, fort de quinze années d'expérience auprès des donneurs
                d'ordre publics, propose une offre construite autour d'une équipe
                pluridisciplinaire dédiée à la conduite des programmes de transformation
                numérique. Nous avons mené des missions similaires pour la DGAMPA (2023),
                Naval Group (2024) et la Caisse des Dépôts (2022, 2024).
              </p>

              <h2>2. Compréhension du besoin</h2>
              <p>
                Le marché vise à doter votre direction d'un système d'information
                modernisé, interopérable avec les systèmes existants et capable d'absorber
                la croissance du périmètre fonctionnel attendue sur les trois prochaines
                années.
              </p>

              <h2>3. Synthèse de l'offre</h2>
              <table>
                <tbody>
                  <tr>
                    <td>Périmètre</td>
                    <td>SI métier + RUN 3 ans + TMA</td>
                  </tr>
                  <tr>
                    <td>Méthodologie</td>
                    <td>Agile à l'échelle (SAFe niveau Essentiel)</td>
                  </tr>
                  <tr>
                    <td>Équipe dédiée</td>
                    <td>14 ETP — dont 3 architectes senior</td>
                  </tr>
                  <tr>
                    <td>Démarrage</td>
                    <td>T+15 jours après notification</td>
                  </tr>
                </tbody>
              </table>
            </>
          ) : (
            <>
              <div className="pdf-meta">Page {page}</div>
              <h2>Section — Méthodologie projet</h2>
              <p>
                Notre approche s'appuie sur un découpage en cycles de livraison itératifs
                de trois semaines, chacun aboutissant à une démonstration en environnement
                de recette et à une validation formelle des Product Owners désignés.
              </p>
              <p>
                Les points de gouvernance hebdomadaires permettent d'arbitrer en temps
                réel les écarts de périmètre et d'ajuster les priorités selon les besoins
                métiers identifiés en cours de mission.
              </p>
              <h2>Indicateurs de pilotage</h2>
              <table>
                <tbody>
                  <tr>
                    <td>Vélocité</td>
                    <td>Mesurée par sprint — cible 80 points</td>
                  </tr>
                  <tr>
                    <td>Qualité</td>
                    <td>Taux de défauts critiques &lt; 2 %</td>
                  </tr>
                  <tr>
                    <td>Satisfaction</td>
                    <td>Enquête trimestrielle, cible NPS ≥ 40</td>
                  </tr>
                </tbody>
              </table>
              <p>
                Chaque jalon contractuel fait l'objet d'un comité de validation auquel
                participent les représentants de la maîtrise d'ouvrage, de la maîtrise
                d'œuvre interne et de notre direction de projet.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

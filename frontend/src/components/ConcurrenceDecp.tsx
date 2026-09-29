import { api, type AnalyseConcurrence } from "../lib/api";
import { useApi } from "../lib/useApi";

/**
 * Encart « Concurrence (DECP) » de la fiche AO : historique open data des
 * marchés attribués au même acheteur (SIRET) et dans le même secteur (CPV) sur
 * 3 ans — titulaires récurrents, montant médian, tendance.
 */
export function ConcurrenceDecp({ aoId }: { aoId: number }) {
  const { data, error, loading, reload } = useApi(
    (signal) => api.concurrenceAO(aoId, false, signal),
    [aoId],
  );

  return (
    <div className="tender-panel__section" data-testid="concurrence-decp">
      <div className="tender-panel__section-title">
        Concurrence (DECP)
        <button
          className="btn btn--ghost"
          style={{ marginLeft: "auto", padding: "2px 8px", fontSize: 11 }}
          disabled={loading}
          onClick={() => void reload()}
          title="Relit le cache local (renouvelé toutes les 24 h)"
        >
          {loading ? "Chargement…" : "Actualiser"}
        </button>
      </div>

      {loading && !data && <p className="tender-panel__summary">Interrogation des DECP…</p>}
      {error && !data && (
        <p className="tender-panel__summary" role="alert">
          Historique indisponible : {error}
        </p>
      )}
      {data?.message && (
        <p style={{ fontSize: 12, color: "var(--fg-3)", margin: "0 0 10px" }}>{data.message}</p>
      )}
      {data?.acheteur && <Bloc titre="Même acheteur" analyse={data.acheteur} />}
      {data?.secteur && (
        <Bloc titre={`Même secteur (CPV ${data.cpv?.slice(0, 4) ?? ""}…)`} analyse={data.secteur} />
      )}
      {data?.maj_le && (
        <p style={{ fontSize: 11, color: "var(--fg-4)", margin: "6px 0 0" }}>
          Source : data.gouv.fr (DECP consolidées) · {data.depuis_cache ? "cache local" : "à jour"}{" "}
          du {new Date(data.maj_le).toLocaleDateString("fr-FR")}
        </p>
      )}
    </div>
  );
}

const TENDANCES: Record<string, string> = {
  hausse: "↗ en hausse",
  baisse: "↘ en baisse",
  stable: "→ stable",
  indeterminee: "indéterminée",
};

function euros(v: number | null): string {
  return v == null ? "—" : `${Math.round(v).toLocaleString("fr-FR")} €`;
}

function Bloc({ titre, analyse }: { titre: string; analyse: AnalyseConcurrence }) {
  if (analyse.nb_marches === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--fg-3)" }}>
        {titre} : aucun marché notifié sur {analyse.periode_annees} ans.
      </p>
    );
  }
  const t = analyse.tendance;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-2)", marginBottom: 6 }}>
        {titre}
      </div>
      <dl className="kv">
        <dt>Marchés ({analyse.periode_annees} ans)</dt>
        <dd>
          {analyse.nb_marches}
          {analyse.echantillon_plafonne ? " (échantillon des plus récents)" : ""}
        </dd>
        <dt>Montant médian</dt>
        <dd>{euros(analyse.montant_median)}</dd>
        <dt>Offres reçues (moy.)</dt>
        <dd>{analyse.offres_moyennes ?? "—"}</dd>
        <dt>Tendance 12 mois</dt>
        <dd>
          {TENDANCES[t.sens] ?? t.sens} — {t.nb_recent} marché(s) vs {t.nb_precedent} l'an
          précédent, médiane {euros(t.montant_median_recent)} vs {euros(t.montant_median_precedent)}
        </dd>
      </dl>
      <div style={{ fontSize: 11, color: "var(--fg-3)", margin: "8px 0 4px" }}>
        Titulaires récurrents
      </div>
      <ul className="keypoints">
        {analyse.titulaires.slice(0, 5).map((x) => (
          <li key={`${x.siret ?? x.nom}`}>
            {x.nom} — {x.nb_marches} marché(s), {euros(x.montant_total)}
          </li>
        ))}
      </ul>
    </div>
  );
}

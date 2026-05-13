import { useEffect, useState } from "react";
import { api, type AppelsOffrePage } from "../lib/api";

export function Veille() {
  const [page, setPage] = useState<AppelsOffrePage | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    api
      .listerAO()
      .then(setPage)
      .catch((e) => setErreur(e instanceof Error ? e.message : String(e)));
  }, []);

  if (erreur) {
    return (
      <div className="p-6 text-red-400">
        Erreur lors du chargement : {erreur}
      </div>
    );
  }

  if (!page) {
    return <div className="p-6 text-slate-400">Chargement…</div>;
  }

  if (page.total === 0) {
    return (
      <div className="p-6 text-slate-400">
        <h2 className="text-lg text-slate-200 mb-2">Aucun appel d'offre détecté</h2>
        <p>
          ARGOS n'a pas encore collecté de données. Phase 2 du projet :
          configuration des portails et premières collectes.
        </p>
      </div>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead className="text-left text-slate-400 border-b border-slate-800">
        <tr>
          <th className="px-4 py-2">Titre</th>
          <th className="px-4 py-2">Émetteur</th>
          <th className="px-4 py-2">Date limite</th>
          <th className="px-4 py-2">Statut</th>
        </tr>
      </thead>
      <tbody>
        {page.items.map((ao) => (
          <tr key={ao.id} className="border-b border-slate-900 hover:bg-slate-900/40">
            <td className="px-4 py-2">{ao.titre}</td>
            <td className="px-4 py-2 text-slate-300">{ao.emetteur ?? "—"}</td>
            <td className="px-4 py-2 text-slate-300">{ao.date_limite ?? "—"}</td>
            <td className="px-4 py-2 text-slate-300">{ao.statut}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

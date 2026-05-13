import { useEffect, useState } from "react";
import { api, type HealthResponse } from "../lib/api";

type Etat = "verification" | "ok" | "ko";

export function StatusBar() {
  const [etat, setEtat] = useState<Etat>("verification");
  const [info, setInfo] = useState<HealthResponse | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let actif = true;
    const verifier = async () => {
      try {
        const h = await api.health();
        if (!actif) return;
        setInfo(h);
        setEtat("ok");
        setErreur(null);
      } catch (e) {
        if (!actif) return;
        setEtat("ko");
        setErreur(e instanceof Error ? e.message : String(e));
      }
    };
    verifier();
    const t = setInterval(verifier, 10_000);
    return () => {
      actif = false;
      clearInterval(t);
    };
  }, []);

  const pastille =
    etat === "ok"
      ? "bg-emerald-500"
      : etat === "ko"
        ? "bg-red-500"
        : "bg-amber-400 animate-pulse";

  const message =
    etat === "ok"
      ? `Backend OK — v${info?.version ?? "?"} @ ${info?.timestamp ?? ""}`
      : etat === "ko"
        ? `Backend injoignable : ${erreur ?? ""}`
        : "Vérification du backend…";

  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <span className={`inline-block w-2 h-2 rounded-full ${pastille}`} />
      <span>{message}</span>
    </div>
  );
}

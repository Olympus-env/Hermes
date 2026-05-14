import { useEffect, useState } from "react";
import { api, type StatutModele } from "../lib/api";

const GIGA = 1024 * 1024 * 1024;
const POLL_INTERVAL_MS = 1500;

type Props = {
  onReady: () => void;
};

function formatGo(octets: number): string {
  if (octets <= 0) return "0 Go";
  return `${(octets / GIGA).toFixed(2)} Go`;
}

/**
 * Modal bloquant qui apparaît au démarrage si le modèle PYTHIA principal
 * n'est pas installé. Lance le téléchargement et affiche la progression.
 * Appelle `onReady` quand le modèle est disponible.
 */
export function ModelDownloader({ onReady }: Props) {
  const [statut, setStatut] = useState<StatutModele | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [demarrageDemande, setDemarrageDemande] = useState(false);

  // Poll de l'état toutes les 1.5 s tant que le modèle n'est pas prêt.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const s = await api.statutModele();
        if (cancelled) return;
        setStatut(s);
        setErreur(null);

        if (s.installe && !s.progression.en_cours) {
          onReady();
          return;
        }
        timer = window.setTimeout(tick, POLL_INTERVAL_MS);
      } catch (e) {
        if (cancelled) return;
        setErreur(e instanceof Error ? e.message : String(e));
        timer = window.setTimeout(tick, POLL_INTERVAL_MS * 2);
      }
    };

    tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [onReady]);

  // Démarrage automatique du téléchargement dès qu'on sait que le modèle
  // manque et qu'Ollama est joignable.
  useEffect(() => {
    if (!statut || demarrageDemande) return;
    if (!statut.ollama_disponible) return;
    if (statut.installe) return;
    if (statut.progression.en_cours) return;

    setDemarrageDemande(true);
    api.telechargerModele().catch((e) => {
      setErreur(e instanceof Error ? e.message : String(e));
      setDemarrageDemande(false);
    });
  }, [statut, demarrageDemande]);

  if (!statut) {
    return (
      <ModalShell titre="Initialisation de HERMES" sousTitre="Vérification de PYTHIA…">
        <div style={{ color: "var(--fg-3)", fontSize: 13 }}>Connexion au backend…</div>
        {erreur && <ErreurBox message={erreur} />}
      </ModalShell>
    );
  }

  if (!statut.ollama_disponible) {
    return (
      <ModalShell
        titre="PYTHIA indisponible"
        sousTitre="Ollama ne répond pas sur 127.0.0.1:11434"
      >
        <p style={{ fontSize: 13, color: "var(--fg-2)", lineHeight: 1.5 }}>
          PYTHIA (Ollama) doit être démarré pour qu'HERMES fonctionne. Si HERMES
          a été lancé via <code>hermes.exe</code>, Ollama est démarré
          automatiquement — patiente quelques secondes. Sinon, lance
          <code> ollama serve </code> manuellement.
        </p>
        {erreur && <ErreurBox message={erreur} />}
      </ModalShell>
    );
  }

  const p = statut.progression;
  const total = p.octets_total;
  const done = p.octets_telecharges;
  const pourcent = p.pourcent;

  return (
    <ModalShell
      titre="Téléchargement de PYTHIA"
      sousTitre={`Modèle ${statut.modele} — première installation`}
    >
      <p style={{ fontSize: 13, color: "var(--fg-2)", lineHeight: 1.5, marginBottom: 16 }}>
        HERMES télécharge le modèle de langage local. Cette étape n'est faite
        qu'une seule fois. Le téléchargement se poursuit même si tu fermes
        cette fenêtre, mais l'application n'est utilisable qu'à la fin.
      </p>

      <div
        style={{
          width: "100%",
          height: 14,
          background: "var(--bg-2)",
          border: "1px solid var(--line)",
          borderRadius: 7,
          overflow: "hidden",
          marginBottom: 8,
        }}
      >
        <div
          style={{
            width: `${pourcent}%`,
            height: "100%",
            background: "var(--gold)",
            transition: "width 0.3s ease",
          }}
        />
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 12,
          fontFamily: "var(--font-mono)",
          color: "var(--fg-3)",
        }}
      >
        <span>
          {formatGo(done)} {total > 0 && `/ ${formatGo(total)}`}
        </span>
        <span>{pourcent.toFixed(1)} %</span>
      </div>

      <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--fg-4)" }}>
        Statut Ollama : <code>{p.statut || "en attente"}</code>
      </div>

      {p.erreur && <ErreurBox message={p.erreur} />}
      {erreur && !p.erreur && <ErreurBox message={erreur} />}
    </ModalShell>
  );
}

function ModalShell({
  titre,
  sousTitre,
  children,
}: {
  titre: string;
  sousTitre?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10,10,10,0.85)",
        backdropFilter: "blur(4px)",
        display: "grid",
        placeItems: "center",
        zIndex: 9999,
      }}
    >
      <div
        style={{
          width: "min(560px, 92vw)",
          background: "var(--bg-1)",
          border: "1px solid var(--line-strong)",
          borderRadius: 10,
          padding: "24px 28px",
          boxShadow: "0 12px 48px rgba(0,0,0,0.6)",
        }}
      >
        <div style={{ marginBottom: 18 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>{titre}</h2>
          {sousTitre && (
            <div style={{ marginTop: 4, fontSize: 12.5, color: "var(--fg-3)" }}>
              {sousTitre}
            </div>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}

function ErreurBox({ message }: { message: string }) {
  return (
    <div
      style={{
        marginTop: 14,
        padding: "10px 14px",
        background: "rgba(220,80,80,0.10)",
        border: "1px solid rgba(220,80,80,0.30)",
        borderRadius: 6,
        fontSize: 12.5,
        color: "var(--fg-2)",
      }}
    >
      Erreur : {message}
    </div>
  );
}

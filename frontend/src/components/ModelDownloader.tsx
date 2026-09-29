import { useEffect, useState } from "react";
import { api, type OptionsModeles, type StatutModele } from "../lib/api";

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
 * n'est pas installé. Propose de choisir un modèle déjà installé ou d'en
 * télécharger un (sur clic explicite), avec suivi et annulation.
 * Appelle `onReady` quand le modèle est disponible.
 */
export function ModelDownloader({ onReady }: Props) {
  const [statut, setStatut] = useState<StatutModele | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [options, setOptions] = useState<OptionsModeles | null>(null);
  const [choix, setChoix] = useState("");

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

  // Options (modèles proposés / installés, espace disque) : chargées une fois
  // Ollama joignable. AUCUN téléchargement n'est lancé sans clic explicite.
  const ollamaOk = statut?.ollama_disponible ?? false;
  useEffect(() => {
    if (!ollamaOk) return;
    api
      .optionsModeles()
      .then((o) => {
        setOptions(o);
        setChoix((c) => c || o.modele_actuel);
      })
      .catch((e) => setErreur(e instanceof Error ? e.message : String(e)));
  }, [ollamaOk]);

  const lancer = async () => {
    setErreur(null);
    try {
      await api.telechargerModele(choix);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    }
  };

  const annuler = async () => {
    try {
      await api.annulerTelechargementModele();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    }
  };

  const utiliserInstalle = async (nom: string) => {
    setErreur(null);
    try {
      await api.choisirModeleInstalle(nom);
      onReady();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    }
  };

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

  if (!p.en_cours) {
    const propose = options?.proposes.find((m) => m.nom === choix);
    const taille = propose?.taille_octets ?? 0;
    const libre = options?.espace_disque_libre_octets ?? 0;
    const insuffisant = taille > 0 && libre > 0 && libre < taille * 1.2;
    const installesDispo = options?.installes ?? [];
    return (
      <ModalShell
        titre="Modèle PYTHIA requis"
        sousTitre={`Le modèle « ${statut.modele} » n'est pas installé`}
      >
        <p style={{ fontSize: 13, color: "var(--fg-2)", lineHeight: 1.5, marginBottom: 14 }}>
          Rien n'est téléchargé sans ton accord. Choisis un modèle déjà présent
          dans Ollama, ou lance explicitement un téléchargement.
        </p>

        {installesDispo.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 12, color: "var(--fg-3)", marginBottom: 6 }}>
              Modèles déjà installés
            </div>
            {installesDispo.map((nom) => (
              <button
                key={nom}
                className="btn"
                style={{ marginRight: 6, marginBottom: 6 }}
                onClick={() => void utiliserInstalle(nom)}
              >
                Utiliser {nom}
              </button>
            ))}
          </div>
        )}

        <div style={{ fontSize: 12, color: "var(--fg-3)", marginBottom: 6 }}>
          Télécharger un modèle
        </div>
        <select
          value={choix}
          onChange={(e) => setChoix(e.target.value)}
          style={{ width: "100%", marginBottom: 8 }}
        >
          {(options?.proposes ?? []).map((m) => (
            <option key={m.nom} value={m.nom}>
              {m.nom} — ~{formatGo(m.taille_octets)}
              {m.installe ? " (installé)" : ""}
            </option>
          ))}
        </select>
        <div style={{ fontSize: 12, color: "var(--fg-3)", lineHeight: 1.5 }}>
          Taille estimée (indicative) : {taille > 0 ? formatGo(taille) : "inconnue"}
          {" · "}espace disque libre : {libre > 0 ? formatGo(libre) : "inconnu"}
        </div>
        {insuffisant && (
          <ErreurBox message="Espace disque probablement insuffisant pour ce modèle." />
        )}
        {p.statut === "annule" && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--fg-3)" }}>
            Téléchargement annulé.
          </div>
        )}

        <div style={{ marginTop: 16 }}>
          <button
            className="btn"
            disabled={!choix || !!propose?.installe || insuffisant}
            onClick={() => void lancer()}
          >
            Télécharger
          </button>
        </div>

        {p.erreur && <ErreurBox message={p.erreur} />}
        {erreur && !p.erreur && <ErreurBox message={erreur} />}
      </ModalShell>
    );
  }

  return (
    <ModalShell
      titre="Téléchargement de PYTHIA"
      sousTitre={`Modèle ${statut.modele}`}
    >
      <p style={{ fontSize: 13, color: "var(--fg-2)", lineHeight: 1.5, marginBottom: 16 }}>
        HERMES télécharge le modèle de langage local que tu as demandé. Tu peux
        annuler à tout moment ; l'application n'est utilisable qu'à la fin.
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

      <div style={{ marginTop: 14 }}>
        <button className="btn" onClick={() => void annuler()}>
          Annuler le téléchargement
        </button>
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

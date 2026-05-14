import { useEffect, useState } from "react";
import type { ToastInput } from "../lib/toast";
import { HermesMark } from "./HermesMark";
import { Icon } from "./Icon";

type Props = {
  onClose: () => void;
  onToast: (t: ToastInput) => void;
};

export function PortalLoginModal({ onClose, onToast }: Props) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");

  useEffect(() => {
    if (step !== 3) return;
    const t = setTimeout(() => {
      onClose();
      onToast({
        title: "ARGOS",
        app: "Portail ajouté",
        msg: `Session ${name || "Portail"} capturée et chiffrée. ARGOS l'utilisera au prochain cycle.`,
        agent: "argos",
      });
    }, 1800);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const steps = [
    { n: 1, label: "Identifier le portail" },
    { n: 2, label: "Connexion interactive" },
    { n: 3, label: "Capture de session" },
  ];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <button className="modal__close" onClick={onClose}>
            <Icon.close />
          </button>
          <div className="modal__eyebrow">
            <HermesMark size={14} />
            <span>HERMES · Première connexion</span>
          </div>
          <h3 className="modal__title">Ajouter un portail de veille</h3>
          <p className="modal__sub">
            Connectez-vous une seule fois dans la fenêtre Playwright. ARGOS conservera la
            session chiffrée et la rejouera à chaque cycle.
          </p>
        </div>

        <div className="modal__body">
          <div className="modal__steps">
            {steps.map((s) => (
              <div
                key={s.n}
                className={`modal__step ${
                  step === s.n
                    ? "modal__step--active"
                    : step > s.n
                      ? "modal__step--done"
                      : ""
                }`}
              >
                <div className="modal__step-num">
                  {step > s.n ? <Icon.check size={10} /> : s.n}
                </div>
                <div className="modal__step-text">{s.label}</div>
              </div>
            ))}

            <div className="modal__hint">
              <span className="modal__hint-icon">
                <Icon.warning size={12} />
              </span>
              <span>
                Aucun mot de passe n'est jamais stocké en clair. Seule la session est
                conservée.
              </span>
            </div>
          </div>

          <div className="modal__viewport">
            {step === 1 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 14, flex: 1 }}>
                <div>
                  <label
                    style={{
                      fontSize: 11,
                      color: "var(--fg-3)",
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                    }}
                  >
                    Nom du portail
                  </label>
                  <input
                    className="input"
                    style={{ marginTop: 6 }}
                    placeholder="ex. Maximilien"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    autoFocus
                  />
                </div>
                <div>
                  <label
                    style={{
                      fontSize: 11,
                      color: "var(--fg-3)",
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                    }}
                  >
                    URL de connexion
                  </label>
                  <input
                    className="input"
                    style={{ marginTop: 6, fontFamily: "var(--font-mono)" }}
                    placeholder="https://maximilien.fr/connexion"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                  />
                </div>
                <div
                  style={{
                    background: "var(--bg-2)",
                    border: "1px solid var(--line)",
                    borderRadius: 6,
                    padding: "14px 16px",
                    fontSize: 12.5,
                    color: "var(--fg-2)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 6,
                    }}
                  >
                    <Icon.warning size={13} />
                    <span style={{ fontWeight: 500 }}>Comportement de la session</span>
                  </div>
                  <span style={{ color: "var(--fg-3)" }}>
                    Une fenêtre Playwright va s'ouvrir. Connectez-vous normalement (2FA,
                    captcha, etc.). Dès que la page d'accueil du portail est visible,
                    fermez la fenêtre — HERMES capturera automatiquement la session.
                  </span>
                </div>
                <div style={{ flex: 1 }} />
              </div>
            )}

            {step === 2 && (
              <>
                <div className="browser-mock">
                  <div className="browser-mock__bar">
                    <div className="browser-mock__dots">
                      <span className="browser-mock__dot" />
                      <span className="browser-mock__dot" />
                      <span className="browser-mock__dot" />
                    </div>
                    <div className="browser-mock__url">
                      {url || "https://maximilien.fr/connexion"}
                    </div>
                  </div>
                  <div className="browser-mock__content">
                    <h3>Connexion à {name || "Maximilien"}</h3>
                    <div className="browser-mock__form">
                      <div className="browser-mock__field">
                        <label>Identifiant</label>
                        <input type="text" defaultValue="utilisateur-demo" />
                      </div>
                      <div className="browser-mock__field">
                        <label>Mot de passe</label>
                        <input type="password" defaultValue="••••••••••••" />
                      </div>
                      <button className="browser-mock__submit">Se connecter</button>
                    </div>
                  </div>
                </div>
                <div className="modal__hint" style={{ marginTop: 14 }}>
                  <span className="modal__hint-icon">
                    <span
                      style={{
                        display: "inline-block",
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        background: "var(--gold)",
                        boxShadow: "0 0 8px var(--gold-glow)",
                      }}
                    />
                  </span>
                  <span>
                    Fenêtre Playwright active — connectez-vous puis revenez ici.
                  </span>
                </div>
              </>
            )}

            {step === 3 && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  flex: 1,
                  gap: 16,
                  padding: "40px 0",
                }}
              >
                <div
                  style={{
                    width: 56,
                    height: 56,
                    border: "2px solid rgba(29,158,117,0.20)",
                    borderTopColor: "var(--argos)",
                    borderRadius: "50%",
                    animation: "spin 0.8s linear infinite",
                  }}
                />
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  Capture de la session…
                </div>
                <div style={{ fontSize: 12, color: "var(--fg-3)" }}>
                  Chiffrement AES-256 puis stockage local sécurisé.
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="modal__foot">
          <div className="modal__foot-state">
            <span>
              Étape <strong style={{ color: "var(--fg)" }}>{step}</strong> / 3
            </span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {step > 1 && step < 3 && (
              <button
                className="btn btn--ghost"
                onClick={() => setStep((step - 1) as 1 | 2)}
              >
                Précédent
              </button>
            )}
            {step < 2 && (
              <button
                className="btn btn--gold"
                onClick={() => setStep(2)}
                disabled={!name || !url}
              >
                Ouvrir Playwright
              </button>
            )}
            {step === 2 && (
              <button className="btn btn--gold" onClick={() => setStep(3)}>
                J'ai terminé la connexion
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

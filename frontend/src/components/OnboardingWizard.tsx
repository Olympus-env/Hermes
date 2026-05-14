import { useState } from "react";
import { HermesMark } from "./HermesMark";
import { api } from "../lib/api";
import { saveUserProfile, markOnboardingDone, type UserProfile } from "../lib/userProfile";

type Step = 1 | 2 | 3;

type Props = {
  onDone: (profile: UserProfile) => void;
};

function parseMotsCles(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * Wizard d'onboarding au tout premier lancement de HERMES.
 *
 * 3 étapes obligatoires avant que l'utilisateur puisse utiliser l'app :
 *   1. Identité (prénom, nom, email)
 *   2. Entreprise (nom, activité, infos utiles pour l'IA)
 *   3. Critères de veille initiaux (mots-clés inclus/exclus)
 *
 * À la fin, on persiste le profil en localStorage et les mots-clés via
 * PUT /argos/filtre. Ainsi le premier cycle ARGOS ne ramènera que des
 * AO pertinents.
 */
export function OnboardingWizard({ onDone }: Props) {
  const [step, setStep] = useState<Step>(1);

  // Étape 1
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");

  // Étape 2
  const [entreprise, setEntreprise] = useState("");
  const [activite, setActivite] = useState("");
  const [infosUtiles, setInfosUtiles] = useState("");

  // Étape 3
  const [inclus, setInclus] = useState("");
  const [exclus, setExclus] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const step1Ok = firstName.trim().length > 0 && lastName.trim().length > 0;
  const step2Ok = entreprise.trim().length > 0 && activite.trim().length > 0;
  const step3Ok = parseMotsCles(inclus).length > 0;

  const finish = async () => {
    setSubmitting(true);
    setErreur(null);
    try {
      const profile = saveUserProfile({
        firstName,
        lastName,
        email,
        entreprise,
        activite,
        infosUtiles,
      });
      await api.ecrireFiltreVeille({
        inclus: parseMotsCles(inclus),
        exclus: parseMotsCles(exclus),
      });
      markOnboardingDone();
      onDone(profile);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal" style={{ width: "min(640px, 94vw)" }}>
        <div className="modal__head">
          <div className="modal__eyebrow">
            <HermesMark size={14} />
            <span>HERMES · Premier lancement — étape {step}/3</span>
          </div>
          <ProgressDots step={step} />
        </div>

        {step === 1 && (
          <StepIdentite
            firstName={firstName}
            lastName={lastName}
            email={email}
            onFirstName={setFirstName}
            onLastName={setLastName}
            onEmail={setEmail}
          />
        )}
        {step === 2 && (
          <StepEntreprise
            entreprise={entreprise}
            activite={activite}
            infosUtiles={infosUtiles}
            onEntreprise={setEntreprise}
            onActivite={setActivite}
            onInfos={setInfosUtiles}
          />
        )}
        {step === 3 && (
          <StepFiltres
            inclus={inclus}
            exclus={exclus}
            onInclus={setInclus}
            onExclus={setExclus}
          />
        )}

        {erreur && (
          <div
            style={{
              margin: "12px 26px 0",
              padding: "10px 14px",
              background: "rgba(220,80,80,0.10)",
              border: "1px solid rgba(220,80,80,0.30)",
              borderRadius: 6,
              fontSize: 12.5,
              color: "var(--fg-2)",
            }}
          >
            Erreur : {erreur}
          </div>
        )}

        <div
          className="modal__foot"
          style={{ justifyContent: "space-between", alignItems: "center" }}
        >
          {step > 1 ? (
            <button
              className="btn btn--ghost"
              onClick={() => setStep((s) => (s === 3 ? 2 : 1) as Step)}
              disabled={submitting}
            >
              ← Retour
            </button>
          ) : (
            <span style={{ fontSize: 11.5, color: "var(--fg-4)" }}>
              Toutes les informations restent locales sur cette machine.
            </span>
          )}

          {step < 3 && (
            <button
              className="btn btn--gold"
              disabled={(step === 1 && !step1Ok) || (step === 2 && !step2Ok)}
              onClick={() => setStep((s) => (s + 1) as Step)}
            >
              Continuer →
            </button>
          )}
          {step === 3 && (
            <button
              className="btn btn--gold"
              disabled={!step3Ok || submitting}
              onClick={finish}
            >
              {submitting ? "Enregistrement…" : "Terminer et ouvrir HERMES"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Sous-composants
// --------------------------------------------------------------------------- //

function ProgressDots({ step }: { step: Step }) {
  return (
    <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: 3,
            borderRadius: 2,
            background: i <= step ? "var(--gold)" : "var(--line-strong)",
            transition: "background 0.2s",
          }}
        />
      ))}
    </div>
  );
}

function StepIdentite({
  firstName,
  lastName,
  email,
  onFirstName,
  onLastName,
  onEmail,
}: {
  firstName: string;
  lastName: string;
  email: string;
  onFirstName: (v: string) => void;
  onLastName: (v: string) => void;
  onEmail: (v: string) => void;
}) {
  return (
    <div className="profile-modal__body">
      <h3 className="modal__title" style={{ marginTop: 0 }}>
        Qui es-tu ?
      </h3>
      <p className="modal__sub" style={{ marginBottom: 18 }}>
        Identité utilisée dans l'interface et transmise à HERMION pour
        personnaliser le ton et la signature des réponses générées.
      </p>

      <div className="settings-row">
        <div className="settings-row__label">Prénom *</div>
        <input
          className="input"
          value={firstName}
          onChange={(e) => onFirstName(e.target.value)}
          autoFocus
        />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row__label">Nom *</div>
          <div className="settings-row__hint">Première lettre = avatar</div>
        </div>
        <input className="input" value={lastName} onChange={(e) => onLastName(e.target.value)} />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row__label">Email</div>
          <div className="settings-row__hint">Optionnel — pour les exports</div>
        </div>
        <input
          className="input"
          type="email"
          value={email}
          onChange={(e) => onEmail(e.target.value)}
        />
      </div>
    </div>
  );
}

function StepEntreprise({
  entreprise,
  activite,
  infosUtiles,
  onEntreprise,
  onActivite,
  onInfos,
}: {
  entreprise: string;
  activite: string;
  infosUtiles: string;
  onEntreprise: (v: string) => void;
  onActivite: (v: string) => void;
  onInfos: (v: string) => void;
}) {
  return (
    <div className="profile-modal__body">
      <h3 className="modal__title" style={{ marginTop: 0 }}>
        Ton entreprise
      </h3>
      <p className="modal__sub" style={{ marginBottom: 18 }}>
        Plus tu en dis ici, mieux KRINOS scorera les AO et plus HERMION
        rédigera de réponses précises et pertinentes.
      </p>

      <div className="settings-row">
        <div className="settings-row__label">Nom de l'entreprise *</div>
        <input
          className="input"
          value={entreprise}
          onChange={(e) => onEntreprise(e.target.value)}
          placeholder="ex : ACME Conseil"
          autoFocus
        />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row__label">Activité principale *</div>
          <div className="settings-row__hint">En quelques mots</div>
        </div>
        <input
          className="input"
          value={activite}
          onChange={(e) => onActivite(e.target.value)}
          placeholder="ex : ESN spécialisée Java / PostgreSQL — AMO secteur public"
        />
      </div>
      <div className="settings-row" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="settings-row__label">Informations utiles pour l'IA</div>
          <div className="settings-row__hint">
            Références clients, certifications, taille équipe, spécialités…
          </div>
        </div>
        <textarea
          className="response-comment-input"
          style={{ minHeight: 100 }}
          value={infosUtiles}
          onChange={(e) => onInfos(e.target.value)}
          placeholder={"ex : 12 ETP, certifié ISO 27001, références : Naval Group (2024), CDC (2023), DGAMPA (2022). Compétences PASSI 4 portées. Tarif jour moyen 950 €."}
        />
      </div>
    </div>
  );
}

function StepFiltres({
  inclus,
  exclus,
  onInclus,
  onExclus,
}: {
  inclus: string;
  exclus: string;
  onInclus: (v: string) => void;
  onExclus: (v: string) => void;
}) {
  return (
    <div className="profile-modal__body">
      <h3 className="modal__title" style={{ marginTop: 0 }}>
        Premiers critères de veille
      </h3>
      <p className="modal__sub" style={{ marginBottom: 18 }}>
        ARGOS filtrera les appels d'offre avant insertion dans MNEMOSYNE
        selon ces mots-clés. Tu pourras les modifier à tout moment dans
        <em> Paramètres → Critères de filtrage</em>.
      </p>

      <div className="settings-row" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="settings-row__label">Mots-clés inclus *</div>
          <div className="settings-row__hint">
            Au moins un mot doit apparaître dans titre/objet/émetteur
          </div>
        </div>
        <textarea
          className="response-comment-input"
          style={{ minHeight: 80 }}
          value={inclus}
          onChange={(e) => onInclus(e.target.value)}
          placeholder="ex : maintenance applicative, java, postgresql, audit cyber, AMO"
          autoFocus
        />
      </div>
      <div className="settings-row" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="settings-row__label">Mots-clés exclus</div>
          <div className="settings-row__hint">
            AO contenant ces termes sont écartés directement
          </div>
        </div>
        <textarea
          className="response-comment-input"
          style={{ minHeight: 80 }}
          value={exclus}
          onChange={(e) => onExclus(e.target.value)}
          placeholder="ex : nettoyage, restauration, espaces verts, climatisation"
        />
      </div>

      <div
        style={{
          marginTop: 14,
          padding: "10px 14px",
          background: "rgba(200,169,81,0.08)",
          border: "1px solid rgba(200,169,81,0.30)",
          borderRadius: 6,
          fontSize: 12,
          color: "var(--fg-2)",
        }}
      >
        Pourquoi cette étape est obligatoire : sans filtre, ARGOS collecterait
        tous les AO BOAMP (plus de 1 000 par jour). Avec quelques mots-clés
        métier précis, tu n'auras à examiner que ceux qui te concernent.
      </div>
    </div>
  );
}

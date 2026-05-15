import { useEffect, useState } from "react";
import {
  getHermionUserContext,
  getProfileAvatarLetter,
  getProfileDisplayName,
  loadUserProfile,
  type UserProfile,
} from "../lib/userProfile";
import { Icon } from "../components/Icon";
import { api, type PortailArgos } from "../lib/api";

type Props = {
  profile: UserProfile | null;
  onSaveProfile: (profile: UserProfile) => void;
};

type SectionId = "profil" | "portails" | "filtrage" | "scoring";

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "profil",   label: "Profil utilisateur" },
  { id: "portails", label: "Portails" },
  { id: "filtrage", label: "Critères de filtrage" },
  { id: "scoring",  label: "Pondération du scoring" },
];

export function Settings({ profile, onSaveProfile }: Props) {
  const [section, setSection] = useState<SectionId>("profil");

  return (
    <div className="view">
      <div className="settings-layout">
        <nav className="settings-nav">
          <div className="nav-section-title" style={{ padding: "0 12px 8px" }}>
            Sections
          </div>
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={`settings-nav__item${
                section === s.id ? " settings-nav__item--active" : ""
              }`}
              onClick={() => setSection(s.id)}
            >
              {s.label}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {section === "profil" && (
            <UserProfileSection profile={profile} onSave={onSaveProfile} />
          )}
          {section === "portails" && <PortalsSection />}
          {section === "filtrage" && <FilteringSection />}
          {section === "scoring" && <ScoringSection />}
        </div>
      </div>
    </div>
  );
}

function UserProfileSection({
  profile,
  onSave,
}: {
  profile: UserProfile | null;
  onSave: (profile: UserProfile) => void;
}) {
  const [firstName, setFirstName] = useState(profile?.firstName ?? "");
  const [lastName, setLastName] = useState(profile?.lastName ?? "");
  const [email, setEmail] = useState(profile?.email ?? "");
  const [entreprise, setEntreprise] = useState(profile?.entreprise ?? "");
  const [activite, setActivite] = useState(profile?.activite ?? "");
  const [infosUtiles, setInfosUtiles] = useState(profile?.infosUtiles ?? "");
  const preview: UserProfile = {
    firstName,
    lastName,
    email,
    entreprise,
    activite,
    infosUtiles,
  };
  const canSave = firstName.trim().length > 0 && lastName.trim().length > 0;

  return (
    <div className="settings-section">
      <h2>Profil utilisateur</h2>
      <p className="settings-section__desc">
        Identité locale et contexte métier injectés dans les prompts KRINOS
        (scoring) et HERMION (rédaction). Plus les informations sont précises,
        plus l'IA produit des réponses pertinentes.
      </p>

      <div className="settings-row">
        <div>
          <div className="settings-row__label">Aperçu</div>
          <div className="settings-row__hint">Topbar et contexte HERMION</div>
        </div>
        <div className="profile-preview">
          <div className="topbar__user-avatar">{getProfileAvatarLetter(preview)}</div>
          <div>
            <div className="profile-preview__name">
              {canSave ? getProfileDisplayName(preview) : "Utilisateur non configuré"}
            </div>
            <div
              className="profile-preview__context"
              style={{ whiteSpace: "pre-line" }}
            >
              {canSave ? getHermionUserContext(preview) : "Nom et prénom requis"}
            </div>
          </div>
        </div>
      </div>

      <div className="settings-row">
        <div className="settings-row__label">Prénom *</div>
        <input
          className="input"
          value={firstName}
          onChange={(e) => setFirstName(e.target.value)}
        />
      </div>

      <div className="settings-row">
        <div>
          <div className="settings-row__label">Nom *</div>
          <div className="settings-row__hint">Sa première lettre définit l'avatar</div>
        </div>
        <input
          className="input"
          value={lastName}
          onChange={(e) => setLastName(e.target.value)}
        />
      </div>

      <div className="settings-row">
        <div>
          <div className="settings-row__label">Email</div>
          <div className="settings-row__hint">Optionnel pour les exports et mails</div>
        </div>
        <input
          className="input"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>

      <div className="settings-row">
        <div>
          <div className="settings-row__label">Entreprise</div>
          <div className="settings-row__hint">Nom de la structure répondant aux AO</div>
        </div>
        <input
          className="input"
          value={entreprise}
          onChange={(e) => setEntreprise(e.target.value)}
          placeholder="ex : ACME Conseil"
        />
      </div>

      <div className="settings-row">
        <div>
          <div className="settings-row__label">Activité principale</div>
          <div className="settings-row__hint">En quelques mots</div>
        </div>
        <input
          className="input"
          value={activite}
          onChange={(e) => setActivite(e.target.value)}
          placeholder="ex : ESN Java/PostgreSQL — AMO secteur public"
        />
      </div>

      <div className="settings-row" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="settings-row__label">Informations utiles pour l'IA</div>
          <div className="settings-row__hint">
            Références, certifications, taille équipe…
          </div>
        </div>
        <textarea
          className="response-comment-input"
          style={{ minHeight: 100 }}
          value={infosUtiles}
          onChange={(e) => setInfosUtiles(e.target.value)}
          placeholder="ex : 12 ETP, certifié ISO 27001, références : Naval Group (2024), CDC (2023). Compétences PASSI 4 portées."
        />
      </div>

      <div style={{ marginTop: 18 }}>
        <button
          className="btn btn--gold"
          disabled={!canSave}
          onClick={() =>
            onSave({
              firstName,
              lastName,
              email,
              entreprise,
              activite,
              infosUtiles,
            })
          }
        >
          Enregistrer le profil
        </button>
      </div>
    </div>
  );
}

const SCRAPER_URLS: Record<string, string> = {
  boamp: "https://www.boamp.fr",
};

function PortalsSection() {
  const [scrapers, setScrapers] = useState<string[]>([]);
  const [portails, setPortails] = useState<PortailArgos[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [scrapersData, portailsData] = await Promise.all([
        api.listerScrapersArgos(),
        api.listerPortailsArgos(),
      ]);
      setScrapers(scrapersData.disponibles);
      setPortails(portailsData);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const toggle = async (nom: string, actif: boolean) => {
    const existant = portails.find((p) => p.nom === nom);
    setSaving(nom);
    setError(null);
    try {
      const updated = await api.enregistrerPortailArgos(nom, {
        url_base: existant?.url_base ?? SCRAPER_URLS[nom] ?? "",
        type: existant?.type ?? "public",
        actif,
        frequence_minutes: existant?.frequence_minutes ?? 360,
      });
      setPortails((rows) => {
        const others = rows.filter((p) => p.nom !== nom);
        return [...others, updated].sort((a, b) => a.nom.localeCompare(b.nom));
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="settings-section">
      <h2>Portails de veille</h2>
      <p className="settings-section__desc">
        ARGOS ne collecte que les portails dont un scraper backend est enregistré.
        Ajouter une ligne de configuration ne suffit pas : chaque portail privé
        doit avoir son implémentation dédiée.
      </p>

      {loading ? (
        <div style={{ color: "var(--fg-3)", fontSize: 13 }}>Chargement…</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 16 }}>
          {scrapers.map((nom) => {
            const portail = portails.find((p) => p.nom === nom);
            const actif = portail?.actif ?? true;
            return (
              <div className="portal-row" key={nom}>
                <div>
                  <div className="portal-row__name">{nom.toUpperCase()}</div>
                  <div className="portal-row__url">
                    {portail?.url_base ?? SCRAPER_URLS[nom] ?? "URL non configurée"}
                  </div>
                </div>
                <span className="portal-row__count">
                  {portail ? (actif ? "Actif" : "Inactif") : "Disponible"}
                </span>
                <span className="portal-row__sync">
                  {portail?.derniere_collecte
                    ? new Date(portail.derniere_collecte).toLocaleString("fr-FR")
                    : "Jamais collecté"}
                </span>
                <button
                  className={`toggle${actif ? " toggle--on" : ""}`}
                  onClick={() => void toggle(nom, !actif)}
                  role="switch"
                  aria-checked={actif}
                  disabled={saving === nom}
                  title={
                    actif
                      ? "Désactive ce portail dans la configuration ARGOS"
                      : "Active ce portail dans la configuration ARGOS"
                  }
                >
                  <div className="toggle__thumb" />
                </button>
              </div>
            );
          })}
          {scrapers.length === 0 && (
            <div style={{ color: "var(--fg-3)", fontSize: 13 }}>
              Aucun scraper ARGOS enregistré côté backend.
            </div>
          )}
          {error && (
            <div
              style={{
                marginTop: 12,
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
        </div>
      )}

      <div
        style={{
          marginTop: 14,
          padding: "10px 14px",
          background: "rgba(200,169,81,0.08)",
          border: "1px solid rgba(200,169,81,0.30)",
          borderRadius: 6,
          fontSize: 12,
          color: "var(--fg-2)",
          lineHeight: 1.5,
        }}
      >
        Portails privés : le socle Playwright et le stockage chiffré existent,
        mais chaque portail doit encore être codé puis ajouté au registre ARGOS.
      </div>

      <div style={{ marginTop: 16 }}>
        <button className="btn btn--ghost" disabled title="Nécessite un scraper backend dédié">
          <Icon.plus size={13} /> Ajouter un portail privé
        </button>
      </div>
    </div>
  );
}

function parseMotsCles(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function FilteringSection() {
  const [keywords, setKeywords] = useState("");
  const [excluded, setExcluded] = useState("");
  const [savedKeywords, setSavedKeywords] = useState("");
  const [savedExcluded, setSavedExcluded] = useState("");
  const [actif, setActif] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestionMsg, setSuggestionMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  const dirty = keywords !== savedKeywords || excluded !== savedExcluded;

  useEffect(() => {
    let cancelled = false;
    api
      .lireFiltreVeille()
      .then((f) => {
        if (cancelled) return;
        const inc = f.inclus.join(", ");
        const exc = f.exclus.join(", ");
        setKeywords(inc);
        setExcluded(exc);
        setSavedKeywords(inc);
        setSavedExcluded(exc);
        setActif(f.actif);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onSave = async () => {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const reponse = await api.ecrireFiltreVeille({
        inclus: parseMotsCles(keywords),
        exclus: parseMotsCles(excluded),
      });
      const inc = reponse.inclus.join(", ");
      const exc = reponse.exclus.join(", ");
      setKeywords(inc);
      setExcluded(exc);
      setSavedKeywords(inc);
      setSavedExcluded(exc);
      setActif(reponse.actif);
      setSavedMessage(
        reponse.actif
          ? "Filtre enregistré — il sera appliqué dès la prochaine collecte ARGOS."
          : "Filtre vidé — toutes les collectes ARGOS conservent l'intégralité des AO.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const onSuggest = async () => {
    const profil = loadUserProfile();
    if (!profil || (!profil.entreprise.trim() && !profil.activite.trim())) {
      setError(
        "Renseigne d'abord le nom de l'entreprise et l'activité dans la section " +
          "« Profil utilisateur » — l'IA en a besoin pour suggérer des mots-clés.",
      );
      return;
    }
    setSuggesting(true);
    setError(null);
    setSavedMessage(null);
    setSuggestionMsg(null);
    try {
      const suggestion = await api.suggererFiltreVeille({
        entreprise: profil.entreprise,
        activite: profil.activite,
        infos: profil.infosUtiles,
      });
      // Pré-remplit les textareas sans écraser si l'utilisateur veut fusionner :
      // on remplace pour rester clair (il peut éditer après).
      setKeywords(suggestion.inclus.join(", "));
      setExcluded(suggestion.exclus.join(", "));
      setSuggestionMsg(
        suggestion.raisonnement
          ? `${suggestion.inclus.length} mots-clés inclus, ${suggestion.exclus.length} exclus proposés. ${suggestion.raisonnement} — vérifie puis enregistre.`
          : `${suggestion.inclus.length} mots-clés inclus, ${suggestion.exclus.length} exclus proposés — vérifie puis enregistre.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSuggesting(false);
    }
  };

  return (
    <div className="settings-section">
      <h2>Critères de filtrage</h2>
      <p className="settings-section__desc">
        ARGOS filtre les AO collectés avant insertion dans MNEMOSYNE selon ces
        mots-clés. Un AO est conservé si au moins un mot-clé inclus apparaît dans
        son titre, objet ou émetteur, et qu'aucun mot-clé exclus ne s'y trouve.
        Comparaison insensible à la casse et aux accents.
      </p>

      {loading ? (
        <div style={{ color: "var(--fg-3)", fontSize: 13 }}>Chargement…</div>
      ) : (
        <>
          <div className="settings-row">
            <div>
              <div className="settings-row__label">Mots-clés inclus</div>
              <div className="settings-row__hint">
                Séparés par des virgules. Vide = aucun filtre d'inclusion.
              </div>
            </div>
            <textarea
              className="response-comment-input"
              style={{ minHeight: 60 }}
              placeholder="ex : maintenance applicative, java, postgresql, audit"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
            />
          </div>

          <div className="settings-row">
            <div>
              <div className="settings-row__label">Mots-clés exclus</div>
              <div className="settings-row__hint">
                AO contenant ces termes (titre/objet/émetteur) sont écartés.
              </div>
            </div>
            <textarea
              className="response-comment-input"
              style={{ minHeight: 60 }}
              placeholder="ex : nettoyage, restauration, espaces verts"
              value={excluded}
              onChange={(e) => setExcluded(e.target.value)}
            />
          </div>

          <div style={{ marginTop: 18, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <button
              className="btn btn--gold"
              disabled={saving || !dirty}
              onClick={onSave}
            >
              {saving
                ? "Enregistrement…"
                : dirty
                  ? "Enregistrer le filtre"
                  : "Aucune modification"}
            </button>
            <button
              className="btn"
              disabled={suggesting}
              onClick={onSuggest}
              title="Demande à PYTHIA des mots-clés pertinents selon le profil de ton entreprise"
            >
              <Icon.refresh size={11} />
              {suggesting ? "PYTHIA réfléchit…" : "Suggérer (IA)"}
            </button>
            {dirty && (
              <span
                style={{
                  fontSize: 12,
                  color: "var(--warn, #e0a93b)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                ● modifications non enregistrées
              </span>
            )}
            <span
              style={{
                fontSize: 12,
                color: actif ? "var(--argos)" : "var(--fg-3)",
                fontFamily: "var(--font-mono)",
                marginLeft: "auto",
              }}
            >
              {actif ? "● filtre actif" : "○ filtre inactif"}
            </span>
          </div>

          {suggestionMsg && (
            <div
              style={{
                marginTop: 12,
                padding: "10px 14px",
                background: "rgba(200,169,81,0.10)",
                border: "1px solid rgba(200,169,81,0.30)",
                borderRadius: 6,
                fontSize: 12.5,
                color: "var(--fg-2)",
                lineHeight: 1.5,
              }}
            >
              {suggestionMsg}
            </div>
          )}

          {savedMessage && (
            <div
              style={{
                marginTop: 12,
                padding: "10px 14px",
                background: "rgba(29,158,117,0.10)",
                border: "1px solid rgba(29,158,117,0.30)",
                borderRadius: 6,
                fontSize: 12.5,
                color: "var(--fg-2)",
              }}
            >
              {savedMessage}
            </div>
          )}
          {error && (
            <div
              style={{
                marginTop: 12,
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
        </>
      )}
    </div>
  );
}

const SCORING_DIMENSIONS: {
  id: keyof Omit<import("../lib/api").PonderationKrinos, "total">;
  label: string;
  desc: string;
}[] = [
  {
    id: "affinite_metier",
    label: "Affinité métier",
    desc: "Correspondance avec l'activité / le savoir-faire de l'entreprise",
  },
  {
    id: "references",
    label: "Références",
    desc: "Capacité à appuyer sur des références similaires passées",
  },
  {
    id: "adequation_budget",
    label: "Adéquation budget",
    desc: "Taille du marché vs capacité de l'entreprise (ni trop petit ni trop gros)",
  },
  {
    id: "capacite_equipe",
    label: "Capacité équipe",
    desc: "Taille équipe requise / délais vs équipe disponible",
  },
  {
    id: "calendrier",
    label: "Risque calendrier",
    desc: "Réalisme des délais de réponse et d'exécution",
  },
];

function ScoringSection() {
  const [values, setValues] = useState<Record<string, number>>(
    Object.fromEntries(SCORING_DIMENSIONS.map((d) => [d.id, 0])),
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedValues, setSavedValues] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const total = SCORING_DIMENSIONS.reduce((s, d) => s + (values[d.id] ?? 0), 0);
  const dirty = SCORING_DIMENSIONS.some((d) => values[d.id] !== savedValues[d.id]);
  const totalOk = total === 100;

  useEffect(() => {
    let cancelled = false;
    api
      .lirePonderation()
      .then((p) => {
        if (cancelled) return;
        const v: Record<string, number> = {
          affinite_metier: p.affinite_metier,
          references: p.references,
          adequation_budget: p.adequation_budget,
          capacite_equipe: p.capacite_equipe,
          calendrier: p.calendrier,
        };
        setValues(v);
        setSavedValues({ ...v });
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const reset = () => {
    const defaults = { affinite_metier: 30, references: 20, adequation_budget: 20, capacite_equipe: 15, calendrier: 15 };
    setValues(defaults);
  };

  const onSave = async () => {
    setSaving(true);
    setError(null);
    setSavedMsg(null);
    try {
      const sauvegarde = await api.ecrirePonderation({
        affinite_metier: values.affinite_metier,
        references: values.references,
        adequation_budget: values.adequation_budget,
        capacite_equipe: values.capacite_equipe,
        calendrier: values.calendrier,
      });
      const v = {
        affinite_metier: sauvegarde.affinite_metier,
        references: sauvegarde.references,
        adequation_budget: sauvegarde.adequation_budget,
        capacite_equipe: sauvegarde.capacite_equipe,
        calendrier: sauvegarde.calendrier,
      };
      setValues(v);
      setSavedValues({ ...v });
      setSavedMsg(
        sauvegarde.total === 100
          ? "Pondération enregistrée. Elle sera utilisée dès la prochaine analyse KRINOS."
          : `Pondération enregistrée (total ${sauvegarde.total} % — le score sera normalisé automatiquement).`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-section">
      <h2>Pondération du scoring</h2>
      <p className="settings-section__desc">
        KRINOS demande à PYTHIA un score 0-100 pour chacune de ces dimensions
        puis le backend calcule le score final en somme pondérée. Total cible :
        100 % (le score est re-normalisé si le total diffère).
      </p>

      {loading ? (
        <div style={{ color: "var(--fg-3)", fontSize: 13 }}>Chargement…</div>
      ) : (
        <>
          {SCORING_DIMENSIONS.map((d) => (
            <div className="settings-row" key={d.id}>
              <div>
                <div className="settings-row__label">{d.label}</div>
                <div className="settings-row__hint">{d.desc}</div>
              </div>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={values[d.id]}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [d.id]: +e.target.value }))
                  }
                />
                <div className="slider-row__val">{values[d.id]} %</div>
              </div>
            </div>
          ))}

          <div
            style={{
              marginTop: 18,
              padding: "12px 16px",
              background: totalOk ? "rgba(29,158,117,0.10)" : "rgba(224,169,59,0.10)",
              border: `1px solid ${
                totalOk ? "rgba(29,158,117,0.30)" : "rgba(224,169,59,0.30)"
              }`,
              borderRadius: 6,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 12.5 }}>
              Total :{" "}
              <strong
                style={{
                  color: totalOk ? "var(--argos)" : "var(--warn)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {total} %
              </strong>
              {!totalOk && (
                <span style={{ color: "var(--fg-3)", marginLeft: 8 }}>
                  — sera re-normalisé à 100 % à l'enregistrement
                </span>
              )}
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn--sm" onClick={reset}>
                Réinitialiser
              </button>
              <button
                className="btn btn--gold btn--sm"
                disabled={saving || !dirty}
                onClick={onSave}
              >
                {saving ? "Enregistrement…" : dirty ? "Enregistrer" : "Aucune modification"}
              </button>
            </div>
          </div>

          {savedMsg && (
            <div
              style={{
                marginTop: 12,
                padding: "10px 14px",
                background: "rgba(29,158,117,0.10)",
                border: "1px solid rgba(29,158,117,0.30)",
                borderRadius: 6,
                fontSize: 12.5,
                color: "var(--fg-2)",
              }}
            >
              {savedMsg}
            </div>
          )}
          {error && (
            <div
              style={{
                marginTop: 12,
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

          <div
            style={{
              marginTop: 18,
              fontSize: 11.5,
              color: "var(--fg-4)",
              lineHeight: 1.6,
            }}
          >
            Note : les AO déjà analysés gardent leur score d'origine. Pour
            recalculer un score avec la nouvelle pondération sans relancer
            PYTHIA, ouvre l'AO dans la Veille puis utilise l'action
            « Recalculer score » si l'analyse contient les scores par dimension.
          </div>
        </>
      )}
    </div>
  );
}

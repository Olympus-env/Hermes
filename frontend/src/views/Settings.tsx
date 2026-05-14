import { useEffect, useState } from "react";
import { PORTALS, type Portal } from "../lib/data";
import {
  getHermionUserContext,
  getProfileAvatarLetter,
  getProfileDisplayName,
  loadUserProfile,
  type UserProfile,
} from "../lib/userProfile";
import { Icon } from "../components/Icon";
import { api } from "../lib/api";

type Props = {
  profile: UserProfile | null;
  onSaveProfile: (profile: UserProfile) => void;
  onOpenLoginModal: () => void;
};

type SectionId = "profil" | "portails" | "filtrage";

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "profil",   label: "Profil utilisateur" },
  { id: "portails", label: "Portails" },
  { id: "filtrage", label: "Critères de filtrage" },
];

export function Settings({ profile, onSaveProfile, onOpenLoginModal }: Props) {
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
          {section === "portails" && <PortalsSection onOpenLogin={onOpenLoginModal} />}
          {section === "filtrage" && <FilteringSection />}
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

function PortalsSection({ onOpenLogin }: { onOpenLogin: () => void }) {
  const [portals, setPortals] = useState<Portal[]>(PORTALS);

  const toggle = (i: number) => {
    setPortals((p) =>
      p.map((portal, idx) => (idx === i ? { ...portal, active: !portal.active } : portal)),
    );
  };

  return (
    <div className="settings-section">
      <h2>Portails de veille</h2>
      <p className="settings-section__desc">
        Liste des portails surveillés par ARGOS. La connexion via Playwright permet de
        récupérer les AO derrière des comptes.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 16 }}>
        {portals.map((p, i) => (
          <div className="portal-row" key={p.name}>
            <div>
              <div className="portal-row__name">{p.name}</div>
              <div className="portal-row__url">{p.url}</div>
            </div>
            <span className="portal-row__count">
              {p.count.toLocaleString("fr-FR")} AO
            </span>
            <span className="portal-row__sync">{p.lastSync}</span>
            <div
              className={`toggle${p.active ? " toggle--on" : ""}`}
              onClick={() => toggle(i)}
              role="switch"
              aria-checked={p.active}
            >
              <div className="toggle__thumb" />
            </div>
          </div>
        ))}
      </div>

      <button className="btn btn--gold" onClick={onOpenLogin}>
        <Icon.plus size={13} /> Ajouter un portail
      </button>
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
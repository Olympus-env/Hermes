import { useEffect, useState } from "react";
import { PORTALS, type Portal } from "../lib/data";
import {
  getHermionUserContext,
  getProfileAvatarLetter,
  getProfileDisplayName,
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
  const preview: UserProfile = { firstName, lastName, email };
  const canSave = firstName.trim().length > 0 && lastName.trim().length > 0;

  return (
    <div className="settings-section">
      <h2>Profil utilisateur</h2>
      <p className="settings-section__desc">
        Identité locale utilisée dans l'interface et transmise à HERMION comme contexte
        pour rédiger les réponses.
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
            <div className="profile-preview__context">
              {canSave ? getHermionUserContext(preview) : "Nom et prénom requis"}
            </div>
          </div>
        </div>
      </div>

      <div className="settings-row">
        <div className="settings-row__label">Prénom</div>
        <input
          className="input"
          value={firstName}
          onChange={(e) => setFirstName(e.target.value)}
        />
      </div>

      <div className="settings-row">
        <div>
          <div className="settings-row__label">Nom</div>
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

      <div style={{ marginTop: 18 }}>
        <button
          className="btn btn--gold"
          disabled={!canSave}
          onClick={() => onSave({ firstName, lastName, email })}
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
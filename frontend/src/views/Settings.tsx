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

type SectionId =
  | "profil"
  | "portails"
  | "filtrage"
  | "scoring"
  | "hermion"
  | "notifications"
  | "llm"
  | "systeme";

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "profil",        label: "Profil utilisateur" },
  { id: "portails",      label: "Portails" },
  { id: "filtrage",      label: "Critères de filtrage" },
  { id: "scoring",       label: "Pondération scoring" },
  { id: "hermion",       label: "Workflow HERMION" },
  { id: "notifications", label: "Notifications mail" },
  { id: "llm",           label: "Modèle LLM" },
  { id: "systeme",       label: "Système" },
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
          {section === "profil"        && (
            <UserProfileSection profile={profile} onSave={onSaveProfile} />
          )}
          {section === "portails"      && <PortalsSection onOpenLogin={onOpenLoginModal} />}
          {section === "filtrage"      && <FilteringSection />}
          {section === "scoring"       && <ScoringSection />}
          {section === "hermion"       && <HermionWorkflowSection />}
          {section === "notifications" && <MailSection />}
          {section === "llm"           && <LLMSection />}
          {section === "systeme"       && <SystemSection />}
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
  const [actif, setActif] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .lireFiltreVeille()
      .then((f) => {
        if (cancelled) return;
        setKeywords(f.inclus.join(", "));
        setExcluded(f.exclus.join(", "));
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
      setKeywords(reponse.inclus.join(", "));
      setExcluded(reponse.exclus.join(", "));
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

          <div style={{ marginTop: 18, display: "flex", gap: 12, alignItems: "center" }}>
            <button
              className="btn btn--gold"
              disabled={saving}
              onClick={onSave}
            >
              {saving ? "Enregistrement…" : "Enregistrer le filtre"}
            </button>
            <span
              style={{
                fontSize: 12,
                color: actif ? "var(--argos)" : "var(--fg-3)",
                fontFamily: "var(--font-mono)",
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

function ScoringSection() {
  const dims = [
    { id: "affinite",   label: "Affinité métier",    default: 30 },
    { id: "refs",       label: "Références",         default: 25 },
    { id: "budget",     label: "Adéquation budget",  default: 20 },
    { id: "equipe",     label: "Capacité équipe",    default: 15 },
    { id: "calendrier", label: "Risque calendrier",  default: 10 },
  ];
  const [values, setValues] = useState<Record<string, number>>(
    Object.fromEntries(dims.map((d) => [d.id, d.default])),
  );
  const total = Object.values(values).reduce((a, b) => a + b, 0);

  return (
    <div className="settings-section">
      <h2>Pondération du scoring</h2>
      <p className="settings-section__desc">
        Chaque dimension contribue au score de pertinence calculé par KRINOS. Total cible :
        100 %.
      </p>

      {dims.map((d) => (
        <div className="settings-row" key={d.id}>
          <div>
            <div className="settings-row__label">{d.label}</div>
          </div>
          <div className="slider-row">
            <input
              type="range"
              min="0"
              max="50"
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
          background: total === 100 ? "rgba(29,158,117,0.10)" : "rgba(224,169,59,0.10)",
          border: `1px solid ${
            total === 100 ? "rgba(29,158,117,0.30)" : "rgba(224,169,59,0.30)"
          }`,
          borderRadius: 6,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 12.5 }}>
          Total :{" "}
          <strong
            style={{
              color: total === 100 ? "var(--argos)" : "var(--warn)",
              fontFamily: "var(--font-mono)",
            }}
          >
            {total} %
          </strong>
          {total !== 100 && (
            <span style={{ color: "var(--fg-3)", marginLeft: 8 }}>
              — ajustez pour atteindre 100 %
            </span>
          )}
        </span>
        <button
          className="btn btn--sm"
          onClick={() =>
            setValues(Object.fromEntries(dims.map((d) => [d.id, d.default])))
          }
        >
          Réinitialiser
        </button>
      </div>
    </div>
  );
}

function HermionWorkflowSection() {
  const files = [
    { name: "modele-reponse-AMO.docx",      size: "412 ko", date: "12 mai"  },
    { name: "references-clients-2024.pdf",  size: "2.8 Mo", date: "10 mai"  },
    { name: "cv-equipe-architectes.pdf",    size: "1.4 Mo", date: "08 mai"  },
    { name: "kbis-rcs-juin-2025.pdf",       size: "84 ko",  date: "21 avr." },
  ];

  return (
    <div className="settings-section">
      <h2>Workflow HERMION</h2>
      <p className="settings-section__desc">
        Base de connaissances utilisée par HERMION pour rédiger les réponses. Glissez vos
        modèles, références et documents administratifs.
      </p>

      <div className="settings-row">
        <div>
          <div className="settings-row__label">Modèle de réponse par défaut</div>
        </div>
        <select className="filter-select" style={{ width: "100%" }}>
          <option>Modèle AMO — secteur public</option>
          <option>Modèle Audit cyber — PASSI</option>
          <option>Modèle Marché de prestation TMA</option>
        </select>
      </div>

      <div className="settings-row" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="settings-row__label">Base documentaire</div>
          <div className="settings-row__hint">
            {files.length} fichier{files.length > 1 ? "s" : ""} indexé
            {files.length > 1 ? "s" : ""}
          </div>
        </div>
        <div>
          <div
            style={{
              border: "1px dashed var(--line-strong)",
              borderRadius: 8,
              padding: "22px 18px",
              textAlign: "center",
              color: "var(--fg-3)",
              background: "rgba(247,245,240,0.02)",
              marginBottom: 12,
            }}
          >
            <Icon.download size={20} />
            <div style={{ marginTop: 8, fontSize: 12.5 }}>
              Glissez vos fichiers ici ou{" "}
              <button
                className="btn btn--ghost btn--sm"
                style={{ display: "inline-flex" }}
              >
                parcourir
              </button>
            </div>
            <div style={{ fontSize: 11, color: "var(--fg-4)", marginTop: 4 }}>
              PDF · DOCX · MD · TXT — jusqu'à 50 Mo
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {files.map((f) => (
              <div
                key={f.name}
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr auto auto",
                  gap: 10,
                  padding: "8px 12px",
                  background: "var(--bg-2)",
                  border: "1px solid var(--line)",
                  borderRadius: 4,
                  alignItems: "center",
                  fontSize: 12,
                }}
              >
                <Icon.document size={13} />
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>
                  {f.name}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--fg-3)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {f.size}
                </span>
                <span style={{ fontSize: 11, color: "var(--fg-4)" }}>{f.date}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function MailSection() {
  return (
    <div className="settings-section">
      <h2>Notifications mail</h2>
      <p className="settings-section__desc">
        Configuration SMTP pour l'envoi des notifications et l'export des réponses
        validées.
      </p>

      <div className="settings-row">
        <div className="settings-row__label">Serveur SMTP</div>
        <input className="input" placeholder="smtp.exemple.fr" />
      </div>
      <div className="settings-row">
        <div className="settings-row__label">Port</div>
        <input className="input" defaultValue="587" />
      </div>
      <div className="settings-row">
        <div className="settings-row__label">Utilisateur</div>
        <input className="input" placeholder="prenom.nom@entreprise.fr" />
      </div>
      <div className="settings-row">
        <div className="settings-row__label">Mot de passe</div>
        <input className="input" type="password" defaultValue="••••••••••••" />
      </div>
      <div className="settings-row">
        <div className="settings-row__label">Adresse expéditeur</div>
        <input
          className="input"
          placeholder="Prénom Nom <prenom.nom@entreprise.fr>"
        />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row__label">Chiffrement</div>
        </div>
        <select className="filter-select" style={{ width: "100%" }}>
          <option>STARTTLS</option>
          <option>SSL/TLS</option>
          <option>Aucun</option>
        </select>
      </div>

      <div style={{ marginTop: 18, display: "flex", gap: 10 }}>
        <button className="btn btn--gold">Enregistrer</button>
        <button className="btn">Tester l'envoi</button>
      </div>
    </div>
  );
}

function LLMSection() {
  const [model, setModel] = useState("llama3.1:70b-instruct-q4");
  const [temp, setTemp] = useState(0.3);
  const [maxTokens, setMaxTokens] = useState(8192);

  const models = [
    { id: "llama3.1:70b-instruct-q4", label: "Llama 3.1 70B Instruct (Q4)", size: "42 Go"  },
    { id: "llama3.1:8b-instruct",     label: "Llama 3.1 8B Instruct",       size: "4.7 Go" },
    { id: "mistral-large:123b",       label: "Mistral Large 123B",          size: "70 Go"  },
    { id: "qwen2.5:32b-instruct",     label: "Qwen 2.5 32B Instruct",       size: "19 Go"  },
    { id: "mixtral:8x7b-instruct",    label: "Mixtral 8×7B Instruct",       size: "26 Go"  },
  ];

  return (
    <div className="settings-section">
      <h2>Modèle LLM</h2>
      <p className="settings-section__desc">
        HERMES s'appuie sur Ollama en local. Sélectionnez le modèle utilisé par KRINOS
        (analyse) et HERMION (rédaction).
      </p>

      <div className="settings-row" style={{ alignItems: "flex-start" }}>
        <div className="settings-row__label">Modèle actif</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {models.map((m) => (
            <button
              key={m.id}
              className="portal-row"
              onClick={() => setModel(m.id)}
              style={{
                gridTemplateColumns: "auto 1fr auto auto",
                gap: 12,
                padding: "10px 14px",
                background: model === m.id ? "rgba(200,169,81,0.08)" : "var(--bg-2)",
                borderColor: model === m.id ? "var(--line-gold)" : "var(--line)",
                border: "1px solid",
                margin: 0,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              <span
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: "50%",
                  border: `2px solid ${
                    model === m.id ? "var(--gold)" : "var(--line-strong)"
                  }`,
                  display: "grid",
                  placeItems: "center",
                }}
              >
                {model === m.id && (
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: "50%",
                      background: "var(--gold)",
                    }}
                  />
                )}
              </span>
              <div style={{ textAlign: "left" }}>
                <div style={{ fontWeight: 500, fontSize: 13, color: "var(--fg)" }}>
                  {m.label}
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--fg-3)",
                    marginTop: 2,
                  }}
                >
                  {m.id}
                </div>
              </div>
              <span className="portal-row__count" style={{ alignSelf: "center" }}>
                {m.size}
              </span>
              <span
                style={{
                  fontSize: 10.5,
                  color: "var(--argos)",
                  background: "rgba(29,158,117,0.10)",
                  padding: "2px 6px",
                  borderRadius: 3,
                  border: "1px solid rgba(29,158,117,0.22)",
                  alignSelf: "center",
                }}
              >
                installé
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="settings-row">
        <div className="settings-row__label">Température</div>
        <div className="slider-row">
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={temp}
            onChange={(e) => setTemp(+e.target.value)}
          />
          <div className="slider-row__val">{temp.toFixed(2)}</div>
        </div>
      </div>
      <div className="settings-row">
        <div className="settings-row__label">Tokens max</div>
        <div className="slider-row">
          <input
            type="range"
            min="1024"
            max="32768"
            step="1024"
            value={maxTokens}
            onChange={(e) => setMaxTokens(+e.target.value)}
          />
          <div className="slider-row__val" style={{ width: 64 }}>
            {maxTokens.toLocaleString("fr-FR")}
          </div>
        </div>
      </div>

      <div
        style={{
          marginTop: 18,
          padding: "12px 16px",
          background: "rgba(29,158,117,0.06)",
          border: "1px solid rgba(29,158,117,0.20)",
          borderRadius: 6,
          fontSize: 12,
          color: "var(--fg-2)",
        }}
      >
        <span
          style={{
            color: "var(--argos)",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.06em",
          }}
        >
          ● ollama serve
        </span>
        <span style={{ color: "var(--fg-4)", margin: "0 8px" }}>·</span>
        <span style={{ fontFamily: "var(--font-mono)" }}>
          127.0.0.1:11434 — running
        </span>
      </div>
    </div>
  );
}

function SystemSection() {
  return (
    <div className="settings-section">
      <h2>Système</h2>
      <p className="settings-section__desc">
        Maintenance et état général de l'application.
      </p>

      <dl className="kv" style={{ gridTemplateColumns: "180px 1fr", fontSize: 13 }}>
        <dt>Version</dt>
        <dd style={{ fontFamily: "var(--font-mono)" }}>HERMES v0.6.2 (build 1124)</dd>
        <dt>Base de données</dt>
        <dd style={{ fontFamily: "var(--font-mono)" }}>
          SQLite · 412 Mo · 1 284 entrées
        </dd>
        <dt>Cache documents</dt>
        <dd style={{ fontFamily: "var(--font-mono)" }}>
          ~/Library/Hermes/cache · 2.1 Go
        </dd>
        <dt>Logs</dt>
        <dd style={{ fontFamily: "var(--font-mono)" }}>~/Library/Hermes/logs</dd>
        <dt>Dernière sauvegarde</dt>
        <dd>il y a 6 h — automatique, quotidienne</dd>
      </dl>

      <div style={{ marginTop: 22, display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button className="btn">Sauvegarder maintenant</button>
        <button className="btn">Exporter les logs</button>
        <button className="btn btn--ghost">Vider le cache</button>
        <button className="btn btn--danger">Réinitialiser la base</button>
      </div>
    </div>
  );
}

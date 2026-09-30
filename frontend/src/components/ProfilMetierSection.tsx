import { useEffect, useState, type ReactNode } from "react";
import { api, type ProfilMetier } from "../lib/api";
import type { UserProfile } from "../lib/userProfile";

const VIDE: ProfilMetier = {
  activite: "",
  secteurs: [],
  codes_cpv: [],
  zone_geographique: "",
  effectif: null,
  ca_tranche: "",
  certifications: [],
  types_marches: [],
  references_types: [],
};

const TRANCHES_CA = ["", "< 500 k€", "500 k€ - 2 M€", "2 - 10 M€", "10 - 50 M€", "> 50 M€"];

const enListe = (s: string, sep: RegExp = /[,\n]/) =>
  s.split(sep).map((x) => x.trim()).filter(Boolean);

function estVide(p: ProfilMetier): boolean {
  return JSON.stringify(p) === JSON.stringify(VIDE);
}

function Ligne({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <div className="settings-row">
      <div>
        <div className="settings-row__label">{label}</div>
        <div className="settings-row__hint">{hint}</div>
      </div>
      {children}
    </div>
  );
}

/**
 * Profil métier envoyé à KRINOS (PYTHIA, Jev). Aucune donnée d'identité :
 * nom, email et SIRET ne sont ni demandés ni acceptés par le backend.
 */
export function ProfilMetierSection({ legacy }: { legacy: UserProfile | null }) {
  const [p, setP] = useState<ProfilMetier>(VIDE);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Champs listes édités en texte brut (évite de re-parser à chaque frappe).
  const [txt, setTxt] = useState({ secteurs: "", cpv: "", certs: "", types: "", refs: "" });

  const appliquer = (profil: ProfilMetier) => {
    setP(profil);
    setTxt({
      secteurs: profil.secteurs.join(", "),
      cpv: profil.codes_cpv.join(", "),
      certs: profil.certifications.join(", "),
      types: profil.types_marches.join(", "),
      refs: profil.references_types.join("\n"),
    });
  };

  useEffect(() => {
    let annule = false;
    (async () => {
      try {
        let profil = await api.lireProfilMetier();
        // Migration douce : profil backend vide -> reprend l'activité du profil local.
        if (estVide(profil) && legacy?.activite.trim()) {
          profil = await api.ecrireProfilMetier({ ...VIDE, activite: legacy.activite.trim() });
          if (!annule) setMsg("Activité reprise depuis ton profil local.");
        }
        if (!annule) appliquer(profil);
      } catch (e) {
        if (!annule) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!annule) setLoading(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [legacy]);

  const enregistrer = async () => {
    setError(null);
    setMsg(null);
    try {
      const saved = await api.ecrireProfilMetier({
        ...p,
        secteurs: enListe(txt.secteurs),
        codes_cpv: enListe(txt.cpv),
        certifications: enListe(txt.certs),
        types_marches: enListe(txt.types),
        references_types: enListe(txt.refs, /\n/),
      });
      appliquer(saved);
      setMsg("Profil métier enregistré.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (loading) return <div className="settings-section">Chargement…</div>;

  return (
    <div className="settings-section">
      <h2>Profil métier</h2>
      <p className="settings-section__desc">
        Décrit ton savoir-faire pour l'analyse KRINOS (PYTHIA et second avis Jev).
        N'y mets aucune donnée d'identité : nom, email et SIRET sont refusés.
      </p>
      <Ligne label="Activité" hint="ex : ESN Java, cabinet AMO">
        <input className="input" maxLength={400} value={p.activite}
          onChange={(e) => setP({ ...p, activite: e.target.value })} />
      </Ligne>
      <Ligne label="Secteurs" hint="séparés par des virgules">
        <input className="input" value={txt.secteurs}
          onChange={(e) => setTxt({ ...txt, secteurs: e.target.value })} />
      </Ligne>
      <Ligne label="Codes CPV" hint="ex : 72000000-5, 79411000-8">
        <input className="input" value={txt.cpv}
          onChange={(e) => setTxt({ ...txt, cpv: e.target.value })} />
      </Ligne>
      <Ligne label="Zone géographique" hint="région, départements, national…">
        <input className="input" maxLength={200} value={p.zone_geographique}
          onChange={(e) => setP({ ...p, zone_geographique: e.target.value })} />
      </Ligne>
      <Ligne label="Effectif" hint="nombre de personnes">
        <input className="input" type="number" min={0} value={p.effectif ?? ""}
          onChange={(e) =>
            setP({ ...p, effectif: e.target.value === "" ? null : Number(e.target.value) })} />
      </Ligne>
      <Ligne label="Chiffre d'affaires" hint="tranche annuelle">
        <select className="input" value={p.ca_tranche}
          onChange={(e) => setP({ ...p, ca_tranche: e.target.value })}>
          {TRANCHES_CA.map((t) => (
            <option key={t} value={t}>{t || "Non renseigné"}</option>
          ))}
        </select>
      </Ligne>
      <Ligne label="Certifications" hint="ex : ISO 27001, Qualiopi">
        <input className="input" value={txt.certs}
          onChange={(e) => setTxt({ ...txt, certs: e.target.value })} />
      </Ligne>
      <Ligne label="Types de marchés visés" hint="ex : services, accords-cadres">
        <input className="input" value={txt.types}
          onChange={(e) => setTxt({ ...txt, types: e.target.value })} />
      </Ligne>
      <Ligne label="Références types" hint="une par ligne, sans nom de personne">
        <textarea className="response-comment-input" style={{ minHeight: 100 }} value={txt.refs}
          onChange={(e) => setTxt({ ...txt, refs: e.target.value })} />
      </Ligne>

      <div style={{ marginTop: 16 }}>
        <button className="btn btn--gold" onClick={enregistrer}>Enregistrer</button>
        {msg && <span style={{ marginLeft: 12 }}>{msg}</span>}
        {error && <span style={{ marginLeft: 12, color: "#c0392b" }}>{error}</span>}
      </div>
    </div>
  );
}

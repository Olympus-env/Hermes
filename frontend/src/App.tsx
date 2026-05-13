import { useState } from "react";
import { StatusBar } from "./components/StatusBar";
import { Tabs, type Onglet } from "./components/Tabs";
import { Veille } from "./views/Veille";
import { Reponses } from "./views/Reponses";

export default function App() {
  const [actif, setActif] = useState("veille");

  const onglets: Onglet[] = [
    { id: "veille", label: "Veille (ARGOS / KRINOS)", contenu: <Veille /> },
    { id: "reponses", label: "Réponses (HERMION)", contenu: <Reponses /> },
  ];

  return (
    <div className="flex flex-col h-screen bg-hermes-bg">
      <header className="flex items-center justify-between px-6 py-3 border-b border-slate-800 bg-hermes-panel">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-semibold tracking-wide text-hermes-accent">
            HERMES
          </h1>
          <span className="text-xs text-slate-500">
            Veille & réponse aux appels d'offre — 100 % local
          </span>
        </div>
        <StatusBar />
      </header>
      <main className="flex-1 min-h-0">
        <Tabs onglets={onglets} actif={actif} surChangement={setActif} />
      </main>
      <footer className="px-6 py-2 text-[10px] text-slate-600 border-t border-slate-800">
        ARGOS · KRINOS · HERMION · MNEMOSYNE · PYTHIA
      </footer>
    </div>
  );
}

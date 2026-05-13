import { type ReactNode } from "react";

export type Onglet = {
  id: string;
  label: string;
  contenu: ReactNode;
};

type Props = {
  onglets: Onglet[];
  actif: string;
  surChangement: (id: string) => void;
};

export function Tabs({ onglets, actif, surChangement }: Props) {
  const courant = onglets.find((o) => o.id === actif) ?? onglets[0];
  return (
    <div className="flex flex-col h-full">
      <nav className="flex border-b border-slate-800">
        {onglets.map((o) => {
          const estActif = o.id === actif;
          return (
            <button
              key={o.id}
              onClick={() => surChangement(o.id)}
              className={[
                "px-4 py-2 text-sm transition-colors border-b-2",
                estActif
                  ? "text-hermes-accent border-hermes-accent"
                  : "text-slate-400 border-transparent hover:text-slate-200",
              ].join(" ")}
            >
              {o.label}
            </button>
          );
        })}
      </nav>
      <div className="flex-1 overflow-auto">{courant.contenu}</div>
    </div>
  );
}

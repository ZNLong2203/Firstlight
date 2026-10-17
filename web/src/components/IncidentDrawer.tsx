import { useEffect } from "react";

import { target } from "../format";
import type { Incident } from "../types";
import { IncidentPanel } from "./IncidentPanel";

interface Props {
  incident: Incident;
  offsetHours: number;
  demoCode: string;
  onSelect: (id: string) => void;
  onClose: () => void;
}

/** An incident that covers more than one pond: a gateway, a farm, or the whole estate. */
export function IncidentDrawer({ incident, offsetHours, demoCode, onSelect, onClose }: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      className="fixed inset-y-0 right-0 z-30 flex w-full flex-col overflow-y-auto border-l border-night-700 bg-night-900 shadow-2xl shadow-black/60 sm:w-[520px]"
      aria-label={`Incident ${incident._id}`}
    >
      <header className="flex items-start justify-between gap-4 border-b border-night-700 px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold text-white">{target(incident)}</h2>
          <p className="mt-1 font-mono text-xs text-slate-400">{incident._id}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1.5 text-slate-400 transition hover:bg-night-800 hover:text-white"
          aria-label="Close"
        >
          <svg viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
          </svg>
        </button>
      </header>
      <IncidentPanel incident={incident} offsetHours={offsetHours} demoCode={demoCode} />
      <section className="px-5 py-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Ponds</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          {incident.ponds.map((pond) => (
            <button
              key={pond}
              type="button"
              onClick={() => onSelect(pond)}
              className="rounded-md bg-night-800 px-2.5 py-1 font-mono text-xs text-slate-200 ring-1 ring-night-700 transition hover:ring-slate-500"
            >
              {pond}
            </button>
          ))}
        </div>
      </section>
    </aside>
  );
}

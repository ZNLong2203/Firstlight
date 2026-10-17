import { useEffect } from "react";

import { target } from "../format";
import type { Incident } from "../types";
import { IncidentPanel } from "./IncidentPanel";
import { CloseButton } from "./PondDrawer";

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
      className="fixed inset-y-0 right-0 z-30 flex w-full flex-col overflow-y-auto border-l border-ink-700 bg-ink-900 shadow-[-24px_0_48px_rgba(0,0,0,0.45)] sm:w-[548px]"
      aria-label={`Incident ${incident._id}`}
    >
      <header className="flex items-start justify-between gap-4 border-b border-ink-700 px-6 pb-5 pt-6">
        <div>
          <p className="font-mono text-[12px] text-faint">{incident._id}</p>
          <h2 className="mt-1.5 font-display text-[30px] leading-tight text-paper">{target(incident)}</h2>
        </div>
        <CloseButton onClose={onClose} />
      </header>
      <IncidentPanel incident={incident} offsetHours={offsetHours} demoCode={demoCode} />
      <section className="px-6 py-5">
        <h3 className="font-display text-[16px] text-paper">The ponds it covers</h3>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {incident.ponds.map((pond) => (
            <button
              key={pond}
              type="button"
              onClick={() => onSelect(pond)}
              className="rounded-[3px] border border-ink-600 px-2 py-1 font-mono text-[12px] text-paper-2 transition-colors hover:border-paper/40 hover:text-paper"
            >
              {pond}
            </button>
          ))}
        </div>
      </section>
    </aside>
  );
}

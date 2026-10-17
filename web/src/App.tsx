import { useCallback, useEffect, useMemo, useState } from "react";

import { Attention } from "./components/Attention";
import { ChaosPanel } from "./components/ChaosPanel";
import { countBy, FleetMap } from "./components/FleetMap";
import { IncidentDrawer } from "./components/IncidentDrawer";
import { PondDrawer } from "./components/PondDrawer";
import { TopBar } from "./components/TopBar";
import { useDemoCode } from "./demo";
import { effectiveStatus } from "./format";
import { LEGEND } from "./status";
import type { AiStats, Incident, Meta } from "./types";
import { useLivePonds, useNow } from "./useLive";

const RECENT_MS = 60 * 60_000; // a pond's drawer keeps showing its last incident for an hour

/** The incident a pond's drawer should show: the open one, or the latest that closed within the hour. */
function incidentFor(pond: string, incidents: Map<string, Incident>, now: number): Incident | undefined {
  let best: Incident | undefined;
  for (const incident of incidents.values()) {
    if (!incident.ponds.includes(pond)) continue;
    if (incident.open) return incident;
    const closed = Date.parse(incident.closed_at ?? "");
    if (now - closed < RECENT_MS && (!best || closed > Date.parse(best.closed_at ?? ""))) best = incident;
  }
  return best;
}

/** The selected pond lives in the URL hash, so an alert can link straight to it. */
function useSelectedPond(): [string | null, (id: string | null) => void] {
  const read = () => decodeURIComponent(window.location.hash.slice(1)) || null;
  const [selected, setSelected] = useState<string | null>(read);
  useEffect(() => {
    const onHash = () => setSelected(read());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const select = useCallback((id: string | null) => {
    setSelected(id);
    window.history.replaceState(null, "", id ? `#${encodeURIComponent(id)}` : window.location.pathname);
  }, []);
  return [selected, select];
}

/** How the AI investigator scores so far; refreshed every 30 s. */
function useAiStats(): AiStats | null {
  const [stats, setStats] = useState<AiStats | null>(null);
  useEffect(() => {
    const load = () =>
      fetch("/v1/incidents/ai/stats")
        .then((r) => (r.ok ? (r.json() as Promise<AiStats>) : null))
        .then(setStats)
        .catch(() => undefined);
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, []);
  return stats;
}

function useMeta(): Meta | null {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    fetch("/v1/meta")
      .then((r) => (r.ok ? (r.json() as Promise<Meta>) : null))
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);
  return meta;
}

export function App() {
  const { ponds, incidents, link } = useLivePonds();
  const now = useNow();
  const meta = useMeta();
  const aiStats = useAiStats();
  const [demoCode, setDemoCode] = useDemoCode();
  const [selected, select] = useSelectedPond();
  const list = useMemo(() => [...ponds.values()], [ponds]);
  const counts = countBy(list.map((p) => effectiveStatus(p, now)));
  const offset = meta?.farm_clock_offset_hours ?? null;
  const open = selected ? ponds.get(selected) : undefined;
  const openIncident = selected?.startsWith("INC-") ? incidents.get(selected) : undefined;
  const drawer = Boolean(open || openIncident);
  const toggle = useCallback((id: string) => select(id === selected ? null : id), [select, selected]);
  const close = useCallback(() => select(null), [select]);

  useEffect(() => {
    document.title = counts.alert ? `(${counts.alert}) Firstlight` : "Firstlight";
  }, [counts.alert]);

  return (
    <div className="min-h-dvh">
      <TopBar now={now} offsetHours={offset} counts={counts} link={link} />
      {link === "reconnecting" && (
        <div className="bg-amber-400/15 px-4 py-2 text-center text-sm text-amber-200" role="alert">
          Connection to the farms lost. Reconnecting; the values below may be out of date.
        </div>
      )}
      <main
        className={`mx-auto max-w-[1600px] space-y-8 px-4 py-6 transition-opacity sm:px-6 ${
          drawer ? "xl:pr-[544px]" : ""
        } ${link === "live" ? "" : "opacity-60"}`}
      >
        {link === "connecting" && list.length === 0 ? (
          <p className="py-20 text-center text-sm text-slate-500">Connecting to the farms…</p>
        ) : list.length === 0 ? (
          <p className="py-20 text-center text-sm text-slate-500">Waiting for the first gateway to report.</p>
        ) : (
          <>
            <section aria-labelledby="attention-title">
              <h2 id="attention-title" className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                Needs attention
              </h2>
              <Attention
                ponds={ponds}
                incidents={incidents}
                now={now}
                offsetHours={offset ?? 0}
                selected={selected}
                onSelect={toggle}
                aiStats={aiStats}
              />
            </section>
            <section aria-labelledby="fleet-title">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h2 id="fleet-title" className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                  All ponds · dissolved oxygen, mg/L
                </h2>
                <Legend />
              </div>
              <FleetMap ponds={list} now={now} selected={selected} onSelect={toggle} />
            </section>
          </>
        )}
      </main>
      {open && (
        <PondDrawer
          pond={open}
          incident={incidentFor(open._id, incidents, now)}
          now={now}
          offsetHours={offset ?? 0}
          demoCode={demoCode}
          onClose={close}
        />
      )}
      {openIncident && (
        <IncidentDrawer
          incident={openIncident}
          offsetHours={offset ?? 0}
          demoCode={demoCode}
          onSelect={select}
          onClose={close}
        />
      )}
      <ChaosPanel ponds={list} selected={selected} offsetHours={offset ?? 0} demoCode={demoCode} onDemoCode={setDemoCode} />
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
      {LEGEND.map(([swatch, label]) => (
        <li key={label} className="flex items-center gap-1.5">
          <span className={`size-2.5 rounded-sm ${swatch}`} />
          {label}
        </li>
      ))}
    </ul>
  );
}

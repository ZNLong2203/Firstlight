import { useCallback, useEffect, useMemo, useState } from "react";

import { ChaosPanel } from "./components/ChaosPanel";
import { IncidentDrawer } from "./components/IncidentDrawer";
import { IncidentsView } from "./components/IncidentsView";
import { Masthead } from "./components/Masthead";
import { NightView } from "./components/NightView";
import { PondDrawer } from "./components/PondDrawer";
import { PondsView } from "./components/PondsView";
import { useDemoCode } from "./demo";
import { effectiveStatus } from "./format";
import type { AiStats, Incident, Meta, Night, Report, Status } from "./types";
import { useLivePonds, useNow } from "./useLive";
import { useView } from "./view";

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
    const url = window.location.pathname + window.location.search;
    window.history.replaceState(null, "", id ? `${url}#${encodeURIComponent(id)}` : url);
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

/** The latest dawn report; refreshed every five minutes, and at once after a demo writes one. */
function useDawnReport(): [{ estate: Report | null; farms: Report[] }, () => void] {
  const [report, setReport] = useState<{ estate: Report | null; farms: Report[] }>({ estate: null, farms: [] });
  const load = useCallback(() => {
    fetch("/v1/reports/latest")
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => body && setReport(body as { estate: Report | null; farms: Report[] }))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    load();
    const timer = setInterval(load, 5 * 60_000);
    return () => clearInterval(timer);
  }, [load]);
  return [report, load];
}

/** The estate's oxygen through the night; the API recomputes it once a minute. */
function useNight(): Night | null {
  const [night, setNight] = useState<Night | null>(null);
  useEffect(() => {
    const load = () =>
      fetch("/v1/night")
        .then((r) => (r.ok ? (r.json() as Promise<Night>) : null))
        .then((body) => body && setNight(body))
        .catch(() => undefined);
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);
  return night;
}

function countBy(statuses: Status[]): Record<Status, number> {
  const counts: Record<Status, number> = { ok: 0, watch: 0, alert: 0, sensor: 0, blind: 0 };
  for (const status of statuses) counts[status] += 1;
  return counts;
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
  const night = useNight();
  const [dawn, reloadDawn] = useDawnReport();
  const [demoCode, setDemoCode] = useDemoCode();
  const [selected, select] = useSelectedPond();
  const [view, setView] = useView();
  const list = useMemo(() => [...ponds.values()], [ponds]);
  const counts = countBy(list.map((p) => effectiveStatus(p, now)));
  const latest = list.reduce<number | null>((newest, p) => {
    const t = p.last ? Date.parse(p.last.ts) : null;
    return t !== null && (newest === null || t > newest) ? t : newest;
  }, null);
  const offset = meta?.farm_clock_offset_hours ?? null;
  const open = selected ? ponds.get(selected) : undefined;
  const openIncident = selected?.startsWith("INC-") ? incidents.get(selected) : undefined;
  const drawer = Boolean(open || openIncident);
  const toggle = useCallback((id: string) => select(id === selected ? null : id), [select, selected]);
  const close = useCallback(() => select(null), [select]);
  const incidentList = useMemo(() => [...incidents.values()], [incidents]);
  const openIncidents = incidentList.filter((i) => i.open).length;

  useEffect(() => {
    document.title = counts.alert ? `(${counts.alert}) Firstlight` : "Firstlight";
  }, [counts.alert]);

  return (
    <div className="min-h-dvh">
      <Masthead
        now={now}
        offsetHours={offset}
        counts={counts}
        total={list.length}
        latest={latest}
        link={link}
        night={night}
        openIncidents={openIncidents}
        view={view}
        onView={setView}
        inset={drawer}
      />
      {link === "reconnecting" && (
        <div className="border-b border-ochre/30 bg-ochre/10 px-4 py-2 text-center text-[13px] text-ochre" role="alert">
          The link to the farms dropped. Reconnecting; what you see may be out of date.
        </div>
      )}
      <main
        className={`mx-auto max-w-[1600px] px-4 pb-24 pt-6 transition-opacity sm:px-8 ${drawer ? "xl:pr-[564px]" : ""} ${
          link === "live" ? "" : "opacity-60"
        }`}
      >
        {link === "connecting" && list.length === 0 ? (
          <p className="py-24 text-center font-display text-[20px] italic text-mute">Reaching the farms…</p>
        ) : list.length === 0 ? (
          <p className="py-24 text-center font-display text-[20px] italic text-mute">Waiting for the first gateway to report.</p>
        ) : view === "incidents" ? (
          <IncidentsView ponds={ponds} incidents={incidents} offsetHours={offset ?? 0} aiStats={aiStats} selected={selected} onSelect={toggle} />
        ) : view === "night" ? (
          <NightView
            night={night}
            incidents={incidentList}
            now={now}
            offsetHours={offset ?? 0}
            total={list.length}
            aiStats={aiStats}
            dawn={dawn}
            onSelect={toggle}
          />
        ) : (
          <PondsView ponds={ponds} incidents={incidents} now={now} offsetHours={offset ?? 0} selected={selected} onSelect={toggle} />
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
      <ChaosPanel
        ponds={list}
        selected={selected}
        offsetHours={offset ?? 0}
        demoCode={demoCode}
        onDemoCode={setDemoCode}
        onReport={reloadDawn}
      />
    </div>
  );
}

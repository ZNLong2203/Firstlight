import { lazy, Suspense, useEffect, useState } from "react";

import { ago, effectiveStatus, perHour, reasons } from "../format";
import { BADGE, STATUS_LABEL } from "../status";
import { PROVINCES, type HistoryPoint, type Incident, type PondDetail, type PondState } from "../types";
import { IncidentPanel } from "./IncidentPanel";

// ECharts is most of the bundle and only needed once a pond is opened.
const DoChart = lazy(() => import("./DoChart").then((m) => ({ default: m.DoChart })));

const WINDOW_MS = 2 * 3_600_000;

interface Props {
  pond: PondState;
  incident?: Incident;
  now: number;
  offsetHours: number;
  demoCode: string;
  onClose: () => void;
}

export function PondDrawer({ pond, incident, now, offsetHours, demoCode, onClose }: Props) {
  const [detail, setDetail] = useState<PondDetail | null>(null);
  const [history, setHistory] = useState<HistoryPoint[] | null>(null);
  const [failed, setFailed] = useState(false);
  const status = effectiveStatus(pond, now);

  useEffect(() => {
    const abort = new AbortController();
    setDetail(null);
    setHistory(null);
    setFailed(false);
    const get = <T,>(path: string) =>
      fetch(path, { signal: abort.signal }).then((r) => {
        if (!r.ok) throw new Error(`${path}: ${r.status}`);
        return r.json() as Promise<T>;
      });
    Promise.all([get<PondDetail>(`/v1/ponds/${pond._id}`), get<HistoryPoint[]>(`/v1/ponds/${pond._id}/history?minutes=120`)])
      .then(([d, h]) => {
        setDetail(d);
        setHistory(h);
      })
      .catch((error: unknown) => {
        if (!abort.signal.aborted) {
          console.error(error);
          setFailed(true);
        }
      });
    return () => abort.abort();
  }, [pond._id]);

  // New readings arrive with the live stream, so the chart grows without polling.
  const last = pond.last;
  useEffect(() => {
    if (!last) return;
    setHistory((points) => {
      if (!points || (points.length && Date.parse(points.at(-1)!.ts) >= Date.parse(last.ts))) return points;
      const cutoff = Date.parse(last.ts) - WINDOW_MS;
      const point = { ts: last.ts, do: last.do, temp: last.temp, ph: last.ph, running: last.aerators_running };
      return [...points.filter((p) => Date.parse(p.ts) >= cutoff), point];
    });
  }, [last]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const aerators = detail?.devices.filter((d) => d.type === "aerator") ?? [];
  const probe = detail?.devices.find((d) => d.type === "do_probe");
  const minutes = pond.forecast?.minutes_to_hypoxia;
  const seen = last ? (now - Date.parse(last.ts)) / 1000 : null;

  return (
    <aside
      className="fixed inset-y-0 right-0 z-30 flex w-full flex-col overflow-y-auto border-l border-night-700 bg-night-900 shadow-2xl shadow-black/60 sm:w-[520px]"
      aria-label={`Pond ${pond._id}`}
    >
      <header className="flex items-start justify-between gap-4 border-b border-night-700 px-5 py-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="font-mono text-xl font-semibold text-white">{pond._id}</h2>
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${BADGE[status]}`}>
              {STATUS_LABEL[status]}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            {PROVINCES[pond.farm.split("-")[0]]} · farm {pond.farm} · {pond.gateway}
            {pond.area_m2 ? ` · ${pond.area_m2.toLocaleString("en")} m²` : ""}
          </p>
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

      <dl className="grid grid-cols-4 divide-x divide-night-700 border-b border-night-700">
        <Stat label="DO now" value={last && status !== "blind" ? last.do.toFixed(2) : "–"} unit="mg/L" />
        <Stat
          label="To 3 mg/L"
          value={status === "blind" ? "–" : minutes == null ? "safe" : minutes <= 0 ? "now" : String(Math.round(minutes))}
          unit={minutes != null && minutes > 0 && status !== "blind" ? "min" : ""}
          tone={minutes != null && minutes < 30 ? "text-red-300" : minutes != null && minutes < 60 ? "text-amber-200" : ""}
        />
        <Stat label="Trend" value={status === "blind" ? "–" : perHour(pond.forecast?.slope_per_min)} unit="mg/L/h" />
        <Stat label="Last data" value={seen == null ? "–" : ago(seen)} unit="ago" tone={seen != null && seen > 60 ? "text-slate-400" : ""} />
      </dl>

      {incident && <IncidentPanel incident={incident} offsetHours={offsetHours} demoCode={demoCode} />}

      {status !== "ok" && !incident?.open && (
        <ul className="flex flex-wrap gap-2 border-b border-night-700 px-5 py-3 text-xs">
          {reasons(pond, status, now).map((reason) => (
            <li key={reason} className="rounded-full bg-night-800 px-2.5 py-1 text-slate-200 ring-1 ring-night-700">
              {reason}
            </li>
          ))}
        </ul>
      )}

      <section className="border-b border-night-700 px-3 pt-3">
        <div className="flex items-center justify-between px-2 text-[11px] text-slate-500">
          <span>Last 2 hours · farm time</span>
          <span className="flex items-center gap-3">
            <Key color="bg-sky-300" label="DO" />
            <Key color="bg-orange-400" label="Forecast" />
            <Key color="bg-emerald-400" label="Aerators turning" />
          </span>
        </div>
        {history ? (
          <Suspense fallback={<ChartPlaceholder text="Loading…" />}>
            <DoChart history={history} pond={pond} now={now} offsetHours={offsetHours} />
          </Suspense>
        ) : (
          <ChartPlaceholder text={failed ? "Could not load this pond's history." : "Loading…"} />
        )}
      </section>

      {last && (
        <dl className="grid grid-cols-3 divide-x divide-night-700 border-b border-night-700">
          <Stat label="Water" value={last.temp.toFixed(1)} unit="°C" small />
          <Stat label="pH" value={last.ph.toFixed(2)} unit="" small />
          <Stat label="Probe quality" value={last.probe_q.toFixed(2)} unit="" small />
        </dl>
      )}

      <section className="px-5 py-4">
        <h3 className="flex items-baseline justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
          Aerators
          {last && (
            <span className="font-mono text-[11px] normal-case tracking-normal text-slate-500">
              {last.aerators_running} of {last.aerators_on} turning
            </span>
          )}
        </h3>
        <ul className="mt-2 space-y-1.5">
          {aerators.map((device) => (
            <li key={device._id} className="flex items-center justify-between rounded-lg bg-night-800 px-3 py-2 text-sm">
              <span className="font-mono text-xs text-slate-200">{device._id}</span>
              <span className="flex items-center gap-2 text-xs text-slate-400">
                {device.aerator?.kw} kW
                {device.aerator?.standby && (
                  <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-sky-300">
                    standby
                  </span>
                )}
              </span>
            </li>
          ))}
          {!detail && !failed && <li className="text-xs text-slate-500">Loading devices…</li>}
        </ul>
        {probe && (
          <p className="mt-3 text-xs text-slate-500">
            Probe <span className="font-mono text-slate-300">{probe._id}</span>
            {probe.probe?.model ? ` · ${probe.probe.model}` : ""}
          </p>
        )}
      </section>
    </aside>
  );
}

function Stat({ label, value, unit, tone = "", small = false }: { label: string; value: string; unit: string; tone?: string; small?: boolean }) {
  return (
    <div className="px-4 py-3">
      <dt className="text-[10px] font-medium uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className={`mt-0.5 font-mono font-semibold tabular-nums text-white ${small ? "text-base" : "text-xl"} ${tone}`}>
        {value}
        {unit && <span className="ml-1 font-sans text-[11px] font-normal text-slate-500">{unit}</span>}
      </dd>
    </div>
  );
}

function ChartPlaceholder({ text }: { text: string }) {
  return <div className="grid h-72 place-items-center text-sm text-slate-500">{text}</div>;
}

function Key({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`h-0.5 w-3 rounded ${color}`} />
      {label}
    </span>
  );
}

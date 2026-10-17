import { lazy, Suspense, useEffect, useState } from "react";

import { ago, clockName, effectiveStatus, perHour, reasons, vnd } from "../format";
import { STATUS_LABEL, STATUS_TEXT } from "../status";
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
  const trusted = status !== "sensor";

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
  const crop = detail?.crop;

  return (
    <aside
      className="fixed inset-y-0 right-0 z-30 flex w-full flex-col overflow-y-auto border-l border-ink-700 bg-ink-900 shadow-[-24px_0_48px_rgba(0,0,0,0.45)] sm:w-[548px]"
      aria-label={`Pond ${pond._id}`}
    >
      <header className="border-b border-ink-700 px-6 pb-5 pt-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[12px] text-mute">
              {PROVINCES[pond.farm.split("-")[0]]} · farm {pond.farm} · gateway {pond.gateway}
              {pond.area_m2 ? ` · ${pond.area_m2.toLocaleString("en")} m²` : ""}
            </p>
            <h2 className="mt-1.5 font-display text-[36px] leading-none text-paper">{pond._id}</h2>
            <p className={`mt-2 text-[13px] ${STATUS_TEXT[status]}`}>
              {STATUS_LABEL[status]}
              {status !== "ok" && !incident?.open && (
                <span className="text-paper-2"> · {reasons(pond, status, now).join(" · ")}</span>
              )}
            </p>
          </div>
          <CloseButton onClose={onClose} />
        </div>
        {crop && (
          <p
            className="mt-4 border-l-2 border-dawn/60 pl-3 text-[12.5px] leading-relaxed text-dawn-soft"
            title="Team estimate from published Mekong Delta figures: stocking × survival × weight × the farm-gate price of 16/10/2026; while the shrimp are too small to sell, the seed and feed spent on them"
          >
            Day {crop.doc} of the crop: {crop.abw_g} g shrimp, {crop.count_per_kg} to the kilo,{" "}
            {(crop.biomass_kg / 1000).toFixed(1)} t in the pond. Worth about{" "}
            <span className="font-medium text-dawn">{vnd(crop.value_vnd)}</span>{" "}
            {crop.basis === "market" ? "at today's farm-gate price." : "in seed and feed so far; too small to sell yet."}
          </p>
        )}
      </header>

      <dl className="grid grid-cols-4 divide-x divide-ink-700 border-b border-ink-700">
        {/* A probe known to be wrong: its oxygen is shown for what it is, and nothing is computed from it. */}
        <Stat
          label="Oxygen now"
          value={last && status !== "blind" ? last.do.toFixed(2) : "–"}
          unit={trusted ? "mg/L" : "not trusted"}
          tone={trusted ? "" : "text-mute line-through"}
        />
        <Stat
          label="Until 3 mg/L"
          value={!trusted || status === "blind" ? "–" : minutes == null ? "safe" : minutes <= 0 ? "now" : String(Math.round(minutes))}
          unit={trusted && minutes != null && minutes > 0 && status !== "blind" ? "min" : ""}
          tone={trusted && minutes != null && minutes < 30 ? "text-rust" : trusted && minutes != null && minutes < 60 ? "text-ochre" : ""}
        />
        <Stat label="Trend, per hour" value={!trusted || status === "blind" ? "–" : perHour(pond.forecast?.slope_per_min)} unit="" />
        <Stat label="Last reading" value={seen == null ? "–" : ago(seen)} unit="ago" tone={seen != null && seen > 60 ? "text-mute" : ""} />
      </dl>

      {incident && <IncidentPanel incident={incident} offsetHours={offsetHours} demoCode={demoCode} />}

      <section className="border-b border-ink-700 px-4 pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2 px-2 text-[11.5px] text-mute">
          <span className="font-display text-[15px] text-paper">The last two hours</span>
          <span className="flex items-center gap-3">
            <Key color="bg-paper" label="oxygen" />
            <Key color="bg-dawn" label="forecast" dashed />
            <Key color="bg-sea" label="aerators turning" />
            <span>{clockName(offsetHours)}</span>
          </span>
        </div>
        {history ? (
          <Suspense fallback={<ChartPlaceholder text="Drawing the chart…" />}>
            <DoChart history={history} pond={pond} now={now} offsetHours={offsetHours} trusted={trusted} />
          </Suspense>
        ) : (
          <ChartPlaceholder text={failed ? "Could not load this pond's history." : "Drawing the chart…"} />
        )}
      </section>

      {last && (
        <dl className="grid grid-cols-3 divide-x divide-ink-700 border-b border-ink-700">
          <Stat label="Water" value={last.temp.toFixed(1)} unit="°C" small />
          <Stat label="pH" value={last.ph.toFixed(2)} unit="" small />
          <Stat label="Probe signal" value={last.probe_q.toFixed(2)} unit="of 1" small />
        </dl>
      )}

      <section className="px-6 py-5">
        <div className="flex items-baseline justify-between">
          <h3 className="font-display text-[17px] text-paper">Aerators</h3>
          {last && (
            <span className="text-[12px] text-mute">
              {last.aerators_running} of {last.aerators_on} switched on are turning
            </span>
          )}
        </div>
        <ul className="mt-2 divide-y divide-ink-700">
          {aerators.map((device) => {
            const reading = last?.aer?.find((a) => a.id === device._id);
            const repair = pond.repair_tickets?.some((t) => t.device === device._id);
            const state = !reading ? "unknown" : reading.amp >= 0.5 ? "turning" : reading.on ? "stopped" : "off";
            const text =
              state === "turning"
                ? `${reading!.amp.toFixed(1)} A`
                : state === "stopped"
                  ? repair
                    ? "stopped · repair ticket open"
                    : "on, but drawing 0 A"
                  : state === "off"
                    ? "off"
                    : "";
            return (
              <li key={device._id} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex items-center gap-3">
                  <Wheel state={state} />
                  <span className="font-mono text-[12.5px] text-paper">{device._id}</span>
                  {device.aerator?.standby && <span className="text-[12px] italic text-mute">standby</span>}
                </span>
                <span className="flex items-baseline gap-4 text-[12.5px]">
                  <span className="text-mute">{device.aerator?.kw} kW</span>
                  <span
                    className={`min-w-[4.5rem] text-right font-mono ${
                      state === "turning" ? "text-sea" : state === "stopped" ? "text-rust" : "text-mute"
                    }`}
                  >
                    {text}
                  </span>
                </span>
              </li>
            );
          })}
          {!detail && !failed && <li className="py-2.5 text-[12.5px] text-mute">Loading the devices…</li>}
        </ul>
        {probe && (
          <p className="mt-4 text-[12px] text-mute">
            Oxygen probe <span className="font-mono text-paper-2">{probe._id}</span>
            {probe.probe?.model ? `, ${probe.probe.model}` : ""}
          </p>
        )}
      </section>
    </aside>
  );
}

export function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      className="-mr-2 rounded-md p-2 text-mute transition-colors hover:bg-ink-800 hover:text-paper"
      aria-label="Close"
    >
      <svg viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
      </svg>
    </button>
  );
}

/** A paddlewheel aerator seen from above. */
function Wheel({ state }: { state: "turning" | "stopped" | "off" | "unknown" }) {
  const color = state === "turning" ? "#86bfa9" : state === "stopped" ? "#e0714e" : "#5f655e";
  return (
    <svg viewBox="0 0 20 20" className="size-5 shrink-0" aria-hidden="true">
      <circle cx="10" cy="10" r="2.2" fill={color} />
      {[0, 45, 90, 135].map((angle) => (
        <rect key={angle} x="9.2" y="2" width="1.6" height="16" rx="0.8" fill={color} opacity={state === "off" ? 0.5 : 0.85} transform={`rotate(${angle} 10 10)`} />
      ))}
      {state === "stopped" && <path d="M4 16 16 4" stroke="#0f1718" strokeWidth="3" />}
      {state === "stopped" && <path d="M4 16 16 4" stroke="#e0714e" strokeWidth="1.4" />}
    </svg>
  );
}

function Stat({ label, value, unit, tone = "", small = false }: { label: string; value: string; unit: string; tone?: string; small?: boolean }) {
  return (
    <div className="px-5 py-4">
      <dt className="text-[11.5px] text-mute">{label}</dt>
      <dd className={`mt-1 whitespace-nowrap numeral leading-none text-paper ${small ? "text-[20px]" : "text-[27px]"} ${tone}`}>
        {value}
        {unit && <span className="ml-1 font-sans text-[11px] text-mute no-underline">{unit}</span>}
      </dd>
    </div>
  );
}

function ChartPlaceholder({ text }: { text: string }) {
  return <div className="grid h-72 place-items-center font-display text-[14px] italic text-mute">{text}</div>;
}

function Key({ color, label, dashed = false }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-[2px] w-3.5 ${dashed ? "bg-[length:5px_2px] bg-repeat-x" : ""} ${color}`} />
      {label}
    </span>
  );
}

import { CAUSE_LABEL, clockTime, describe, effectiveStatus, headline, perHour, reasons, seconds, target, urgency } from "../format";
import { BADGE, CARD, INCIDENT_BADGE, INCIDENT_CARD, INCIDENT_LABEL, INCIDENT_ORDER, STATUS_LABEL } from "../status";
import { PROVINCES, type Incident, type PondState } from "../types";

const SHOWN = 8;

interface Props {
  ponds: Map<string, PondState>;
  incidents: Map<string, Incident>;
  now: number;
  offsetHours: number;
  selected: string | null;
  onSelect: (id: string) => void;
}

/** Open incidents first, then ponds that need watching on their own, then the proof from tonight. */
export function Attention({ ponds, incidents, now, offsetHours, selected, onSelect }: Props) {
  const all = [...incidents.values()];
  const open = all
    .filter((i) => i.open)
    .sort((a, b) => INCIDENT_ORDER.indexOf(a.status) - INCIDENT_ORDER.indexOf(b.status) || b.opened_at.localeCompare(a.opened_at));
  const covered = new Set(open.flatMap((i) => i.ponds));
  const loose = [...ponds.values()]
    .map((pond) => ({ pond, status: effectiveStatus(pond, now) }))
    .filter(({ pond, status }) => status !== "ok" && !covered.has(pond._id))
    .sort((a, b) => urgency(a.pond, a.status) - urgency(b.pond, b.status));
  const closed = all
    .filter((i) => !i.open)
    .sort((a, b) => (b.closed_at ?? "").localeCompare(a.closed_at ?? ""))
    .slice(0, 6);
  const cards = open.length + loose.length;

  return (
    <div className="space-y-5">
      {cards === 0 ? (
        <AllQuiet total={ponds.size} />
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-3">
          {open.map((incident) => (
            <IncidentCard
              key={incident._id}
              incident={incident}
              pond={incident.pond ? ponds.get(incident.pond) : undefined}
              offsetHours={offsetHours}
              selected={selected === (incident.pond ?? incident._id)}
              onSelect={onSelect}
            />
          ))}
          {loose.slice(0, Math.max(0, SHOWN - open.length)).map(({ pond, status }) => (
            <button
              key={pond._id}
              type="button"
              onClick={() => onSelect(pond._id)}
              className={`rounded-xl border p-3 text-left transition hover:brightness-125 ${CARD[status]} ${
                pond._id === selected ? "outline-2 outline-offset-2 outline-sky-300" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${BADGE[status]}`}>
                  {STATUS_LABEL[status]}
                </span>
                <span className="font-mono text-xs text-slate-300">{pond._id}</span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-3xl font-semibold tabular-nums text-white">
                  {status === "blind" || !pond.last ? "–" : pond.last.do.toFixed(1)}
                </span>
                <span className="text-xs text-slate-400">mg/L</span>
                {status !== "blind" && pond.forecast && (
                  <span className="ml-auto font-mono text-xs text-slate-400">{perHour(pond.forecast.slope_per_min)}/h</span>
                )}
              </div>
              <ul className="mt-1.5 space-y-0.5 text-xs text-slate-200">
                {reasons(pond, status, now).map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              <p className="mt-2 text-[11px] text-slate-500">
                {PROVINCES[pond.farm.split("-")[0]]} · {pond.gateway}
              </p>
            </button>
          ))}
        </div>
      )}
      {loose.length > SHOWN - open.length && (
        <p className="text-xs text-slate-500">and {loose.length - Math.max(0, SHOWN - open.length)} more on the map below</p>
      )}
      {closed.length > 0 && <Closed incidents={closed} offsetHours={offsetHours} onSelect={onSelect} />}
    </div>
  );
}

function IncidentCard({
  incident,
  pond,
  offsetHours,
  selected,
  onSelect,
}: {
  incident: Incident;
  pond?: PondState;
  offsetHours: number;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const step = headline(incident);
  return (
    <button
      type="button"
      onClick={() => onSelect(incident.pond ?? incident._id)}
      className={`rounded-xl border p-3 text-left transition hover:brightness-125 ${INCIDENT_CARD[incident.status]} ${
        selected ? "outline-2 outline-offset-2 outline-sky-300" : ""
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${INCIDENT_BADGE[incident.status]}`}>
          {INCIDENT_LABEL[incident.status]}
        </span>
        <span className="font-mono text-xs text-slate-400">{incident._id}</span>
      </div>
      <div className="mt-2 text-sm font-semibold text-white">{target(incident)}</div>
      <div className="text-xs text-slate-300">
        {incident.diagnosis ? (
          <>
            {CAUSE_LABEL[incident.diagnosis.cause] ?? incident.diagnosis.cause}
            <span className="text-slate-500"> · {Math.round(incident.diagnosis.confidence * 100)}% sure</span>
          </>
        ) : (
          "Looking for the cause…"
        )}
      </div>
      {pond?.last && (
        <div className="mt-2 flex items-baseline gap-2">
          <span className="font-mono text-2xl font-semibold tabular-nums text-white">{pond.last.do.toFixed(1)}</span>
          <span className="text-xs text-slate-400">mg/L</span>
          {pond.forecast && <span className="ml-auto font-mono text-xs text-slate-400">{perHour(pond.forecast.slope_per_min)}/h</span>}
        </div>
      )}
      {step && (
        <p className="mt-2 text-xs text-slate-200">
          <span className="mr-1.5 font-mono text-slate-500">{clockTime(step.t, offsetHours)}</span>
          {describe(step)}
        </p>
      )}
    </button>
  );
}

function Closed({
  incidents,
  offsetHours,
  onSelect,
}: {
  incidents: Incident[];
  offsetHours: number;
  onSelect: (id: string) => void;
}) {
  return (
    <div>
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Closed tonight · the proof</h3>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-2">
        {incidents.map((incident) => {
          const m = incident.metrics;
          return (
            <li key={incident._id}>
              <button
                type="button"
                onClick={() => onSelect(incident.pond ?? incident._id)}
                className="w-full rounded-lg border border-night-700 bg-night-900 px-3 py-2 text-left text-xs transition hover:border-slate-500"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={incident.status === "dismissed" ? "text-violet-300" : "text-emerald-300"}>
                    {incident.status === "dismissed" ? "False alarm stopped" : "Recovered"}
                  </span>
                  <span className="font-mono text-slate-500">
                    {incident._id} · {clockTime(incident.closed_at, offsetHours)}
                  </span>
                </div>
                <div className="mt-0.5 text-slate-200">
                  {CAUSE_LABEL[incident.diagnosis?.cause ?? "unknown"]} · {incident.pond ?? incident.gateway ?? incident.farm}
                </div>
                <div className="mt-0.5 text-slate-500">
                  {incident.status === "dismissed"
                    ? "nobody woken; cleaning ticket opened"
                    : m
                      ? `detected ${seconds(m.mttd_s)} · acted ${seconds(m.time_to_action_s)} · lowest ${m.min_do?.toFixed(1) ?? "–"} mg/L`
                      : ""}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function AllQuiet({ total }: { total: number }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3">
      <svg viewBox="0 0 24 24" className="size-5 shrink-0 text-emerald-300" fill="currentColor" aria-hidden="true">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
      </svg>
      <p className="text-sm text-emerald-100">
        All quiet. <span className="text-emerald-300/80">{total} of {total} ponds are safe.</span>
      </p>
    </div>
  );
}

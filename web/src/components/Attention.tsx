import { CAUSE_LABEL, clockTime, describe, effectiveStatus, headline, perHour, reasons, seconds, target, urgency, vnd } from "../format";
import { BADGE, CARD, INCIDENT_BADGE, INCIDENT_CARD, INCIDENT_LABEL, INCIDENT_ORDER, STATUS_LABEL } from "../status";
import { PROVINCES, type AiStats, type Incident, type PondState } from "../types";

const SHOWN = 8;

interface Props {
  ponds: Map<string, PondState>;
  incidents: Map<string, Incident>;
  now: number;
  offsetHours: number;
  selected: string | null;
  onSelect: (id: string) => void;
  aiStats?: AiStats | null;
}

/** Open incidents first, then ponds that need watching on their own, then the proof from the latest incidents. */
export function Attention({ ponds, incidents, now, offsetHours, selected, onSelect, aiStats }: Props) {
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
    .filter((i) => !i.open && i.diagnosis && i.diagnosis.cause !== "unknown") // proof needs a known cause
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
                <span
                  className={`font-mono text-3xl font-semibold tabular-nums ${
                    status === "sensor" ? "text-slate-500 line-through decoration-violet-400/70" : "text-white"
                  }`}
                >
                  {status === "blind" || !pond.last ? "–" : pond.last.do.toFixed(1)}
                </span>
                <span className="text-xs text-slate-400">{status === "sensor" ? "mg/L, probe not trusted" : "mg/L"}</span>
                {status !== "blind" && status !== "sensor" && pond.forecast && (
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
      {closed.length > 0 && <Closed incidents={closed} offsetHours={offsetHours} onSelect={onSelect} aiStats={aiStats} />}
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
      {incident.at_risk && (
        <div className="text-[11px] text-amber-200/90">≈ {vnd(incident.at_risk.value_vnd)} of shrimp at stake</div>
      )}
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
  aiStats,
}: {
  incidents: Incident[];
  offsetHours: number;
  onSelect: (id: string) => void;
  aiStats?: AiStats | null;
}) {
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Closed recently · the proof</h3>
        {aiStats && (aiStats.scored ?? 0) > 0 && (
          <p className="text-[11px] text-slate-400">
            Right by the ground truth: <span className="font-mono text-sky-300">AI {aiStats.ai_correct}/{aiStats.scored}</span>
            {" · "}
            <span className="font-mono text-emerald-300">rules {aiStats.rules_correct}/{aiStats.scored}</span>
          </p>
        )}
      </div>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-2">
        {incidents.map((incident) => {
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
                  {CAUSE_LABEL[incident.diagnosis?.cause ?? "unknown"]} · {where(incident)}
                </div>
                <div className="mt-0.5 text-slate-500">{proofLine(incident)}</div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** What the incident was about, in one word: the pond, the gateway, the farm or the whole estate. */
function where(incident: Incident): string {
  if (incident.scope === "pond") return incident.pond ?? incident.key;
  if (incident.scope === "gateway") return incident.gateway ?? incident.key;
  if (incident.scope === "farm") return `farm ${incident.farm ?? incident.key}`;
  return "the whole estate";
}

function proofLine(incident: Incident): string {
  const m = incident.metrics;
  if (incident.status === "dismissed") return "nobody woken; cleaning ticket opened";
  if (!m) return "";
  if (m.blind_s != null) {
    const recovered = m.coverage != null ? `${Math.round(m.coverage * 100)}% of readings recovered` : "data back";
    return `blind ${seconds(m.blind_s)} · ${recovered} · lowest ${m.min_do?.toFixed(1) ?? "–"} mg/L`;
  }
  const saved =
    incident.at_risk && (m.min_do ?? 0) >= 3 && ["aerator_failure", "power_outage"].includes(incident.diagnosis?.cause ?? "")
      ? ` · ≈ ${vnd(incident.at_risk.value_vnd)} protected`
      : "";
  return `detected ${seconds(m.mttd_s)} · acted ${seconds(m.time_to_action_s)} · lowest ${m.min_do?.toFixed(1) ?? "–"} mg/L${saved}`;
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

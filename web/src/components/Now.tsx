import { CAUSE_LABEL, clockTime, describe, effectiveStatus, headline, perHour, reasons, target, urgency, vnd } from "../format";
import { INCIDENT_LABEL, INCIDENT_ORDER, INCIDENT_TONE, oxygenColor, STATUS_LABEL, STATUS_TEXT } from "../status";
import type { Incident, PondState } from "../types";
import { Track } from "./Track";

const SHOWN_PONDS = 6;
const CLOSEST = 5;

interface Props {
  ponds: Map<string, PondState>;
  incidents: Map<string, Incident>;
  now: number;
  offsetHours: number;
  selected: string | null;
  onSelect: (id: string) => void;
}

/** What needs a person, most urgent first: open incidents, then ponds worth watching on their own. */
export function Now({ ponds, incidents, now, offsetHours, selected, onSelect }: Props) {
  const open = [...incidents.values()]
    .filter((i) => i.open)
    .sort((a, b) => INCIDENT_ORDER.indexOf(a.status) - INCIDENT_ORDER.indexOf(b.status) || b.opened_at.localeCompare(a.opened_at));
  const covered = new Set(open.flatMap((i) => i.ponds));
  const loose = [...ponds.values()]
    .map((pond) => ({ pond, status: effectiveStatus(pond, now) }))
    .filter(({ pond, status }) => status !== "ok" && !covered.has(pond._id))
    .sort((a, b) => urgency(a.pond, a.status) - urgency(b.pond, b.status));

  return (
    <section aria-labelledby="now-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-ink-700 pb-3">
        <h2 id="now-title" className="font-display text-[24px] leading-none text-paper">
          Now
        </h2>
        <p className="text-[12.5px] text-mute">
          {open.length ? `${open.length} open ${open.length === 1 ? "incident" : "incidents"}` : "no open incidents"}
          {loose.length > 0 && ` · ${loose.length} ${loose.length === 1 ? "pond" : "ponds"} to watch`}
        </p>
      </div>

      {open.length === 0 && loose.length === 0 ? (
        <AllQuiet total={ponds.size} />
      ) : (
        <>
          <ol className="divide-y divide-ink-700">
            {open.map((incident) => (
              <li key={incident._id}>
                <IncidentRow
                  incident={incident}
                  pond={incident.pond ? ponds.get(incident.pond) : undefined}
                  offsetHours={offsetHours}
                  selected={selected === (incident.pond ?? incident._id)}
                  onSelect={onSelect}
                />
              </li>
            ))}
          </ol>
          {loose.length > 0 && (
            <ul className={`divide-y divide-ink-700 ${open.length ? "border-t border-ink-700" : ""}`}>
              {loose.slice(0, SHOWN_PONDS).map(({ pond, status }) => (
                <li key={pond._id}>
                  <button
                    type="button"
                    onClick={() => onSelect(pond._id)}
                    className={`grid w-full grid-cols-[6.5rem_minmax(0,1fr)_auto] items-baseline gap-x-4 py-3 text-left transition-colors hover:bg-ink-900/70 ${
                      pond._id === selected ? "bg-ink-900" : ""
                    }`}
                  >
                    <span className="font-mono text-[13px] text-paper">{pond._id}</span>
                    <span className="truncate text-[13px] text-paper-2">{reasons(pond, status, now).join(" · ")}</span>
                    <span className="whitespace-nowrap text-right">
                      <span className={`numeral text-[21px] ${status === "sensor" ? "text-mute line-through" : "text-paper"}`}>
                        {status === "blind" || !pond.last ? "–" : pond.last.do.toFixed(1)}
                      </span>
                      <span className={`ml-2 text-[12px] ${STATUS_TEXT[status]}`}>{STATUS_LABEL[status]}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {loose.length > SHOWN_PONDS && (
            <p className="border-t border-ink-700 pt-3 text-[12px] text-mute">
              and {loose.length - SHOWN_PONDS} more on the map below
            </p>
          )}
        </>
      )}
      <Closest ponds={ponds} now={now} exclude={covered} selected={selected} onSelect={onSelect} />
    </section>
  );
}

/** The safe ponds with the least oxygen: where the next alarm is most likely to come from. */
function Closest({
  ponds,
  now,
  exclude,
  selected,
  onSelect,
}: {
  ponds: Map<string, PondState>;
  now: number;
  exclude: Set<string>;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const closest = [...ponds.values()]
    .filter((p) => p.last && effectiveStatus(p, now) === "ok" && !exclude.has(p._id))
    .sort((a, b) => a.last!.do - b.last!.do)
    .slice(0, CLOSEST);
  if (!closest.length) return null;
  return (
    <div className="mt-10">
      <h3 className="font-display text-[18px] text-paper">Closest to the line</h3>
      <p className="mt-0.5 text-[12.5px] text-mute">The safe ponds with the least oxygen right now, against the 3 and 4 mg/L marks.</p>
      <ul className="mt-2 divide-y divide-ink-700">
        {closest.map((pond) => (
          <li key={pond._id}>
            <button
              type="button"
              onClick={() => onSelect(pond._id)}
              className={`grid w-full grid-cols-[6.5rem_minmax(0,15rem)_3rem_4.5rem_minmax(0,1fr)] items-center gap-4 py-2.5 text-left transition-colors hover:bg-ink-900/70 ${
                pond._id === selected ? "bg-ink-900" : ""
              }`}
            >
              <span className="font-mono text-[13px] text-paper">{pond._id}</span>
              <Gauge mgl={pond.last!.do} />
              <span className="numeral text-right text-[20px] text-paper">{pond.last!.do.toFixed(1)}</span>
              <span className="text-right font-mono text-[11.5px] text-mute">{perHour(pond.forecast?.slope_per_min)}/h</span>
              <span className="truncate text-[12px] text-faint">{(pond.last!.do - 4).toFixed(1)} above the safe line</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

const GAUGE = { lo: 2.5, hi: 6.5 };

/** Where a pond sits on the oxygen scale, with the stress and safe marks for reference. */
function Gauge({ mgl }: { mgl: number }) {
  const at = (v: number) => `${((Math.min(GAUGE.hi, Math.max(GAUGE.lo, v)) - GAUGE.lo) / (GAUGE.hi - GAUGE.lo)) * 100}%`;
  return (
    <span className="relative block h-[14px]" aria-hidden="true">
      <span className="absolute inset-x-0 top-[6px] h-[2px] rounded-full bg-ink-700" />
      <span className="absolute top-[6px] h-[2px] rounded-full bg-paper-2/60" style={{ left: at(4), width: `calc(${at(mgl)} - ${at(4)})` }} />
      {[3, 4].map((v) => (
        <span key={v} className={`absolute top-[2px] h-[10px] w-px ${v === 3 ? "bg-rust" : "bg-ochre"}`} style={{ left: at(v) }} />
      ))}
      <span className="absolute top-[3px] size-[8px] -translate-x-1/2 rounded-full border border-ink-950" style={{ left: at(mgl), background: oxygenColor(mgl) }} />
    </span>
  );
}

function IncidentRow({
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
  const diagnosis = incident.diagnosis;
  return (
    <button
      type="button"
      onClick={() => onSelect(incident.pond ?? incident._id)}
      className={`block w-full py-5 text-left transition-colors hover:bg-ink-900/70 ${
        selected ? "-ml-4 border-l-2 border-dawn bg-ink-900 pl-[14px]" : ""
      }`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-display text-[21px] leading-tight text-paper">{target(incident)}</span>
        <span className={`text-[13px] ${INCIDENT_TONE[incident.status]}`}>{INCIDENT_LABEL[incident.status]}</span>
        <span className="ml-auto font-mono text-[11px] text-faint">{incident._id}</span>
      </div>
      <p className="mt-1 text-[13px] text-paper-2">
        {diagnosis ? (
          <>
            {CAUSE_LABEL[diagnosis.cause] ?? diagnosis.cause}
            <span className="text-mute"> · {Math.round(diagnosis.confidence * 100)}% sure</span>
          </>
        ) : (
          "Looking for the cause…"
        )}
        {incident.at_risk && (
          <>
            <span className="text-mute"> · </span>
            <span className="text-dawn-soft">≈ {vnd(incident.at_risk.value_vnd)} of shrimp at stake</span>
          </>
        )}
      </p>
      <Track incident={incident} offsetHours={offsetHours} />
      <div className="mt-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-[12.5px]">
        {pond?.last && (
          <span className="whitespace-nowrap">
            <span className="numeral text-[21px] text-paper">{pond.last.do.toFixed(1)}</span>
            <span className="text-mute">
              {" "}
              mg/L{pond.forecast ? ` · ${perHour(pond.forecast.slope_per_min)} per hour` : ""}
            </span>
          </span>
        )}
        {step && (
          <span className="text-paper-2">
            <span className="mr-1.5 font-mono text-[11px] text-mute">{clockTime(step.t, offsetHours)}</span>
            {describe(step)}
          </span>
        )}
      </div>
    </button>
  );
}

function AllQuiet({ total }: { total: number }) {
  return (
    <div className="py-8">
      <p className="font-display text-[27px] italic leading-snug text-paper-2">All {total} ponds are safe.</p>
      <p className="mt-2 max-w-lg text-[13px] leading-relaxed text-mute">
        Nothing needs a person. Every pond is forecast every ten seconds, and one that drifts toward 3 mg/L shows up
        here before it gets there.
      </p>
    </div>
  );
}

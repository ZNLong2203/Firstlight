import { CAUSE_LABEL, effectiveStatus, perHour, reasons, urgency, vnd } from "../format";
import { INCIDENT_LABEL, INCIDENT_ORDER, INCIDENT_TONE, STATUS_LABEL, STATUS_TEXT } from "../status";
import type { Incident, IncidentStatus, PondState, Status } from "../types";
import { EstateMap } from "./EstateMap";
import { Track } from "./Track";

const SHOWN = 8;
const CLOSEST = 4;

const INCIDENT_BAR: Record<IncidentStatus, string> = {
  investigating: "bg-paper/70",
  mitigating: "bg-ochre",
  verifying: "bg-sea",
  monitoring: "bg-fog",
  awaiting_approval: "bg-dawn",
  escalated: "bg-rust",
  resolved: "bg-sea",
  dismissed: "bg-lavender",
};

const STATUS_BAR: Record<Status, string> = {
  alert: "bg-rust",
  blind: "bg-fog",
  watch: "bg-ochre",
  sensor: "bg-lavender",
  ok: "bg-sea",
};

interface Props {
  ponds: Map<string, PondState>;
  incidents: Map<string, Incident>;
  now: number;
  offsetHours: number;
  selected: string | null;
  onSelect: (id: string) => void;
}

/** The ponds first: what needs a look on top, every pond of the estate below. */
export function PondsView({ ponds, incidents, now, offsetHours, selected, onSelect }: Props) {
  const list = [...ponds.values()];
  const open = [...incidents.values()]
    .filter((i) => i.open)
    .sort((a, b) => INCIDENT_ORDER.indexOf(a.status) - INCIDENT_ORDER.indexOf(b.status) || b.opened_at.localeCompare(a.opened_at));
  const covered = new Set(open.flatMap((i) => i.ponds));
  const loose = list
    .map((pond) => ({ pond, status: effectiveStatus(pond, now) }))
    .filter(({ pond, status }) => status !== "ok" && !covered.has(pond._id))
    .sort((a, b) => urgency(a.pond, a.status) - urgency(b.pond, b.status));
  const shownLoose = loose.slice(0, Math.max(0, SHOWN - open.length));

  return (
    <div className="space-y-8">
      {open.length + loose.length === 0 ? (
        <Quiet ponds={list} now={now} onSelect={onSelect} />
      ) : (
        <section aria-labelledby="attention-title">
          <h2 id="attention-title" className="mb-3 font-display text-[19px] text-paper">
            Needs a look
          </h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(18.5rem,1fr))] gap-3">
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
            {shownLoose.map(({ pond, status }) => (
              <PondCard key={pond._id} pond={pond} status={status} now={now} selected={pond._id === selected} onSelect={onSelect} />
            ))}
          </div>
          {loose.length > shownLoose.length && (
            <p className="mt-2 text-[12px] text-mute">and {loose.length - shownLoose.length} more, ringed on the map</p>
          )}
        </section>
      )}
      <EstateMap ponds={list} now={now} selected={selected} onSelect={onSelect} />
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
  const diagnosis = incident.diagnosis;
  const where =
    incident.scope === "pond"
      ? incident.pond
      : incident.scope === "gateway"
        ? `${incident.gateway} · ${incident.ponds.length} ponds`
        : incident.scope === "farm"
          ? `Farm ${incident.farm}`
          : "The whole estate";
  return (
    <button
      type="button"
      onClick={() => onSelect(incident.pond ?? incident._id)}
      className={`relative overflow-hidden rounded-md border bg-ink-900 py-3.5 pl-5 pr-4 text-left transition-colors hover:border-paper/30 ${
        selected ? "border-paper/50" : "border-ink-600"
      }`}
    >
      <span className={`absolute inset-y-0 left-0 w-[3px] ${INCIDENT_BAR[incident.status]}`} aria-hidden="true" />
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-display text-[18px] leading-tight text-paper">{where}</span>
        <span className={`text-right text-[12px] ${INCIDENT_TONE[incident.status]}`}>{INCIDENT_LABEL[incident.status]}</span>
      </div>
      <p className="mt-0.5 text-[12.5px] text-paper-2">
        {diagnosis ? (
          <>
            {CAUSE_LABEL[diagnosis.cause] ?? diagnosis.cause}
            <span className="text-mute"> · {Math.round(diagnosis.confidence * 100)}% sure</span>
          </>
        ) : (
          "Looking for the cause…"
        )}
      </p>
      <Track incident={incident} offsetHours={offsetHours} compact />
      <div className="mt-3 flex items-baseline justify-between gap-3 text-[12px]">
        {pond?.last ? (
          <span>
            <span className="numeral text-[22px] text-paper">{pond.last.do.toFixed(1)}</span>
            <span className="text-mute"> mg/L · {perHour(pond.forecast?.slope_per_min)}/h</span>
          </span>
        ) : (
          <span className="text-mute">{incident.ponds.length} ponds</span>
        )}
        {incident.at_risk && <span className="text-dawn-soft">≈ {vnd(incident.at_risk.value_vnd)} at stake</span>}
      </div>
    </button>
  );
}

function PondCard({
  pond,
  status,
  now,
  selected,
  onSelect,
}: {
  pond: PondState;
  status: Status;
  now: number;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(pond._id)}
      className={`relative overflow-hidden rounded-md border bg-ink-900 py-3.5 pl-5 pr-4 text-left transition-colors hover:border-paper/30 ${
        selected ? "border-paper/50" : "border-ink-600"
      }`}
    >
      <span className={`absolute inset-y-0 left-0 w-[3px] ${STATUS_BAR[status]}`} aria-hidden="true" />
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[14px] text-paper">{pond._id}</span>
        <span className={`text-[12px] ${STATUS_TEXT[status]}`}>{STATUS_LABEL[status]}</span>
      </div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className={`numeral text-[28px] leading-none ${status === "sensor" ? "text-mute line-through" : "text-paper"}`}>
          {status === "blind" || !pond.last ? "–" : pond.last.do.toFixed(1)}
        </span>
        <span className="text-[11.5px] text-mute">
          mg/L{status !== "blind" && status !== "sensor" && pond.forecast ? ` · ${perHour(pond.forecast.slope_per_min)}/h` : ""}
        </span>
      </div>
      <p className="mt-1.5 text-[12px] text-paper-2">{reasons(pond, status, now).join(" · ")}</p>
    </button>
  );
}

/** Nothing needs a person: say so in one line, and name the ponds nearest the line. */
function Quiet({ ponds, now, onSelect }: { ponds: PondState[]; now: number; onSelect: (id: string) => void }) {
  const closest = ponds
    .filter((p) => p.last && effectiveStatus(p, now) === "ok")
    .sort((a, b) => a.last!.do - b.last!.do)
    .slice(0, CLOSEST);
  return (
    <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <span className="font-display text-[20px] italic text-paper">All {ponds.length} ponds are safe.</span>
      {closest.length > 0 && (
        <span className="text-[13px] text-mute">
          Lowest right now:{" "}
          {closest.map((pond, i) => (
            <span key={pond._id}>
              <button type="button" onClick={() => onSelect(pond._id)} className="font-mono text-paper-2 transition-colors hover:text-dawn-soft">
                {pond._id} <span className="text-paper">{pond.last!.do.toFixed(1)}</span>
              </button>
              {i < closest.length - 1 ? <span className="text-faint"> · </span> : null}
            </span>
          ))}
        </span>
      )}
    </p>
  );
}

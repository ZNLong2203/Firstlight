import { CAUSE_LABEL, clockDay, clockTime, describe, headline, perHour, seconds, target, vnd } from "../format";
import { INCIDENT_LABEL, INCIDENT_ORDER, INCIDENT_TONE } from "../status";
import type { AiStats, Incident, PondState } from "../types";
import { Track } from "./Track";

interface Props {
  ponds: Map<string, PondState>;
  incidents: Map<string, Incident>;
  offsetHours: number;
  aiStats: AiStats | null;
  selected: string | null;
  onSelect: (id: string) => void;
}

/** Open incidents with every stop they have passed, and the record of the ones that closed. */
export function IncidentsView({ ponds, incidents, offsetHours, aiStats, selected, onSelect }: Props) {
  const all = [...incidents.values()];
  const open = all
    .filter((i) => i.open)
    .sort((a, b) => INCIDENT_ORDER.indexOf(a.status) - INCIDENT_ORDER.indexOf(b.status) || b.opened_at.localeCompare(a.opened_at));
  const closed = all.filter((i) => !i.open).sort((a, b) => (b.closed_at ?? "").localeCompare(a.closed_at ?? ""));

  return (
    <div className="space-y-12">
      <Summary closed={closed} aiStats={aiStats} />

      <section aria-labelledby="open-title">
        <Heading id="open-title" title="Open" note={open.length ? `${open.length} now` : undefined} />
        {open.length === 0 ? (
          <p className="py-5 font-display text-[19px] italic text-paper-2">No open incidents. The farms are quiet.</p>
        ) : (
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
        )}
      </section>

      <section aria-labelledby="record-title">
        <Heading id="record-title" title="The record" note="closed recently, newest first; select a row for the whole story" />
        {closed.length === 0 ? (
          <p className="py-5 text-[13px] text-mute">Nothing has closed yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-[13px]">
              <thead>
                <tr className="border-b border-ink-700 text-[11.5px] text-mute">
                  <th className="py-2 pr-4 font-normal">Closed</th>
                  <th className="py-2 pr-4 font-normal">What happened</th>
                  <th className="py-2 pr-4 font-normal">Where</th>
                  <th className="py-2 pr-4 text-right font-normal">Detected in</th>
                  <th className="py-2 pr-4 text-right font-normal">Acted in</th>
                  <th className="py-2 pr-4 text-right font-normal">Lowest, mg/L</th>
                  <th className="py-2 font-normal">Outcome</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-700">
                {closed.map((incident) => {
                  const m = incident.metrics;
                  const pick = () => onSelect(incident.pond ?? incident._id);
                  return (
                    <tr
                      key={incident._id}
                      tabIndex={0}
                      onClick={pick}
                      onKeyDown={(event) => event.key === "Enter" && pick()}
                      className="cursor-pointer transition-colors hover:bg-ink-900/80 focus-visible:bg-ink-900"
                    >
                      <td className="py-3 pr-4 font-mono text-[12px] text-faint">{clockDay(incident.closed_at, offsetHours)}</td>
                      <td className="py-3 pr-4 text-paper">{CAUSE_LABEL[incident.diagnosis?.cause ?? "unknown"]}</td>
                      <td className="py-3 pr-4 font-mono text-[12.5px] text-paper-2">{where(incident)}</td>
                      <td className="py-3 pr-4 text-right font-mono text-paper-2">{seconds(m?.mttd_s)}</td>
                      <td className="py-3 pr-4 text-right font-mono text-paper-2">
                        {m?.time_to_action_s != null ? seconds(m.time_to_action_s) : "–"}
                      </td>
                      <td className="py-3 pr-4 text-right font-mono text-paper-2">{m?.min_do != null ? m.min_do.toFixed(1) : "–"}</td>
                      <td className={`py-3 ${incident.status === "dismissed" ? "text-lavender" : "text-sea"}`}>{outcome(incident)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Heading({ id, title, note }: { id: string; title: string; note?: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-ink-700 pb-3">
      <h2 id={id} className="font-display text-[24px] leading-none text-paper">
        {title}
      </h2>
      {note && <span className="text-[12.5px] text-mute">{note}</span>}
    </div>
  );
}

/** The numbers a judge or a farm owner asks first. */
function Summary({ closed, aiStats }: { closed: Incident[]; aiStats: AiStats | null }) {
  const median = (values: number[]) => {
    const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
    return sorted.length ? sorted[Math.floor((sorted.length - 1) / 2)] : null;
  };
  const detect = median(closed.map((i) => i.metrics?.mttd_s ?? NaN));
  const act = median(closed.map((i) => i.metrics?.time_to_action_s ?? NaN));
  const stopped = closed.filter((i) => i.status === "dismissed").length;
  const kept = closed
    .filter((i) => i.status === "resolved" && (i.metrics?.min_do ?? 0) >= 3 && ["aerator_failure", "power_outage"].includes(i.diagnosis?.cause ?? ""))
    .reduce((sum, i) => sum + (i.at_risk?.value_vnd ?? 0), 0);
  const facts: [string, string][] = [
    [String(closed.length), "closed recently"],
    [seconds(detect), "median time to detect"],
    [seconds(act), "median time to act"],
    [String(stopped), stopped === 1 ? "false alarm stopped" : "false alarms stopped"],
  ];
  if (kept) facts.push([vnd(kept), "of shrimp kept safe"]);
  if (aiStats?.scored) facts.push([`${aiStats.ai_correct}/${aiStats.scored}`, `Gemini right; rules ${aiStats.rules_correct}/${aiStats.scored}`]);
  return (
    <dl className="grid grid-cols-2 gap-x-8 gap-y-6 rounded-lg border border-ink-700 bg-ink-900/60 px-6 py-5 sm:grid-cols-3 xl:grid-cols-6">
      {facts.map(([value, label]) => (
        <div key={label}>
          <dd className="numeral text-[30px] leading-none text-paper">{value}</dd>
          <dt className="mt-1.5 text-[12px] text-mute">{label}</dt>
        </div>
      ))}
    </dl>
  );
}

export function IncidentRow({
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
      className={`block w-full px-1 py-5 text-left transition-colors hover:bg-ink-900/70 ${selected ? "bg-ink-900" : ""}`}
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
            <span className="text-mute"> mg/L · {perHour(pond.forecast?.slope_per_min)} per hour</span>
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

/** What the incident was about: the pond, the gateway, the farm or the whole estate. */
function where(incident: Incident): string {
  if (incident.scope === "pond") return incident.pond ?? incident.key;
  if (incident.scope === "gateway") return incident.gateway ?? incident.key;
  if (incident.scope === "farm") return `farm ${incident.farm ?? incident.key}`;
  return "whole estate";
}

function outcome(incident: Incident): string {
  if (incident.status === "dismissed") return "False alarm stopped, nobody woken";
  const m = incident.metrics;
  if (m?.blind_s != null) {
    return `Data back after ${seconds(m.blind_s)}${m.coverage != null ? `, ${Math.round(m.coverage * 100)}% of it recovered` : ""}`;
  }
  const kept =
    incident.at_risk && (m?.min_do ?? 0) >= 3 && ["aerator_failure", "power_outage"].includes(incident.diagnosis?.cause ?? "")
      ? ` · ≈ ${vnd(incident.at_risk.value_vnd)} kept safe`
      : "";
  return `Recovered${m?.mttr_min != null ? ` in ${m.mttr_min} min` : ""}${kept}`;
}

import { CAUSE_LABEL, clockTime, seconds, vnd } from "../format";
import type { AiStats, Incident, Report } from "../types";

interface Props {
  incidents: Map<string, Incident>;
  offsetHours: number;
  aiStats: AiStats | null;
  dawn: { estate: Report | null; farms: Report[] };
  onSelect: (id: string) => void;
}

/** The record: what closed, how fast, what it protected; the AI's score; and the morning's report. */
export function Tonight({ incidents, offsetHours, aiStats, dawn, onSelect }: Props) {
  const closed = [...incidents.values()]
    .filter((i) => !i.open && i.diagnosis && i.diagnosis.cause !== "unknown")
    .sort((a, b) => (b.closed_at ?? "").localeCompare(a.closed_at ?? ""))
    .slice(0, 7);

  return (
    <aside className="space-y-10">
      <section aria-labelledby="record-title">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-ink-700 pb-3">
          <h2 id="record-title" className="font-display text-[24px] leading-none text-paper">
            The record
          </h2>
          <span className="text-[12.5px] text-mute">closed recently, newest first</span>
        </div>
        {closed.length === 0 ? (
          <p className="py-6 text-[13px] text-mute">Nothing has closed yet.</p>
        ) : (
          <ol className="divide-y divide-ink-700">
            {closed.map((incident) => (
              <li key={incident._id}>
                <button
                  type="button"
                  onClick={() => onSelect(incident.pond ?? incident._id)}
                  className="block w-full py-3 text-left transition-colors hover:bg-ink-900/70"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-[13.5px] text-paper">
                      {CAUSE_LABEL[incident.diagnosis?.cause ?? "unknown"]}
                      <span className="text-mute"> · {where(incident)}</span>
                    </span>
                    <span className="font-mono text-[11px] text-faint">{clockTime(incident.closed_at, offsetHours)}</span>
                  </div>
                  <div className="mt-0.5 text-[12px] text-paper-2">{proofLine(incident)}</div>
                  <div className={`mt-0.5 text-[12px] ${incident.status === "dismissed" ? "text-lavender" : "text-sea"}`}>
                    {outcome(incident)}
                  </div>
                </button>
              </li>
            ))}
          </ol>
        )}
      </section>

      {aiStats && (aiStats.scored ?? 0) > 0 && (
        <section aria-labelledby="ai-title">
          <h2 id="ai-title" className="font-display text-[19px] text-paper">
            A second opinion
          </h2>
          <p className="mt-2 text-[13px] leading-relaxed text-paper-2">
            After the rules have acted, Gemini investigates each incident again with read-only tools. Scored against the
            faults injected from the chaos panel, it was right{" "}
            <span className="whitespace-nowrap font-mono text-paper">
              {aiStats.ai_correct} of {aiStats.scored}
            </span>{" "}
            times, and the rules{" "}
            <span className="whitespace-nowrap font-mono text-paper">
              {aiStats.rules_correct} of {aiStats.scored}
            </span>
            .{aiStats.grounded === 1 ? " Every answer named only real ponds and devices." : ""}
          </p>
        </section>
      )}

      {dawn.estate && <DawnNote estate={dawn.estate} farms={dawn.farms} />}
    </aside>
  );
}

function DawnNote({ estate, farms }: { estate: Report; farms: Report[] }) {
  const s = estate.summary;
  const facts: [string, string][] = [
    [String(s.incidents), s.incidents === 1 ? "incident" : "incidents"],
    [String(s.recovered), "recovered"],
    [String(s.false_alarms_stopped), "false alarms stopped"],
  ];
  return (
    <section className="rounded-md border border-dawn/25 bg-dawn/[0.05] p-4" aria-labelledby="dawn-title">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="dawn-title" className="font-display text-[19px] text-dawn-soft">
          Dawn report
        </h2>
        <span className="font-mono text-[11px] text-mute">{estate.date}</span>
      </div>
      {estate.message_vi && (
        <p lang="vi" className="mt-2 font-display text-[15.5px] italic leading-snug text-paper">
          “{estate.message_vi}”
        </p>
      )}
      <dl className="mt-3 grid grid-cols-3 gap-3">
        {facts.map(([value, label]) => (
          <div key={label}>
            <dt className="sr-only">{label}</dt>
            <dd className="numeral text-[22px] leading-none text-paper">{value}</dd>
            <div className="mt-1 text-[11px] text-mute">{label}</div>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[12px] text-paper-2">
        {s.oxygen_safety != null && (
          <>
            Oxygen at 4 mg/L or more for <span className="font-mono text-paper">{(s.oxygen_safety * 100).toFixed(1)}%</span> of
            pond-minutes.
          </>
        )}
        {s.protected_vnd > 0 && <> About {vnd(s.protected_vnd)} of shrimp protected.</>}
        {s.lowest && (
          <>
            {" "}
            Lowest: <span className="font-mono">{s.lowest.pond}</span> at {s.lowest.do.toFixed(1)} mg/L.
          </>
        )}
      </p>
      {farms.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-[12px] text-mute">
            {farms.length} {farms.length === 1 ? "farm" : "farms"} with something to report
          </summary>
          <ul className="mt-1.5 space-y-1">
            {farms.map((farm) => (
              <li key={farm._id} className="text-[12px] text-paper-2">
                <span className="font-mono text-mute">{farm.farm}</span>{" "}
                {Object.entries(farm.summary.by_cause)
                  .map(([cause, n]) => `${n} × ${CAUSE_LABEL[cause] ?? cause}`)
                  .join(", ") || "no incidents"}
                {farm.summary.lowest && ` · lowest ${farm.summary.lowest.do.toFixed(1)} mg/L`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** What the incident was about: the pond, the gateway, the farm or the whole estate. */
function where(incident: Incident): string {
  if (incident.scope === "pond") return incident.pond ?? incident.key;
  if (incident.scope === "gateway") return incident.gateway ?? incident.key;
  if (incident.scope === "farm") return `farm ${incident.farm ?? incident.key}`;
  return "the whole estate";
}

function proofLine(incident: Incident): string {
  const m = incident.metrics;
  if (incident.status === "dismissed") return "the probe was fouled; the water was fine";
  if (!m) return "";
  if (m.blind_s != null) {
    const back = m.coverage != null ? `${Math.round(m.coverage * 100)}% of the readings recovered` : "data back";
    return `blind for ${seconds(m.blind_s)} · ${back}`;
  }
  const acted = m.time_to_action_s != null ? ` · acted in ${seconds(m.time_to_action_s)}` : "";
  return `detected in ${seconds(m.mttd_s)}${acted} · lowest ${m.min_do?.toFixed(1) ?? "–"} mg/L`;
}

function outcome(incident: Incident): string {
  if (incident.status === "dismissed") return "False alarm stopped, nobody woken";
  const m = incident.metrics;
  const kept =
    incident.at_risk && (m?.min_do ?? 0) >= 3 && ["aerator_failure", "power_outage"].includes(incident.diagnosis?.cause ?? "")
      ? ` · ≈ ${vnd(incident.at_risk.value_vnd)} kept safe`
      : "";
  return `Recovered${m?.mttr_min != null ? ` in ${m.mttr_min} min` : ""}${kept}`;
}

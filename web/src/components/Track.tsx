import { clockTime, seconds } from "../format";
import type { Incident } from "../types";

interface Stage {
  label: string;
  at?: string;
  tone?: "sea" | "lavender" | "rust" | "dawn";
}

const TONE = {
  sea: { node: "bg-sea border-sea", text: "text-sea" },
  lavender: { node: "bg-lavender border-lavender", text: "text-lavender" },
  rust: { node: "bg-rust border-rust", text: "text-rust" },
  dawn: { node: "bg-dawn border-dawn", text: "text-dawn" },
};

/** The stops an incident passes, depending on what it turned out to be. */
export function stagesOf(incident: Incident): Stage[] {
  const first = (...kinds: string[]) => incident.timeline.find((e) => kinds.includes(e.kind))?.t;
  const cause = incident.diagnosis?.cause;
  const closed = incident.status === "resolved" || incident.status === "dismissed" ? incident.closed_at : undefined;
  const detected: Stage = { label: "Detected", at: incident.opened_at };
  const diagnosed: Stage = { label: "Diagnosed", at: first("diagnosed") };
  const escalated = first("escalated");

  if (cause === "sensor_fault" || incident.status === "dismissed") {
    return [detected, diagnosed, { label: "False alarm stopped", at: closed, tone: "lavender" }];
  }
  if (cause === "gateway_offline" || cause === "ingest_regression") {
    return [detected, diagnosed, { label: "Someone told", at: first("telegram", "notify") }, { label: "Data back", at: closed, tone: "sea" }];
  }
  if (cause === "unknown") {
    return [detected, diagnosed, { label: "Escalated", at: escalated, tone: "rust" }, { label: "Recovered", at: closed, tone: "sea" }];
  }
  const stages: Stage[] = [detected, diagnosed];
  if (first("approval_requested")) stages.push({ label: "Approved", at: first("approved"), tone: "dawn" });
  stages.push({ label: "Acted", at: first("action_done") });
  stages.push({ label: "Verifying", at: first("verifying") });
  stages.push({ label: "Recovered", at: closed, tone: "sea" });
  if (escalated) {
    const next = stages.findIndex((s) => !s.at);
    stages.splice(next < 0 ? stages.length : next, 0, { label: "Escalated", at: escalated, tone: "rust" });
  }
  return stages;
}

/** Detection to recovery as a line of stops, with the time each was reached. */
export function Track({ incident, offsetHours, compact = false }: { incident: Incident; offsetHours: number; compact?: boolean }) {
  const stages = stagesOf(incident);
  const start = Date.parse(incident.opened_at);
  const current = stages.findIndex((s) => !s.at);
  return (
    <ol className={`grid ${compact ? "mt-3" : "mt-4"}`} style={{ gridTemplateColumns: `repeat(${stages.length}, minmax(0, 1fr))` }}>
      {stages.map((stage, i) => {
        const reached = Boolean(stage.at);
        const tone = stage.tone ? TONE[stage.tone] : null;
        const nextReached = Boolean(stages[i + 1]?.at);
        return (
          <li key={stage.label} className="relative pr-2">
            {i < stages.length - 1 && (
              <span
                className={`absolute left-[9px] right-0 top-[4px] h-0 border-t ${
                  nextReached ? "border-paper/45" : "border-dashed border-ink-600"
                }`}
                aria-hidden="true"
              />
            )}
            <span
              className={`relative block size-[9px] rounded-full border ${
                reached ? (tone ? tone.node : "border-paper bg-paper") : i === current ? "border-paper bg-ink-950" : "border-ink-600 bg-ink-950"
              }`}
              aria-hidden="true"
            />
            <span className={`mt-1.5 block text-[11.5px] leading-tight ${reached ? (tone ? tone.text : "text-paper") : i === current ? "text-paper-2" : "text-faint"}`}>
              {stage.label}
            </span>
            {!compact && (
              <span className="mt-0.5 block font-mono text-[10.5px] text-mute">
                {stage.at ? (i === 0 ? clockTime(stage.at, offsetHours, true) : `+${seconds(Math.max(0, Math.round((Date.parse(stage.at) - start) / 1000)))}`) : " "}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

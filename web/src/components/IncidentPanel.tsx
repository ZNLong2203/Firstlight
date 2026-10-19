import { useState } from "react";

import { demoFetch } from "../demo";
import { CAUSE_LABEL, clockName, clockTime, describe, seconds } from "../format";
import { INCIDENT_LABEL, INCIDENT_TONE } from "../status";
import type { Incident } from "../types";
import { AiPanel } from "./AiPanel";
import { Track } from "./Track";

interface Props {
  incident: Incident;
  offsetHours: number;
  demoCode: string;
}

/** Everything about one incident: what was decided, on which evidence, what was done, and the proof. */
export function IncidentPanel({ incident, offsetHours, demoCode }: Props) {
  const diagnosis = incident.diagnosis;
  const evidence = [...incident.evidence].sort((a, b) => b.weight - a.weight);
  return (
    <section className="space-y-7 border-b border-ink-700 px-6 py-6" aria-label={`Incident ${incident._id}`}>
      <div>
        <p className="text-[12px]">
          <span className={INCIDENT_TONE[incident.status]}>{INCIDENT_LABEL[incident.status]}</span>
          <span className="font-mono text-faint"> · {incident._id}</span>
        </p>
        <h3 className="mt-1 font-display text-[22px] leading-tight text-paper">
          {diagnosis ? CAUSE_LABEL[diagnosis.cause] ?? diagnosis.cause : "Looking for the cause…"}
          {diagnosis && diagnosis.confidence > 0 && (
            <span className="ml-2 font-sans text-[13px] text-mute">{Math.round(diagnosis.confidence * 100)}% sure</span>
          )}
        </h3>
        <Track incident={incident} offsetHours={offsetHours} />
      </div>

      {incident.status === "awaiting_approval" && <Approvals incident={incident} demoCode={demoCode} />}

      {incident.metrics && <Proof incident={incident} />}

      <AiPanel incident={incident} />

      {evidence.length > 0 && (
        <div>
          <Heading>The evidence</Heading>
          <p className="mb-3 text-[12px] text-mute">
            Each check pulls toward a cause or away from it; the strongest pull is the diagnosis.
          </p>
          <ul className="space-y-2.5">
            {evidence.map((item, index) => {
              const support = item.verdict === "support";
              return (
                <li key={index} className="grid grid-cols-[minmax(0,1fr)_7.5rem] items-center gap-4 text-[12.5px]">
                  <span className="text-paper-2">
                    <span className="text-mute">{CAUSE_LABEL[item.cause] ?? item.cause}: </span>
                    {item.detail}
                    {item.at && <span className="text-faint"> · from {clockTime(item.at, offsetHours, true)}</span>}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="relative h-[5px] flex-1 bg-ink-800" aria-hidden="true">
                      <span
                        className={`absolute top-0 h-full ${support ? "left-1/2 bg-sea" : "right-1/2 bg-rust"}`}
                        style={{ width: `${Math.min(1, item.weight) * 50}%` }}
                      />
                      <span className="absolute left-1/2 top-[-3px] h-[11px] w-px bg-ink-600" />
                    </span>
                    <span className={`w-9 text-right font-mono text-[11px] ${support ? "text-sea" : "text-rust"}`}>
                      {support ? "+" : "−"}
                      {item.weight.toFixed(2)}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {incident.similar && incident.similar.length > 0 && <Similar incident={incident} />}

      <div>
        <Heading>What happened, {clockName(offsetHours)}</Heading>
        <ol className="mt-2 space-y-1.5">
          {incident.timeline.map((entry, index) => (
            <li key={index} className="grid grid-cols-[4.6rem_minmax(0,1fr)] gap-2 text-[12.5px]">
              <span className="font-mono text-[11.5px] text-faint">{clockTime(entry.t, offsetHours, true)}</span>
              <span className={entry.kind === "notify" ? "text-dawn-soft" : entry.kind === "escalated" ? "text-rust" : "text-paper-2"}>
                {describe(entry)}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h4 className="font-display text-[16px] text-paper">{children}</h4>;
}

function Proof({ incident }: { incident: Incident }) {
  const m = incident.metrics!;
  const lowest: [string, string] = ["lowest oxygen", m.min_do != null ? `${m.min_do.toFixed(2)}` : "–"];
  const cells: [string, string][] =
    m.blind_s != null
      ? [
          ["detected in", seconds(m.mttd_s)],
          ["blind for", seconds(m.blind_s)],
          ["readings recovered", m.coverage != null ? `${Math.round(m.coverage * 100)}%` : "–"],
          lowest,
          ["closed in", m.mttr_min != null ? `${m.mttr_min} min` : "–"],
        ]
      : [
          ["detected in", seconds(m.mttd_s)],
          ["acted in", seconds(m.time_to_action_s)],
          lowest,
          ["under 4 mg/L", m.below_safe_min != null ? `${m.below_safe_min} min` : "–"],
          ["recovered in", m.mttr_min != null ? `${m.mttr_min} min` : "–"],
          ...(m.mtta_s != null ? [["acknowledged in", seconds(m.mtta_s)] as [string, string]] : []),
        ];
  return (
    <div>
      <Heading>The proof</Heading>
      <dl className="mt-3 grid grid-cols-3 gap-x-4 gap-y-4">
        {cells.map(([label, value]) => (
          <div key={label}>
            <dd className="numeral text-[24px] leading-none text-paper">{value}</dd>
            <dt className="mt-1 text-[11.5px] text-mute">{label}</dt>
          </div>
        ))}
      </dl>
      {incident.notebook?.url && (
        <a
          href={incident.notebook.url}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-block text-[12.5px] text-dawn-soft underline-offset-4 hover:underline"
        >
          The graphs, in a Datadog notebook ↗
        </a>
      )}
    </div>
  );
}

function Approvals({ incident, demoCode }: { incident: Incident; demoCode: string }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = (incident.approvals ?? []).filter((a) => a.status === "pending");
  const approve = async (action: string) => {
    setBusy(true);
    setError("");
    try {
      await demoFetch(`/v1/incidents/${incident._id}/approve`, demoCode, {
        method: "POST",
        body: JSON.stringify({ action, by: "console" }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not approve");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="border-l-2 border-dawn pl-4">
      <p className="font-display text-[16px] text-paper">A costly step waits for a person.</p>
      <p className="mt-1 text-[12.5px] text-paper-2">Starting a generator burns diesel, so Firstlight asks before it does.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {pending.map((approval) => (
          <button
            key={approval.action}
            type="button"
            disabled={busy || !demoCode}
            onClick={() => void approve(approval.action)}
            className="rounded-md bg-dawn px-3.5 py-2 text-[13px] font-medium text-ink-950 transition-colors hover:bg-dawn-soft disabled:opacity-50"
          >
            Approve {approval.action === "generator.start" ? "starting the generator" : approval.action}
          </button>
        ))}
      </div>
      {!demoCode && <p className="mt-2 text-[12px] text-mute">Unlock with the demo code in the chaos panel.</p>}
      {error && <p className="mt-2 text-[12px] text-rust">{error}</p>}
    </div>
  );
}

/** The closest past incidents from MongoDB's hybrid search: what happened then, and how it ended. */
function Similar({ incident }: { incident: Incident }) {
  return (
    <div>
      <Heading>Seen before</Heading>
      <p className="text-[12px] text-mute">The closest closed incidents, by meaning and by words.</p>
      <ul className="mt-2 divide-y divide-ink-700">
        {incident.similar!.map((past) => (
          <li key={past._id}>
            <a href={`#${past._id}`} className="block py-2.5 text-[12.5px] transition-colors hover:bg-ink-850">
              <span className="text-paper">{CAUSE_LABEL[past.cause ?? "unknown"] ?? past.cause}</span>
              <span className="text-mute"> · {past.key} · </span>
              <span className="font-mono text-faint">{past._id}</span>
              <span className={past.status === "dismissed" ? "text-lavender" : "text-sea"}>
                {past.status === "dismissed"
                  ? " · false alarm stopped"
                  : past.metrics?.mttr_min != null
                    ? ` · recovered in ${past.metrics.mttr_min} min`
                    : ""}
              </span>
              {past.summary && <span className="mt-0.5 block text-paper-2">{past.summary.slice(0, 180)}</span>}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

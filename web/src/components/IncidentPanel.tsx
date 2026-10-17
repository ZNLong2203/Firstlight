import { useState } from "react";

import { demoFetch } from "../demo";
import { CAUSE_LABEL, clockTime, describe, seconds } from "../format";
import { INCIDENT_BADGE, INCIDENT_LABEL } from "../status";
import type { Incident } from "../types";

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
    <section className="space-y-4 border-b border-night-700 px-5 py-4" aria-label={`Incident ${incident._id}`}>
      <header className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${INCIDENT_BADGE[incident.status]}`}>
          {INCIDENT_LABEL[incident.status]}
        </span>
        <span className="font-mono text-xs text-slate-400">{incident._id}</span>
        <span className="text-sm font-semibold text-white">
          {diagnosis ? CAUSE_LABEL[diagnosis.cause] ?? diagnosis.cause : "Looking for the cause…"}
        </span>
        {diagnosis && diagnosis.confidence > 0 && (
          <span className="text-xs text-slate-400">{Math.round(diagnosis.confidence * 100)}% sure</span>
        )}
      </header>

      {incident.status === "awaiting_approval" && <Approvals incident={incident} demoCode={demoCode} />}

      {incident.metrics && <Proof incident={incident} />}

      {evidence.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Evidence</h4>
          <ul className="space-y-1.5">
            {evidence.map((item, index) => (
              <li key={index} className="flex gap-2 text-xs">
                <span
                  className={`mt-0.5 shrink-0 font-bold ${item.verdict === "support" ? "text-emerald-300" : "text-rose-300"}`}
                  aria-label={item.verdict === "support" ? "for" : "against"}
                >
                  {item.verdict === "support" ? "+" : "−"}
                  {item.weight.toFixed(2)}
                </span>
                <span className="text-slate-300">
                  <span className="text-slate-500">{CAUSE_LABEL[item.cause] ?? item.cause}: </span>
                  {item.detail}
                  {item.at && <span className="text-slate-500"> · from {clockTime(item.at, offsetHours, true)}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Timeline · farm time</h4>
        <ol className="relative space-y-2 border-l border-night-700 pl-3">
          {incident.timeline.map((entry, index) => (
            <li key={index} className="text-xs">
              <span className="absolute -left-[3px] mt-1.5 size-1.5 rounded-full bg-slate-500" aria-hidden="true" />
              <span className="mr-2 font-mono text-slate-500">{clockTime(entry.t, offsetHours, true)}</span>
              <span className={entry.kind === "notify" ? "text-sky-200" : "text-slate-200"}>{describe(entry)}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Proof({ incident }: { incident: Incident }) {
  const m = incident.metrics!;
  const lowest: [string, string] = ["Lowest DO", m.min_do != null ? `${m.min_do.toFixed(2)} mg/L` : "–"];
  const cells: [string, string][] =
    m.blind_s != null
      ? [
          ["Detected in", seconds(m.mttd_s)],
          ["Blind for", seconds(m.blind_s)],
          ["Readings recovered", m.coverage != null ? `${Math.round(m.coverage * 100)}%` : "–"],
          lowest,
          ["Resolved in", m.mttr_min != null ? `${m.mttr_min} min` : "–"],
        ]
      : [
          ["Detected in", seconds(m.mttd_s)],
          ["Acted in", seconds(m.time_to_action_s)],
          lowest,
          ["Under 4 mg/L", m.below_safe_min != null ? `${m.below_safe_min} min` : "–"],
          ["Resolved in", m.mttr_min != null ? `${m.mttr_min} min` : "–"],
        ];
  return (
    <dl className="grid grid-cols-3 gap-2 rounded-lg bg-emerald-500/[0.06] p-3 ring-1 ring-emerald-500/20 sm:grid-cols-5">
      {cells.map(([label, value]) => (
        <div key={label}>
          <dt className="text-[10px] uppercase tracking-wider text-emerald-300/70">{label}</dt>
          <dd className="font-mono text-sm font-semibold text-emerald-100">{value}</dd>
        </div>
      ))}
    </dl>
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
    <div className="rounded-lg bg-orange-500/10 p-3 ring-1 ring-orange-500/40">
      <p className="text-xs text-orange-100">A costly step waits for a person.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {pending.map((approval) => (
          <button
            key={approval.action}
            type="button"
            disabled={busy || !demoCode}
            onClick={() => void approve(approval.action)}
            className="rounded-md bg-orange-500 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-orange-400 disabled:opacity-50"
          >
            Approve {approval.action === "generator.start" ? "starting the generator" : approval.action}
          </button>
        ))}
      </div>
      {!demoCode && <p className="mt-2 text-[11px] text-orange-200/70">Unlock with the demo code in the chaos panel.</p>}
      {error && <p className="mt-2 text-[11px] text-red-300">{error}</p>}
    </div>
  );
}

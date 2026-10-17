import { CAUSE_LABEL } from "../format";
import type { Incident } from "../types";

/** What Gemini made of the incident: a second opinion, a draft for the farmer, and how it scored. */
export function AiPanel({ incident }: { incident: Incident }) {
  const ai = incident.investigation;
  if (!ai) return null;
  if (ai.status === "running") {
    return (
      <section className="rounded-lg bg-sky-500/[0.06] p-3 text-xs text-sky-200 ring-1 ring-sky-500/20">
        <span className="mr-2 inline-block size-2 animate-pulse rounded-full bg-sky-300" aria-hidden="true" />
        AI investigator is checking the evidence…
      </section>
    );
  }
  if (ai.status === "failed") {
    return <p className="text-xs text-slate-500">AI investigator unavailable; the rules handled this incident on their own.</p>;
  }
  const scores = incident.evals ?? {};
  const badges: [string, boolean | undefined][] = [
    ["agrees with the rules", scores.agrees_with_rules],
    ["explains what the rules could not", scores.explained_unknown],
    ["only real devices named", scores.grounded === undefined ? undefined : scores.grounded >= 1],
    ["farmer message OK", scores.farmer_message_ok],
    ["right, by the ground truth", scores.rca_correct],
  ];
  return (
    <section className="space-y-2 rounded-lg bg-sky-500/[0.05] p-3 ring-1 ring-sky-500/20">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-sky-300">AI investigator</h4>
        <span className="font-mono text-[10px] text-slate-500">
          {ai.model} · {ai.tool_calls?.length ?? 0} tool calls · {((ai.latency_ms ?? 0) / 1000).toFixed(0)} s
        </span>
      </header>
      <p className="text-sm text-white">
        {CAUSE_LABEL[ai.cause ?? "unknown"] ?? ai.cause}
        <span className="text-xs text-slate-400"> · {Math.round((ai.confidence ?? 0) * 100)}% sure</span>
      </p>
      <ul className="flex flex-wrap gap-1.5">
        {badges
          .filter(([, value]) => value !== undefined)
          .map(([label, value]) => (
            <li
              key={label}
              className={`rounded-full px-2 py-0.5 text-[10px] ${value ? "bg-emerald-500/15 text-emerald-200" : "bg-rose-500/15 text-rose-200"}`}
            >
              {value ? "✓" : "✗"} {label}
            </li>
          ))}
      </ul>
      {ai.summary && <p className="text-xs leading-relaxed text-slate-300">{ai.summary}</p>}
      {ai.farmer_message_vi && (
        <blockquote className="border-l-2 border-sky-400/50 pl-2 text-xs italic text-sky-100" lang="vi">
          {ai.farmer_message_vi}
        </blockquote>
      )}
      {ai.next_steps && ai.next_steps.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-300">
          {ai.next_steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      )}
      {incident.postmortem?.status === "done" && incident.postmortem.postmortem_md && (
        <details className="pt-1">
          <summary className="cursor-pointer text-xs font-medium text-sky-300">
            Postmortem: {incident.postmortem.title}
          </summary>
          <Markdown text={incident.postmortem.postmortem_md} />
        </details>
      )}
    </section>
  );
}

/** Headings, bullets and paragraphs: all a postmortem uses. Rendered as text, never as HTML. */
function Markdown({ text }: { text: string }) {
  return (
    <div className="mt-2 space-y-1.5 text-xs leading-relaxed text-slate-300">
      {text.split("\n").map((line, index) => {
        const plain = line.replace(/\*\*(.+?)\*\*/g, "$1");
        if (/^#{1,6}\s/.test(line)) {
          return (
            <h5 key={index} className="pt-1 font-semibold text-slate-100">
              {plain.replace(/^#{1,6}\s/, "")}
            </h5>
          );
        }
        if (/^\s*[-*]\s/.test(line)) {
          return (
            <p key={index} className="pl-3 before:-ml-3 before:mr-1.5 before:content-['•']">
              {plain.replace(/^\s*[-*]\s/, "")}
            </p>
          );
        }
        return plain.trim() ? <p key={index}>{plain}</p> : null;
      })}
    </div>
  );
}

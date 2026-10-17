import { CAUSE_LABEL } from "../format";
import type { Incident } from "../types";

/** What Gemini made of the incident: a second opinion, a draft for the farmer, and how it scored. */
export function AiPanel({ incident }: { incident: Incident }) {
  const ai = incident.investigation;
  if (!ai) return null;
  if (ai.status === "running") {
    return (
      <p className="font-display text-[15px] italic text-mute">Gemini is going over the evidence for a second opinion…</p>
    );
  }
  if (ai.status === "failed") {
    return <p className="text-[12.5px] text-mute">No second opinion this time: the rules handled the incident on their own.</p>;
  }
  const scores = incident.evals ?? {};
  const checks: [string, boolean | undefined][] = [
    ["agrees with the rules", scores.agrees_with_rules],
    ["explains what the rules could not", scores.explained_unknown],
    ["names only real ponds and devices", scores.grounded === undefined ? undefined : scores.grounded >= 1],
    ["farmer's message is plain Vietnamese", scores.farmer_message_ok],
    ["matches the fault that was injected", scores.rca_correct],
  ];
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-display text-[16px] text-paper">A second opinion</h4>
        <span className="font-mono text-[10.5px] text-faint">
          {ai.model} · {ai.tool_calls?.length ?? 0} tool calls · {((ai.latency_ms ?? 0) / 1000).toFixed(0)} s
        </span>
      </div>
      <p className="mt-1 text-[13px] text-paper-2">
        Gemini read the evidence again with its own tools and calls it{" "}
        <span className="text-paper">{(CAUSE_LABEL[ai.cause ?? "unknown"] ?? ai.cause)?.toLowerCase()}</span>, {Math.round((ai.confidence ?? 0) * 100)}%
        sure.
      </p>
      {ai.summary && <p className="mt-2 text-[12.5px] leading-relaxed text-paper-2">{ai.summary}</p>}
      {ai.farmer_message_vi && (
        <figure className="mt-3 border-l-2 border-dawn/60 pl-3">
          <blockquote lang="vi" className="font-display text-[15px] italic leading-snug text-paper">
            “{ai.farmer_message_vi}”
          </blockquote>
          <figcaption className="mt-1 text-[11.5px] text-mute">the message drafted for the farmer</figcaption>
        </figure>
      )}
      <ul className="mt-3 grid gap-x-4 gap-y-1 sm:grid-cols-2">
        {checks
          .filter(([, value]) => value !== undefined)
          .map(([label, value]) => (
            <li key={label} className="flex items-baseline gap-1.5 text-[12px]">
              <span className={value ? "text-sea" : "text-rust"} aria-label={value ? "yes" : "no"}>
                {value ? "✓" : "✗"}
              </span>
              <span className={value ? "text-paper-2" : "text-rust"}>{label}</span>
            </li>
          ))}
      </ul>
      {ai.next_steps && ai.next_steps.length > 0 && (
        <ul className="mt-3 list-disc space-y-0.5 pl-4 text-[12.5px] text-paper-2 marker:text-faint">
          {ai.next_steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      )}
      {incident.postmortem?.status === "done" && incident.postmortem.postmortem_md && (
        <details className="mt-3">
          <summary className="cursor-pointer text-[12.5px] text-dawn-soft">The postmortem: {incident.postmortem.title}</summary>
          <Markdown text={incident.postmortem.postmortem_md} />
        </details>
      )}
    </div>
  );
}

/** Headings, bullets and paragraphs: all a postmortem uses. Rendered as text, never as HTML. */
function Markdown({ text }: { text: string }) {
  return (
    <div className="mt-2 space-y-1.5 text-[12.5px] leading-relaxed text-paper-2">
      {text.split("\n").map((line, index) => {
        const plain = line.replace(/\*\*(.+?)\*\*/g, "$1");
        if (/^#{1,6}\s/.test(line)) {
          return (
            <h5 key={index} className="pt-1 font-display text-[14px] text-paper">
              {plain.replace(/^#{1,6}\s/, "")}
            </h5>
          );
        }
        if (/^\s*[-*]\s/.test(line)) {
          return (
            <p key={index} className="pl-3 before:-ml-3 before:mr-1.5 before:text-faint before:content-['•']">
              {plain.replace(/^\s*[-*]\s/, "")}
            </p>
          );
        }
        return plain.trim() ? <p key={index}>{plain}</p> : null;
      })}
    </div>
  );
}

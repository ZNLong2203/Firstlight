import { CAUSE_LABEL, vnd } from "../format";
import type { AiStats, Incident, Night, Report } from "../types";
import { NightCurve } from "./NightCurve";

interface Props {
  night: Night | null;
  incidents: Incident[];
  now: number;
  offsetHours: number;
  total: number;
  aiStats: AiStats | null;
  dawn: { estate: Report | null; farms: Report[] };
  onSelect: (id: string) => void;
}

/** The night as a whole: the estate's oxygen since dusk, last night's report, and how the AI has scored. */
export function NightView({ night, incidents, now, offsetHours, total, aiStats, dawn, onSelect }: Props) {
  return (
    <div className="space-y-12">
      <NightCurve night={night} incidents={incidents} now={now} offsetHours={offsetHours} total={total} height={320} onSelect={onSelect} />
      <div className="grid gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        {dawn.estate ? (
          <DawnNote estate={dawn.estate} farms={dawn.farms} />
        ) : (
          <p className="font-display text-[17px] italic text-mute">The first dawn report is written at 06:00.</p>
        )}
        {aiStats && (aiStats.scored ?? 0) > 0 && <SecondOpinion stats={aiStats} />}
      </div>
    </div>
  );
}

function SecondOpinion({ stats }: { stats: AiStats }) {
  return (
    <section aria-labelledby="ai-title">
      <h2 id="ai-title" className="font-display text-[22px] text-paper">
        A second opinion
      </h2>
      <p className="mt-2 text-[13.5px] leading-relaxed text-paper-2">
        After the rules have acted, Gemini investigates each incident again with read-only tools. Its answers are scored
        without asking another model, and in the demo against the fault that was really injected.
      </p>
      <dl className="mt-5 grid grid-cols-3 gap-6">
        <Fact value={`${stats.ai_correct}/${stats.scored}`} label="Gemini right by the injected fault" />
        <Fact value={`${stats.rules_correct}/${stats.scored}`} label="the rules right, the same way" />
        <Fact value={stats.grounded === 1 ? "all" : `${Math.round((stats.grounded ?? 0) * 100)}%`} label="answers naming only real devices" />
      </dl>
    </section>
  );
}

function Fact({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <dd className="numeral text-[30px] leading-none text-paper">{value}</dd>
      <dt className="mt-1.5 text-[12px] leading-snug text-mute">{label}</dt>
    </div>
  );
}

function DawnNote({ estate, farms }: { estate: Report; farms: Report[] }) {
  const s = estate.summary;
  const facts: [string, string][] = [
    [String(s.incidents), s.incidents === 1 ? "incident" : "incidents"],
    [String(s.recovered), "recovered"],
    [String(s.false_alarms_stopped), "false alarms stopped"],
  ];
  if (s.oxygen_safety != null) facts.push([`${(s.oxygen_safety * 100).toFixed(1)}%`, "of pond-minutes at 4 mg/L or more"]);
  return (
    <section className="rounded-lg border border-dawn/25 bg-dawn/[0.05] p-6" aria-labelledby="dawn-title">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="dawn-title" className="font-display text-[22px] text-dawn-soft">
          The dawn report
        </h2>
        <span className="font-mono text-[11.5px] text-mute">{estate.date}</span>
      </div>
      {estate.message_vi && (
        <p lang="vi" className="mt-3 font-display text-[18px] italic leading-snug text-paper">
          “{estate.message_vi}”
        </p>
      )}
      <p className="mt-1 text-[12px] text-mute">the message the owner reads at 06:00</p>
      <dl className="mt-5 grid grid-cols-2 gap-6 sm:grid-cols-4">
        {facts.map(([value, label]) => (
          <Fact key={label} value={value} label={label} />
        ))}
      </dl>
      {(s.protected_vnd > 0 || s.lowest) && (
        <p className="mt-5 text-[12.5px] text-paper-2">
          {s.protected_vnd > 0 && <>About {vnd(s.protected_vnd)} of shrimp protected. </>}
          {s.lowest && (
            <>
              The lowest pond was <span className="font-mono">{s.lowest.pond}</span>, at {s.lowest.do.toFixed(1)} mg/L.
            </>
          )}
        </p>
      )}
      {farms.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-[12.5px] text-mute">
            {farms.length} {farms.length === 1 ? "farm" : "farms"} with something to report
          </summary>
          <ul className="mt-2 space-y-1">
            {farms.map((farm) => (
              <li key={farm._id} className="text-[12.5px] text-paper-2">
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

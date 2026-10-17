import { CAUSE_LABEL, vnd } from "../format";
import type { Report } from "../types";

/** Last night in one line, for the farm owner who slept through it. */
export function DawnReport({ estate, farms }: { estate: Report; farms: Report[] }) {
  const s = estate.summary;
  const chips: [string, string][] = [
    [String(s.incidents), s.incidents === 1 ? "incident" : "incidents"],
    [String(s.recovered), "recovered"],
    [String(s.false_alarms_stopped), "false alarms stopped"],
  ];
  if (s.protected_vnd) chips.push([`≈ ${vnd(s.protected_vnd)}`, "of shrimp protected"]);
  if (s.oxygen_safety != null) chips.push([`${(s.oxygen_safety * 100).toFixed(1)}%`, "of pond-minutes at 4 mg/L or more"]);
  return (
    <section className="rounded-xl border border-orange-300/20 bg-gradient-to-r from-indigo-950/60 to-orange-950/30 px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-orange-200">Dawn report · {estate.date}</h2>
        {s.lowest && (
          <span className="text-[11px] text-slate-400">
            lowest DO: <span className="font-mono text-slate-200">{s.lowest.pond}</span> at {s.lowest.do.toFixed(1)} mg/L
          </span>
        )}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
        {chips.map(([value, label]) => (
          <li key={label} className="text-xs text-slate-400">
            <span className="mr-1 font-mono text-sm font-semibold text-white">{value}</span>
            {label}
          </li>
        ))}
      </ul>
      {estate.message_vi && (
        <p className="mt-2 text-xs italic text-orange-100/90" lang="vi">
          {estate.message_vi}
        </p>
      )}
      {farms.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[11px] text-slate-400">{farms.length} farms with something to report</summary>
          <ul className="mt-1.5 grid gap-1 sm:grid-cols-2">
            {farms.map((farm) => (
              <li key={farm._id} className="text-xs text-slate-300">
                <span className="font-mono text-slate-400">{farm.farm}</span>{" "}
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

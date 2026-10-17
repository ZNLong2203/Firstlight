import { effectiveStatus, perHour, reasons, STATUS_LABEL, urgency } from "../format";
import { PROVINCES, type PondState, type Status } from "../types";

const CARD: Record<Status, string> = {
  alert: "border-red-500/70 bg-red-500/10 alert-glow",
  blind: "border-slate-500/50 bg-night-800 blind-hatch",
  watch: "border-amber-400/50 bg-amber-400/[0.06]",
  ok: "border-night-700 bg-night-800",
};
const BADGE: Record<Status, string> = {
  alert: "bg-red-500 text-white",
  blind: "bg-slate-600 text-slate-100",
  watch: "bg-amber-400 text-night-950",
  ok: "bg-emerald-500 text-night-950",
};
const SHOWN = 8;

interface Props {
  ponds: PondState[];
  now: number;
  selected: string | null;
  onSelect: (id: string) => void;
}

/** The ponds that need someone tonight, most urgent first. */
export function Attention({ ponds, now, selected, onSelect }: Props) {
  const queue = ponds
    .map((pond) => ({ pond, status: effectiveStatus(pond, now) }))
    .filter(({ status }) => status !== "ok")
    .sort((a, b) => urgency(a.pond, a.status) - urgency(b.pond, b.status));

  if (queue.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3">
        <Moon />
        <p className="text-sm text-emerald-100">
          All quiet. <span className="text-emerald-300/80">{ponds.length} of {ponds.length} ponds are safe.</span>
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
        {queue.slice(0, SHOWN).map(({ pond, status }) => (
          <button
            key={pond._id}
            type="button"
            onClick={() => onSelect(pond._id)}
            className={`rounded-xl border p-3 text-left transition hover:brightness-125 ${CARD[status]} ${
              pond._id === selected ? "outline-2 outline-offset-2 outline-sky-300" : ""
            }`}
          >
            <div className="flex items-center justify-between">
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${BADGE[status]}`}>
                {STATUS_LABEL[status]}
              </span>
              <span className="font-mono text-xs text-slate-300">{pond._id}</span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="font-mono text-3xl font-semibold tabular-nums text-white">
                {status === "blind" || !pond.last ? "–" : pond.last.do.toFixed(1)}
              </span>
              <span className="text-xs text-slate-400">mg/L</span>
              {status !== "blind" && pond.forecast && (
                <span className="ml-auto font-mono text-xs text-slate-400">{perHour(pond.forecast.slope_per_min)}/h</span>
              )}
            </div>
            <ul className="mt-1.5 space-y-0.5 text-xs text-slate-200">
              {reasons(pond, status, now).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-slate-500">
              {PROVINCES[pond.farm.split("-")[0]]} · {pond.gateway}
            </p>
          </button>
        ))}
      </div>
      {queue.length > SHOWN && (
        <p className="mt-2 text-xs text-slate-500">and {queue.length - SHOWN} more on the map below</p>
      )}
    </div>
  );
}

function Moon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5 shrink-0 text-emerald-300" fill="currentColor" aria-hidden="true">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
    </svg>
  );
}

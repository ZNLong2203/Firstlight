import { duration, farmClock, hhmm, nightElapsed } from "../format";
import { DOT, STATUS_LABEL, STATUS_ORDER } from "../status";
import type { Status } from "../types";
import type { Link } from "../useLive";

const NIGHT_MINUTES = 12 * 60;
const VIETNAM_UTC_OFFSET = 7;
interface Props {
  now: number;
  offsetHours: number | null;
  counts: Record<Status, number>;
  link: Link;
}

export function TopBar({ now, offsetHours, counts, link }: Props) {
  const farm = offsetHours === null ? null : farmClock(now, offsetHours);
  const elapsed = farm && nightElapsed(farm);

  return (
    <header className="sticky top-0 z-20 border-b border-night-700 bg-night-950/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-8 gap-y-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <Logo />
          <div>
            <div className="text-[15px] font-semibold tracking-tight text-white">Firstlight</div>
            <div className="text-[11px] text-slate-500">Night board</div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="font-mono text-3xl font-semibold tabular-nums text-white">{farm ? hhmm(farm) : "--:--"}</span>
          <span className="flex flex-col text-xs leading-snug">
            <span className="text-slate-300">
              {!farm ? "farm time" : elapsed === null ? "daytime on the farms" : `dawn in ${duration(NIGHT_MINUTES - elapsed)}`}
            </span>
            {/* The simulated farms run on a shifted clock so a daytime demo happens during their night. */}
            {farm && offsetHours !== VIETNAM_UTC_OFFSET && (
              <span className="text-slate-500">
                simulated farm clock · Vietnam {hhmm(farmClock(now, VIETNAM_UTC_OFFSET))}
              </span>
            )}
          </span>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {STATUS_ORDER.filter((status) => status !== "sensor" || counts.sensor > 0).map((status) => (
            <span
              key={status}
              className={`flex items-center gap-1.5 rounded-full border border-night-700 px-2.5 py-1 text-xs ${
                counts[status] || status === "ok" ? "text-slate-200" : "text-slate-600"
              }`}
            >
              <span className={`size-2 rounded-full ${counts[status] || status === "ok" ? DOT[status] : "bg-slate-700"}`} />
              <span className="font-mono font-semibold tabular-nums">{counts[status]}</span>
              {STATUS_LABEL[status]}
            </span>
          ))}
          <LinkState link={link} />
        </div>
      </div>
      <NightProgress elapsed={elapsed ?? null} />
    </header>
  );
}

function LinkState({ link }: { link: Link }) {
  const [label, tone] =
    link === "connecting"
      ? ["Connecting", "text-slate-400 bg-slate-400"]
      : link === "reconnecting"
        ? ["Reconnecting", "text-amber-300 bg-amber-300"]
        : ["Live", "text-emerald-300 bg-emerald-400"];
  const [text, dot] = tone.split(" ");
  return (
    <span className={`ml-1 flex items-center gap-1.5 text-xs font-medium ${text}`} role="status">
      <span className="relative flex size-2">
        {label === "Live" && <span className={`absolute inline-flex size-full animate-ping rounded-full opacity-60 ${dot}`} />}
        <span className={`relative inline-flex size-2 rounded-full ${dot}`} />
      </span>
      {label}
    </span>
  );
}

/** The night so far, from 18:00 to 06:00 on the farm clock. */
function NightProgress({ elapsed }: { elapsed: number | null }) {
  if (elapsed === null) return null;
  const share = Math.min(1, elapsed / NIGHT_MINUTES) * 100;
  return (
    <div className="relative h-1 bg-night-800" aria-hidden="true">
      {/* The gradient spans the whole night and is revealed up to now, so orange only shows near dawn. */}
      <div
        className="h-full bg-gradient-to-r from-indigo-900 via-indigo-500/70 to-dawn"
        style={{ clipPath: `inset(0 ${100 - share}% 0 0)` }}
      />
      <div
        className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-300 shadow-[0_0_10px_2px] shadow-indigo-400/60"
        style={{ left: `${share}%` }}
      />
    </div>
  );
}

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="size-8" aria-hidden="true">
      <defs>
        <linearGradient id="fl-sun" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#f97316" />
          <stop offset="1" stopColor="#fdba74" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="#111b31" />
      <path d="M7 21a9 9 0 0 1 18 0Z" fill="url(#fl-sun)" />
      <path d="M5 21h22M9 25h14" stroke="#38bdf8" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

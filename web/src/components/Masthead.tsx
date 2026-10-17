import { ago, clockName, duration, farmClock, hhmm, minutesToNight, nightElapsed } from "../format";
import type { Status } from "../types";
import type { Link } from "../useLive";

const NIGHT_MINUTES = 12 * 60;

interface Props {
  now: number;
  offsetHours: number | null;
  counts: Record<Status, number>;
  total: number;
  /** When the newest reading of any pond was taken, in ms. */
  latest: number | null;
  link: Link;
  /** A drawer covers the right of the screen. */
  inset: boolean;
}

export function Masthead({ now, offsetHours, counts, total, latest, link, inset }: Props) {
  const farm = offsetHours === null ? null : farmClock(now, offsetHours);
  const elapsed = farm ? nightElapsed(farm) : null;
  const needing = counts.alert + counts.blind + counts.watch;
  const breakdown = (
    [
      [counts.alert, "alert", "text-rust"],
      [counts.blind, "blind", "text-fog"],
      [counts.watch, "to watch", "text-ochre"],
      [counts.sensor, counts.sensor === 1 ? "probe not trusted" : "probes not trusted", "text-lavender"],
    ] as const
  ).filter(([n]) => n > 0);

  return (
    <header className="z-20 border-b border-ink-700 bg-ink-950 lg:sticky lg:top-0">
      <div className={`mx-auto flex max-w-[1600px] flex-wrap items-end gap-x-12 gap-y-4 px-4 pb-4 pt-5 sm:px-8 ${inset ? "xl:pr-[564px]" : ""}`}>
        <div className="flex items-center gap-3">
          <Mark />
          <div>
            <div className="font-display text-[27px] leading-none tracking-[-0.01em] text-paper">Firstlight</div>
            <div className="mt-1.5 text-[12px] text-mute">The night shift for {total || "the"} shrimp ponds</div>
          </div>
        </div>

        <div className="flex items-end gap-3">
          <span className="numeral text-[38px] leading-[0.8] text-paper sm:text-[46px]">{farm ? hhmm(farm) : "--:--"}</span>
          <span className="text-[12px] leading-[1.35] text-paper-2">
            {!farm
              ? "farm time"
              : elapsed === null
                ? `night falls in ${duration(minutesToNight(farm) ?? 0)}`
                : `dawn in ${duration(NIGHT_MINUTES - elapsed)}`}
            <br />
            <span className="text-mute">{offsetHours === null ? "" : clockName(offsetHours)}</span>
          </span>
        </div>

        <div className="ml-auto text-left sm:text-right">
          <p className="font-display text-[20px] leading-tight text-paper">
            {needing === 0 ? (
              <>All {total} ponds safe</>
            ) : (
              <>
                <span className={counts.alert ? "text-rust" : counts.blind ? "text-fog" : "text-ochre"}>
                  {needing} {needing === 1 ? "pond needs" : "ponds need"} a look
                </span>
                <span className="text-paper-2"> · {counts.ok} safe</span>
              </>
            )}
          </p>
          <p className="mt-1 text-[12px] text-mute">
            {breakdown.map(([n, label, tone]) => (
              <span key={label} className="mr-3">
                <span className={`font-mono ${tone}`}>{n}</span> {label}
              </span>
            ))}
            <Freshness link={link} now={now} latest={latest} />
          </p>
        </div>
      </div>
    </header>
  );
}

/** How fresh the board is, said quietly: the age of the newest reading, or that the link is down. */
function Freshness({ link, now, latest }: { link: Link; now: number; latest: number | null }) {
  if (link === "reconnecting") return <span className="text-ochre">reconnecting to the farms…</span>;
  if (link === "connecting" || latest === null) return <span>connecting…</span>;
  return <span>newest reading {ago((now - latest) / 1000)} ago</span>;
}

/** The sun coming up over the pond: the mark is the product's name. */
export function Mark({ className = "size-10" }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <path d="M10 23a10 10 0 0 1 20 0z" fill="#f0a35e" />
      <path d="M5 23h30M10 28h20M15 33h10" stroke="#ece5d5" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

import { ago, clockName, duration, farmClock, hhmm, minutesToNight, nightElapsed } from "../format";
import type { Night, Status } from "../types";
import type { Link } from "../useLive";
import { VIEWS, type View } from "../view";

const NIGHT_MINUTES = 12 * 60;

interface Props {
  now: number;
  offsetHours: number | null;
  counts: Record<Status, number>;
  total: number;
  /** When the newest reading of any pond was taken, in ms. */
  latest: number | null;
  link: Link;
  night: Night | null;
  openIncidents: number;
  view: View;
  onView: (view: View) => void;
  /** A drawer covers the right of the screen. */
  inset: boolean;
}

export function Masthead({ now, offsetHours, counts, total, latest, link, night, openIncidents, view, onView, inset }: Props) {
  const farm = offsetHours === null ? null : farmClock(now, offsetHours);
  const elapsed = farm ? nightElapsed(farm) : null;
  const needing = counts.alert + counts.blind + counts.watch;
  const badge: Record<View, [number, string] | null> = {
    ponds: needing ? [needing, counts.alert ? "text-rust" : counts.blind ? "text-fog" : "text-ochre"] : null,
    incidents: openIncidents ? [openIncidents, "text-dawn"] : null,
    night: null,
  };

  return (
    <header className="z-20 border-b border-ink-700 bg-ink-950/95 backdrop-blur-sm lg:sticky lg:top-0">
      <div className={`mx-auto max-w-[1600px] px-4 sm:px-8 ${inset ? "xl:pr-[564px]" : ""}`}>
        <div className="flex flex-wrap items-end gap-x-10 gap-y-3 pb-3 pt-4">
          <div className="flex items-center gap-3">
            <Mark />
            <div>
              <div className="font-display text-[26px] leading-none tracking-[-0.01em] text-paper">Firstlight</div>
              <div className="mt-1.5 hidden text-[12px] text-mute sm:block">The night shift for {total || "the"} shrimp ponds</div>
            </div>
          </div>

          <div className="flex items-end gap-3">
            <span className="numeral text-[38px] leading-[0.8] text-paper sm:text-[42px]">{farm ? hhmm(farm) : "--:--"}</span>
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

          {night && night.buckets.length > 1 && (
            <button
              type="button"
              onClick={() => onView("night")}
              className="hidden items-end gap-2 text-left md:flex"
              title="The estate's median oxygen tonight; open the night"
            >
              <Spark night={night} />
              <span className="text-[11.5px] leading-[1.35] text-mute">
                {now >= Date.parse(night.end) ? "last night, median" : "median pond"}
                <br />
                <span className="font-mono text-paper-2">{night.buckets.at(-1)!.median.toFixed(1)} mg/L</span>
              </span>
            </button>
          )}

          <div className="w-full text-left sm:ml-auto sm:w-auto sm:text-right">
            <p className="font-display text-[17px] leading-tight text-paper sm:text-[19px]">
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
              <Freshness link={link} now={now} latest={latest} />
            </p>
          </div>
        </div>

        <nav className="-mb-px flex gap-7" aria-label="Views">
          {VIEWS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => onView(id)}
              aria-current={view === id ? "page" : undefined}
              className={`flex items-baseline gap-1.5 border-b-2 pb-2.5 text-[14px] transition-colors ${
                view === id ? "border-dawn text-paper" : "border-transparent text-mute hover:text-paper-2"
              }`}
            >
              {label}
              {badge[id] && <span className={`font-mono text-[12px] ${badge[id]![1]}`}>{badge[id]![0]}</span>}
            </button>
          ))}
        </nav>
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

/** Tonight's median pond, small enough to sit next to the clock. */
function Spark({ night }: { night: Night }) {
  const W = 120;
  const H = 30;
  const start = Date.parse(night.start);
  const end = Date.parse(night.end);
  const lo = 3;
  const hi = 6;
  const x = (ms: number) => ((ms - start) / (end - start)) * W;
  const y = (v: number) => H - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * H;
  const d = night.buckets.map((b, i) => `${i ? "L" : "M"}${x(Date.parse(b.t)).toFixed(1)},${y(b.median).toFixed(1)}`).join("");
  return (
    <svg width={W} height={H} className="block overflow-visible" aria-hidden="true">
      <line x1="0" x2={W} y1={y(4)} y2={y(4)} stroke="#d6b062" strokeOpacity="0.4" strokeDasharray="2 3" />
      <path d={d} fill="none" stroke="#ece5d5" strokeWidth="1.5" strokeLinejoin="round" />
      <path d={`M${W - 5},${H} a5,5 0 0 1 10,0z`} fill="#f0a35e" />
    </svg>
  );
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

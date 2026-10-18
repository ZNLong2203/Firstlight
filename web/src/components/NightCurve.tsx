import { useEffect, useRef, useState } from "react";

import { CAUSE_LABEL, farmClock, hhmm } from "../format";
import type { Incident, Night } from "../types";

const PAD = { left: 28, right: 72, top: 30, bottom: 30 };
const HOUR = 3_600_000;

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

interface Props {
  night: Night | null;
  incidents: Incident[];
  now: number;
  offsetHours: number;
  total: number;
  height?: number;
  onSelect: (id: string) => void;
}

/**
 * The estate's oxygen from dusk to dawn: the median pond, the band down to the 10th percentile, and the
 * lowest pond, every ten minutes. Oxygen bottoms out just before dawn, so those hours are marked; the
 * night's incidents sit on the time axis where they began.
 */
export function NightCurve({ night, incidents, now, offsetHours, total, height = 300, onSelect }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const start = night ? Date.parse(night.start) : 0;
  const end = night ? Date.parse(night.end) : 0;
  const tonight = night !== null && now >= start && now < end;

  return (
    <section aria-label="Oxygen across the estate tonight">
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-ink-700 pb-3">
          <h2 className="font-display text-[24px] leading-none text-paper">
            {night === null ? "The night" : tonight ? "Tonight" : "Last night"}, across {total} ponds
          </h2>
          <p className="flex flex-wrap items-center gap-x-4 text-[12px] text-mute">
            <span className="flex items-center gap-1.5">
              <svg width="18" height="6" aria-hidden="true">
                <path d="M0 3h18" stroke="#ece5d5" strokeWidth="1.6" />
              </svg>
              median pond
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-[18px] bg-paper/15" aria-hidden="true" />
              down to the 10th percentile
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="18" height="6" aria-hidden="true">
                <path d="M0 3h18" stroke="#d6b062" strokeWidth="1.2" strokeDasharray="3 3" />
              </svg>
              lowest pond
            </span>
            <span>every 10 minutes, mg/L</span>
          </p>
        </div>
        <div ref={ref} className="relative mt-4" style={{ height }}>
          {night && width > 0 && (
            <Chart
              height={height}
              night={night}
              incidents={incidents}
              now={now}
              tonight={tonight}
              offsetHours={offsetHours}
              width={width}
              start={start}
              end={end}
              onSelect={onSelect}
            />
          )}
        </div>
      </div>
    </section>
  );
}

function Chart({
  height: HEIGHT,
  night,
  incidents,
  now,
  tonight,
  offsetHours,
  width,
  start,
  end,
  onSelect,
}: {
  height: number;
  night: Night;
  incidents: Incident[];
  now: number;
  tonight: boolean;
  offsetHours: number;
  width: number;
  start: number;
  end: number;
  onSelect: (id: string) => void;
}) {
  const step = night.step_min * 60_000;
  const points = night.buckets.map((b) => ({ ...b, at: Date.parse(b.t) + step / 2 }));
  const values = points.flatMap((p) => [p.min, p.median]);
  const lo = Math.min(2.8, Math.floor((Math.min(...values, 9) - 0.4) * 2) / 2);
  const hi = Math.max(5.6, Math.ceil((Math.max(...values, 0) + 0.4) * 2) / 2);
  const innerW = width - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const x = (ms: number) => PAD.left + ((ms - start) / (end - start)) * innerW;
  const y = (mgl: number) => PAD.top + (1 - (mgl - lo) / (hi - lo)) * innerH;
  const path = (key: "median" | "min" | "p10") =>
    points.map((p, i) => `${i ? "L" : "M"}${x(p.at).toFixed(1)},${y(p[key]).toFixed(1)}`).join("");
  const band = points.length
    ? `${path("median")}${[...points]
        .reverse()
        .map((p) => `L${x(p.at).toFixed(1)},${y(p.p10).toFixed(1)}`)
        .join("")}Z`
    : "";
  const base = HEIGHT - PAD.bottom;
  const hours = Array.from({ length: 7 }, (_, i) => start + i * 2 * HOUR);
  const levels = [3, 4, 5, 6].filter((v) => v > lo && v < hi);
  const nowX = x(Math.min(now, end));
  const marks = incidents.filter((i) => {
    const t = Date.parse(i.opened_at);
    return t >= start && t < end;
  });

  return (
    <svg width={width} height={HEIGHT} className="block" role="img" aria-label="Dissolved oxygen across the estate">
      <defs>
        <linearGradient id="night-sky" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#0f1718" stopOpacity="0.9" />
          <stop offset="0.72" stopColor="#111a1b" stopOpacity="0.9" />
          <stop offset="1" stopColor="#f0a35e" stopOpacity="0.16" />
        </linearGradient>
      </defs>
      <rect x={PAD.left} y={PAD.top - 8} width={innerW} height={innerH + 8} fill="url(#night-sky)" rx="3" />

      {/* The hours before dawn, when ponds run lowest. */}
      <rect x={x(end - 3 * HOUR)} y={PAD.top - 8} width={x(end) - x(end - 3 * HOUR)} height={innerH + 8} fill="#f0a35e" opacity="0.045" />
      {x(end) - x(end - 3 * HOUR) > 190 && (
        <text x={x(end - 3 * HOUR) + 8} y={PAD.top + 6} className="fill-paper-2 font-display text-[12px] italic">
          before dawn, oxygen runs lowest
        </text>
      )}

      {levels.map((v) => (
        <g key={v}>
          <line
            x1={PAD.left}
            x2={PAD.left + innerW}
            y1={y(v)}
            y2={y(v)}
            stroke={v === 3 ? "#e0714e" : v === 4 ? "#d6b062" : "#22302f"}
            strokeOpacity={v === 3 ? 0.55 : v === 4 ? 0.45 : 1}
            strokeDasharray={v <= 4 ? "4 4" : undefined}
          />
          <text x={PAD.left - 8} y={y(v) + 3.5} textAnchor="end" className="fill-faint font-mono text-[10px]">
            {v}
          </text>
          {v <= 4 && (
            <text x={PAD.left + innerW + 8} y={y(v) + 3.5} className={`font-sans text-[11px] ${v === 3 ? "fill-rust" : "fill-ochre"}`}>
              {v === 3 ? "stress" : "safe above"}
            </text>
          )}
        </g>
      ))}

      {band && <path d={band} fill="#ece5d5" opacity="0.13" />}
      {points.length > 1 && (
        <>
          <path d={path("min")} fill="none" stroke="#d6b062" strokeWidth="1.2" strokeDasharray="3 3" strokeOpacity="0.85" />
          <path d={path("median")} fill="none" stroke="#ece5d5" strokeWidth="1.8" strokeLinejoin="round" />
        </>
      )}

      {/* What has not happened yet is dimmer than what has. */}
      {tonight && <rect x={nowX} y={PAD.top - 8} width={x(end) - nowX} height={innerH + 8} fill="#0b1112" opacity="0.45" />}

      {hours.map((ms) => (
        <text key={ms} x={x(ms)} y={base + 18} textAnchor="middle" className="fill-faint font-mono text-[10px]">
          {hhmm(farmClock(ms, offsetHours))}
        </text>
      ))}
      <line x1={PAD.left} x2={PAD.left + innerW} y1={base} y2={base} stroke="#22302f" />

      {/* Dawn: where the night ends and the report is written. */}
      <path d={`M${x(end) - 7},${base} a7,7 0 0 1 14,0z`} fill="#f0a35e" />

      {tonight && (
        <g>
          <line x1={nowX} x2={nowX} y1={PAD.top - 14} y2={base} stroke="#f0a35e" strokeWidth="1.2" />
          <text x={nowX} y={PAD.top - 18} textAnchor="middle" className="fill-dawn font-mono text-[10.5px]">
            {hhmm(farmClock(now, offsetHours))}
          </text>
        </g>
      )}

      {points.length === 0 && (
        <text x={PAD.left + 12} y={PAD.top + innerH / 2} className="fill-mute font-display text-[13px] italic">
          The night has only just begun.
        </text>
      )}

      {marks.map((incident) => {
        const open = Boolean(incident.open);
        const color = open ? "#e0714e" : incident.status === "dismissed" ? "#aea4d6" : "#86bfa9";
        const label = `${incident._id} · ${CAUSE_LABEL[incident.diagnosis?.cause ?? "unknown"] ?? ""} · ${
          incident.pond ?? incident.gateway ?? incident.farm ?? "estate"
        }`;
        return (
          <g
            key={incident._id}
            role="button"
            tabIndex={0}
            className="cursor-pointer"
            onClick={() => onSelect(incident.pond ?? incident._id)}
            onKeyDown={(event) => event.key === "Enter" && onSelect(incident.pond ?? incident._id)}
          >
            <title>{label}</title>
            <line x1={x(Date.parse(incident.opened_at))} x2={x(Date.parse(incident.opened_at))} y1={base - 10} y2={base} stroke={color} />
            <circle
              cx={x(Date.parse(incident.opened_at))}
              cy={base - 10}
              r="4"
              fill={open ? color : "#0b1112"}
              stroke={color}
              strokeWidth="1.5"
            />
          </g>
        );
      })}
    </svg>
  );
}

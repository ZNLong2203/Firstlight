import { memo } from "react";

import { effectiveStatus } from "../format";
import { oxygenColor, STATUS_LABEL, STATUS_RING, STATUS_TEXT, textOn } from "../status";
import { PROVINCES, type PondState, type Status } from "../types";

interface Props {
  ponds: PondState[];
  now: number;
  selected: string | null;
  onSelect: (id: string) => void;
}

/**
 * The estate from above: each farm is its four ponds between their dikes, coloured by the oxygen in the
 * water. A ring means a person should look; the small marks along the top are the pond's aerators.
 */
export function EstateMap({ ponds, now, selected, onSelect }: Props) {
  const provinces = new Map<string, Map<string, PondState[]>>();
  for (const pond of ponds) {
    const code = pond.farm?.split("-")[0] ?? "?";
    const farms = provinces.get(code) ?? new Map<string, PondState[]>();
    farms.set(pond.farm, [...(farms.get(pond.farm) ?? []), pond]);
    provinces.set(code, farms);
  }

  return (
    <section aria-labelledby="estate-title">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3 border-b border-ink-700 pb-3">
        <div>
          <h2 id="estate-title" className="font-display text-[24px] leading-none text-paper">
            The estate
          </h2>
          <p className="mt-1.5 text-[12.5px] text-mute">
            {provinces.size} provinces of the Mekong Delta, each farm as its four ponds. Dissolved oxygen in mg/L.
          </p>
        </div>
        <Key />
      </div>
      <div className="divide-y divide-ink-700/70">
        {Object.entries(PROVINCES)
          .filter(([code]) => provinces.has(code))
          .map(([code, name]) => {
            const farms = [...provinces.get(code)!.entries()].sort(([a], [b]) => a.localeCompare(b));
            const all = farms.flatMap(([, list]) => list);
            const statuses = all.map((p) => effectiveStatus(p, now));
            const lowest = Math.min(...all.filter((p) => p.last).map((p) => p.last!.do));
            return (
              <div key={code} className="flex flex-col gap-4 py-5 lg:flex-row lg:gap-8">
                <header className="w-44 shrink-0">
                  <h3 className="font-display text-[19px] leading-tight text-paper">{name}</h3>
                  <p className="mt-1 text-[12px] text-mute">
                    {farms.length} farms · {all.length} ponds
                    {Number.isFinite(lowest) && (
                      <>
                        <br />
                        lowest now <span className="font-mono text-paper-2">{lowest.toFixed(1)}</span>
                      </>
                    )}
                  </p>
                  <Tally statuses={statuses} />
                </header>
                <div className="flex flex-wrap gap-x-5 gap-y-4">
                  {farms.map(([farm, list]) => (
                    <div key={farm}>
                      <div className="mb-1 font-mono text-[10px] tracking-wide text-faint">{farm}</div>
                      {/* The dikes between ponds: an earthen frame around the farm. */}
                      <div className="grid grid-cols-2 gap-[3px] rounded-[5px] bg-[#25261f] p-[3px]">
                        {list
                          .sort((a, b) => a._id.localeCompare(b._id))
                          .map((pond) => (
                            <Pond
                              key={pond._id}
                              pond={pond}
                              status={effectiveStatus(pond, now)}
                              selected={pond._id === selected}
                              onSelect={onSelect}
                            />
                          ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
      </div>
    </section>
  );
}

function Tally({ statuses }: { statuses: Status[] }) {
  const count = (s: Status) => statuses.filter((x) => x === s).length;
  const parts = (["alert", "blind", "watch", "sensor"] as Status[]).filter((s) => count(s) > 0);
  if (!parts.length) return <p className="mt-1 text-[12px] text-sea">all safe</p>;
  return (
    <p className="mt-1 text-[12px]">
      {parts.map((s) => (
        <span key={s} className={`mr-2.5 ${STATUS_TEXT[s]}`}>
          {count(s)} {s === "sensor" ? "probe" : STATUS_LABEL[s].toLowerCase()}
        </span>
      ))}
    </p>
  );
}

function PondView({
  pond,
  status,
  selected,
  onSelect,
}: {
  pond: PondState;
  status: Status;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const last = pond.last;
  const seen = status !== "blind" && last;
  const fill = status === "blind" ? "hatch-fog" : status === "sensor" ? "hatch-lavender" : "";
  const style = seen && status !== "sensor" ? { background: oxygenColor(last.do), color: textOn(last.do) } : undefined;
  const turning = last ? `${last.aerators_running} of ${last.aerators_on} aerators turning` : "";
  return (
    <button
      type="button"
      onClick={() => onSelect(pond._id)}
      title={`${pond._id} · ${STATUS_LABEL[status]}${seen ? ` · ${last.do.toFixed(2)} mg/L · ${turning}` : ""}${
        pond.open_incident ? ` · ${pond.open_incident}` : ""
      }`}
      aria-label={`${pond._id}, ${STATUS_LABEL[status]}${seen ? `, ${last.do.toFixed(1)} milligrams per litre` : ""}`}
      style={style}
      className={`relative h-[38px] w-[50px] rounded-[3px] font-mono text-[11.5px] font-semibold transition-[filter] hover:brightness-110 ${fill} ${
        status === "blind" ? "text-fog" : status === "sensor" ? "text-lavender" : ""
      } ${STATUS_RING[status]} ${selected ? "outline-2 outline-offset-[3px] outline-paper" : ""}`}
    >
      <span className={`absolute inset-x-0 bottom-[5px] text-center ${status === "sensor" ? "line-through" : ""}`}>
        {seen ? last.do.toFixed(1) : "–"}
      </span>
      {last?.aer && status !== "blind" && <Aerators aer={last.aer} />}
      {pond.open_incident && (
        <span className="absolute right-[3px] top-[3px] size-[6px] rounded-full bg-dawn ring-1 ring-ink-950" aria-hidden="true" />
      )}
    </button>
  );
}

const Pond = memo(PondView);

/** One mark per aerator: solid when it turns, hollow when it is off, rust when it is on but not turning. */
function Aerators({ aer }: { aer: { on: boolean; amp: number }[] }) {
  return (
    <span className="absolute left-[4px] top-[4px] flex gap-[2px]" aria-hidden="true">
      {aer.map((a, i) => (
        <span
          key={i}
          className={`size-[4px] rounded-[1px] ${
            a.amp >= 0.5 ? "bg-current opacity-80" : a.on ? "bg-rust ring-1 ring-ink-950" : "border border-current opacity-45"
          }`}
        />
      ))}
    </span>
  );
}

/** The scale and the marks, once, next to the map. */
function Key() {
  const stops = [2.5, 3, 3.5, 4, 4.5, 5, 6, 7];
  const gradient = `linear-gradient(90deg, ${stops.map((v, i) => `${oxygenColor(v)} ${(i / (stops.length - 1)) * 100}%`).join(", ")})`;
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-2 text-[11.5px] text-mute">
      <div>
        <div className="h-2 w-56 rounded-sm" style={{ background: gradient }} />
        <div className="relative mt-1 h-3 w-56 font-mono text-[10px] text-faint">
          {[3, 4, 5, 6].map((v) => (
            <span key={v} className="absolute -translate-x-1/2" style={{ left: `${(stops.indexOf(v) / (stops.length - 1)) * 100}%` }}>
              {v}
            </span>
          ))}
        </div>
      </div>
      <span className="flex items-center gap-1.5">
        <span className="size-3 rounded-[2px] bg-ink-800 ring-2 ring-rust ring-offset-1 ring-offset-ink-950" /> needs a person
      </span>
      <span className="flex items-center gap-1.5">
        <span className="hatch-fog size-3 rounded-[2px]" /> no data
      </span>
      <span className="flex items-center gap-1.5">
        <span className="hatch-lavender size-3 rounded-[2px]" /> probe not trusted
      </span>
      <span className="flex items-center gap-1.5">
        <span className="flex gap-[2px]">
          <span className="size-[5px] rounded-[1px] bg-paper/80" />
          <span className="size-[5px] rounded-[1px] border border-paper/50" />
          <span className="size-[5px] rounded-[1px] bg-rust" />
        </span>
        aerators: turning, off, stopped
      </span>
    </div>
  );
}

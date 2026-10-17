import { effectiveStatus } from "../format";
import { PROVINCES, type PondState, type Status } from "../types";
import { PondTile } from "./PondTile";

interface Props {
  ponds: PondState[];
  now: number;
  selected: string | null;
  onSelect: (id: string) => void;
}

/** Every pond on one screen: provinces as rows, each farm as its four ponds in a 2 × 2 block. */
export function FleetMap({ ponds, now, selected, onSelect }: Props) {
  const provinces = new Map<string, Map<string, PondState[]>>();
  for (const pond of ponds) {
    const code = pond.farm?.split("-")[0] ?? "?";
    const farms = provinces.get(code) ?? new Map<string, PondState[]>();
    farms.set(pond.farm, [...(farms.get(pond.farm) ?? []), pond]);
    provinces.set(code, farms);
  }

  return (
    <div className="divide-y divide-night-700/70">
      {Object.entries(PROVINCES)
        .filter(([code]) => provinces.has(code))
        .map(([code, name]) => {
          const farms = [...provinces.get(code)!.entries()].sort(([a], [b]) => a.localeCompare(b));
          const all = farms.flatMap(([, list]) => list);
          const counts = countBy(all.map((p) => effectiveStatus(p, now)));
          return (
            <section key={code} className="flex flex-col gap-3 py-4 md:flex-row md:items-center md:gap-6">
              <header className="w-36 shrink-0">
                <h2 className="text-sm font-semibold text-slate-200">{name}</h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  {farms.length} farms · {all.length} ponds
                </p>
                {counts.alert + counts.watch + counts.blind + counts.sensor > 0 && (
                  <p className="mt-1 flex flex-wrap gap-x-2 text-xs font-medium">
                    {counts.alert > 0 && <span className="text-red-400">{counts.alert} alert</span>}
                    {counts.blind > 0 && <span className="text-slate-400">{counts.blind} blind</span>}
                    {counts.watch > 0 && <span className="text-amber-300">{counts.watch} watch</span>}
                    {counts.sensor > 0 && <span className="text-violet-300">{counts.sensor} sensor</span>}
                  </p>
                )}
              </header>
              <div className="flex flex-wrap gap-x-5 gap-y-3">
                {farms.map(([farm, list]) => (
                  <div key={farm}>
                    <div className="mb-1 font-mono text-[10px] text-slate-500">{farm}</div>
                    <div className="grid grid-cols-2 gap-1">
                      {list
                        .sort((a, b) => a._id.localeCompare(b._id))
                        .map((pond) => (
                          <PondTile
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
            </section>
          );
        })}
    </div>
  );
}

export function countBy(statuses: Status[]): Record<Status, number> {
  const counts: Record<Status, number> = { ok: 0, watch: 0, alert: 0, sensor: 0, blind: 0 };
  for (const status of statuses) counts[status] += 1;
  return counts;
}

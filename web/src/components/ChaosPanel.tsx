import { useCallback, useEffect, useMemo, useState } from "react";

import { demoFetch } from "../demo";
import { clockTime } from "../format";
import type { Fault, PondState } from "../types";

const KIND_LABEL: Record<string, string> = {
  aerator_trip: "Aerator tripped",
  probe_fouling: "Probe fouling",
  gateway_offline: "4G link cut",
  power_outage: "Power cut",
};

interface Props {
  ponds: PondState[];
  selected: string | null;
  offsetHours: number;
  demoCode: string;
  onDemoCode: (code: string) => void;
  onReport: () => void;
}

/** Break the simulated world for real. Needs the demo code; every fault is recorded as ground truth. */
export function ChaosPanel({ ponds, selected, offsetHours, demoCode, onDemoCode, onReport }: Props) {
  const [open, setOpen] = useState(false);
  const [faults, setFaults] = useState<Fault[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [choice, setChoice] = useState<string>("");
  const pondId = choice || (selected && !selected.startsWith("INC-") ? selected : "") || ponds[0]?._id || "";
  const pond = ponds.find((p) => p._id === pondId);

  const farms = useMemo(() => {
    const groups = new Map<string, string[]>();
    for (const p of [...ponds].sort((a, b) => a._id.localeCompare(b._id))) {
      groups.set(p.farm, [...(groups.get(p.farm) ?? []), p._id]);
    }
    return [...groups.entries()];
  }, [ponds]);

  const refresh = useCallback(
    async (code: string) => {
      try {
        setFaults(await demoFetch<Fault[]>("/v1/chaos", code));
        setError("");
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : "not reachable");
        return false;
      }
    },
    [],
  );

  useEffect(() => {
    if (!open || !demoCode) return;
    void refresh(demoCode);
    const timer = setInterval(() => void refresh(demoCode), 5_000);
    return () => clearInterval(timer);
  }, [open, demoCode, refresh]);

  const unlock = async () => {
    if (await refresh(draft)) {
      onDemoCode(draft);
      setDraft("");
    }
  };

  const inject = async (body: Record<string, string>) => {
    setBusy(true);
    try {
      await demoFetch("/v1/chaos", demoCode, { method: "POST", body: JSON.stringify(body) });
      await refresh(demoCode);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  const repair = async (id: string) => {
    setBusy(true);
    try {
      await demoFetch(`/v1/chaos/${id}`, demoCode, { method: "DELETE" });
      await refresh(demoCode);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  const active = faults.filter((f) => f.status === "active");

  return (
    <div className="fixed bottom-5 left-5 z-40 flex flex-col items-start gap-2">
      {open && (
        <div className="w-[min(24rem,calc(100vw-2.5rem))] rounded-md border border-ink-600 bg-ink-900 p-5 shadow-[0_24px_60px_rgba(0,0,0,0.55)]">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-[21px] text-paper">Break something</h2>
            {demoCode && (
              <button type="button" onClick={() => onDemoCode("")} className="text-[12px] text-mute hover:text-paper">
                Lock
              </button>
            )}
          </div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-paper-2">
            Each fault really happens in the simulated farms. Firstlight is not told which one: it has to work it out.
          </p>

          {!demoCode ? (
            <form
              className="mt-4 flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                void unlock();
              }}
            >
              <input
                type="password"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Demo code"
                aria-label="Demo code"
                className="min-w-0 flex-1 rounded-[4px] border border-ink-600 bg-ink-950 px-3 py-2 text-[13px] text-paper outline-none placeholder:text-faint focus:border-dawn"
              />
              <button type="submit" className="rounded-[4px] bg-dawn px-3.5 py-2 text-[13px] font-medium text-ink-950 hover:bg-dawn-soft">
                Unlock
              </button>
            </form>
          ) : (
            <>
              <label className="mt-4 block text-[12px] text-mute">
                On pond
                <select
                  value={pondId}
                  onChange={(event) => setChoice(event.target.value)}
                  className="mt-1 block w-full rounded-[4px] border border-ink-600 bg-ink-950 px-2.5 py-2 font-mono text-[13px] text-paper"
                >
                  {farms.map(([farm, ids]) => (
                    <optgroup key={farm} label={farm}>
                      {ids.map((id) => (
                        <option key={id} value={id}>
                          {id}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </label>
              {pond && (
                <ul className="mt-3 divide-y divide-ink-700 border-y border-ink-700">
                  <Fault busy={busy} onClick={() => void inject({ kind: "aerator_trip", pond: pond._id })} title="Trip the main aerator">
                    It stops drawing current and the oxygen starts to fall.
                  </Fault>
                  <Fault busy={busy} onClick={() => void inject({ kind: "probe_fouling", pond: pond._id })} title="Foul the oxygen probe">
                    Biofilm drags the reading down while the water stays healthy.
                  </Fault>
                  <Fault busy={busy} onClick={() => void inject({ kind: "gateway_offline", gateway: pond.gateway })} title={`Cut the 4G link of ${pond.gateway}`}>
                    The gateway keeps its readings and sends them when it can.
                  </Fault>
                  <Fault busy={busy} onClick={() => void inject({ kind: "power_outage", farm: pond.farm })} title={`Cut the power to farm ${pond.farm}`}>
                    Every aerator on the farm stops at once.
                  </Fault>
                </ul>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void (async () => {
                    setBusy(true);
                    try {
                      await demoFetch("/v1/reports/run", demoCode, { method: "POST" });
                      onReport();
                    } catch (e) {
                      setError(e instanceof Error ? e.message : "failed");
                    } finally {
                      setBusy(false);
                    }
                  })()
                }
                className="mt-3 text-[12.5px] text-dawn-soft underline decoration-dawn/40 underline-offset-4 transition-colors hover:text-dawn disabled:opacity-50"
              >
                Write the dawn report now, for the last 12 hours
              </button>
              <h3 className="mt-5 font-display text-[15px] text-paper">Faults in place</h3>
              {active.length === 0 ? (
                <p className="mt-1 text-[12.5px] text-mute">None. The farms are as they should be.</p>
              ) : (
                <ul className="mt-1 divide-y divide-ink-700">
                  {active.map((fault) => (
                    <li key={fault._id} className="flex items-center justify-between gap-2 py-2 text-[12.5px]">
                      <span className="min-w-0">
                        <span className="text-paper">{KIND_LABEL[fault.kind] ?? fault.kind}</span>
                        <span className="ml-1.5 font-mono text-[11.5px] text-mute">
                          {fault.device ?? fault.pond ?? fault.gateway ?? fault.farm} · {clockTime(fault.started_at, offsetHours)}
                        </span>
                      </span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void repair(fault._id)}
                        className="shrink-0 text-[12.5px] text-sea underline decoration-sea/40 underline-offset-4 hover:text-paper disabled:opacity-50"
                      >
                        Repair
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {error && <p className="mt-3 text-[12px] text-rust">{error}</p>}
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-baseline gap-2 rounded-md border border-ink-600 bg-ink-900 px-4 py-2.5 shadow-[0_10px_30px_rgba(0,0,0,0.5)] transition-colors hover:border-dawn/60"
      >
        <span className="font-display text-[15px] italic text-paper">Chaos panel</span>
        {active.length > 0 && (
          <span className="font-mono text-[12px] text-dawn">
            {active.length} {active.length === 1 ? "fault" : "faults"}
          </span>
        )}
      </button>
    </div>
  );
}

function Fault({ busy, onClick, title, children }: { busy: boolean; onClick: () => void; title: string; children: React.ReactNode }) {
  return (
    <li>
      <button
        type="button"
        disabled={busy}
        onClick={onClick}
        className="group block w-full py-2.5 text-left transition-colors hover:bg-ink-850 disabled:opacity-50"
      >
        <span className="block text-[13px] text-paper group-hover:text-dawn-soft">{title}</span>
        <span className="block text-[12px] text-mute">{children}</span>
      </button>
    </li>
  );
}

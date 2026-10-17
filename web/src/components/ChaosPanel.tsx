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
    <div className="fixed bottom-4 left-4 z-40 flex flex-col items-start gap-2">
      {open && (
        <div className="w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-night-700 bg-night-900/95 p-4 shadow-2xl shadow-black/60 backdrop-blur">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Chaos panel</h2>
            {demoCode && (
              <button type="button" onClick={() => onDemoCode("")} className="text-[11px] text-slate-500 hover:text-slate-300">
                Lock
              </button>
            )}
          </div>
          <p className="mt-1 text-[11px] leading-snug text-slate-500">
            Each button breaks something in the simulated world for real. Firstlight is not told what: it has to work it out.
          </p>

          {!demoCode ? (
            <form
              className="mt-3 flex gap-2"
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
                className="min-w-0 flex-1 rounded-md bg-night-800 px-2.5 py-1.5 text-sm text-white ring-1 ring-night-700 outline-none focus:ring-sky-400"
              />
              <button type="submit" className="rounded-md bg-sky-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-400">
                Unlock
              </button>
            </form>
          ) : (
            <>
              <label className="mt-3 block text-[11px] text-slate-400">
                Pond
                <select
                  value={pondId}
                  onChange={(event) => setChoice(event.target.value)}
                  className="mt-1 block w-full rounded-md bg-night-800 px-2 py-1.5 font-mono text-sm text-white ring-1 ring-night-700"
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
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <ChaosButton busy={busy} onClick={() => void inject({ kind: "aerator_trip", pond: pond._id })}>
                    Trip main aerator
                  </ChaosButton>
                  <ChaosButton busy={busy} onClick={() => void inject({ kind: "probe_fouling", pond: pond._id })}>
                    Foul the DO probe
                  </ChaosButton>
                  <ChaosButton busy={busy} onClick={() => void inject({ kind: "gateway_offline", gateway: pond.gateway })}>
                    Cut 4G of {pond.gateway}
                  </ChaosButton>
                  <ChaosButton busy={busy} onClick={() => void inject({ kind: "power_outage", farm: pond.farm })}>
                    Cut power of {pond.farm}
                  </ChaosButton>
                </div>
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
                className="mt-2 w-full rounded-md bg-indigo-500/15 px-2.5 py-2 text-left text-xs font-medium text-indigo-100 ring-1 ring-indigo-400/30 transition hover:bg-indigo-500/25 disabled:opacity-50"
              >
                Write the dawn report now (last 12 hours)
              </button>
              <h3 className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Active faults</h3>
              {active.length === 0 ? (
                <p className="mt-1 text-xs text-slate-500">None. The world is as it should be.</p>
              ) : (
                <ul className="mt-1 space-y-1.5">
                  {active.map((fault) => (
                    <li key={fault._id} className="flex items-center justify-between gap-2 rounded-md bg-night-800 px-2.5 py-1.5 text-xs">
                      <span className="min-w-0">
                        <span className="text-slate-200">{KIND_LABEL[fault.kind] ?? fault.kind}</span>
                        <span className="ml-1.5 font-mono text-slate-500">
                          {fault.device ?? fault.pond ?? fault.gateway ?? fault.farm} · {clockTime(fault.started_at, offsetHours)}
                        </span>
                      </span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void repair(fault._id)}
                        className="shrink-0 rounded bg-emerald-500/20 px-2 py-0.5 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
                      >
                        Repair
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {error && <p className="mt-2 text-[11px] text-red-300">{error}</p>}
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-full border border-night-700 bg-night-900/95 px-3.5 py-2 text-xs font-semibold text-slate-200 shadow-lg shadow-black/50 backdrop-blur transition hover:border-orange-400/60 hover:text-white"
      >
        <svg viewBox="0 0 20 20" className="size-4 text-orange-400" fill="currentColor" aria-hidden="true">
          <path d="M11.3 1.5 3.5 11.2h5.4l-1.2 7.3 7.8-9.7H10z" />
        </svg>
        Chaos{active.length > 0 ? ` · ${active.length}` : ""}
      </button>
    </div>
  );
}

function ChaosButton({ busy, onClick, children }: { busy: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onClick}
      className="rounded-md bg-orange-500/15 px-2.5 py-2 text-left text-xs font-medium text-orange-100 ring-1 ring-orange-500/30 transition hover:bg-orange-500/25 disabled:opacity-50"
    >
      {children}
    </button>
  );
}

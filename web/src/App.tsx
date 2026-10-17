import { useCallback, useEffect, useMemo, useState } from "react";

import { Attention } from "./components/Attention";
import { countBy, FleetMap } from "./components/FleetMap";
import { PondDrawer } from "./components/PondDrawer";
import { TopBar } from "./components/TopBar";
import { effectiveStatus } from "./format";
import type { Meta } from "./types";
import { useLivePonds, useNow } from "./useLive";

/** The selected pond lives in the URL hash, so an alert can link straight to it. */
function useSelectedPond(): [string | null, (id: string | null) => void] {
  const read = () => decodeURIComponent(window.location.hash.slice(1)) || null;
  const [selected, setSelected] = useState<string | null>(read);
  useEffect(() => {
    const onHash = () => setSelected(read());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const select = useCallback((id: string | null) => {
    setSelected(id);
    window.history.replaceState(null, "", id ? `#${encodeURIComponent(id)}` : window.location.pathname);
  }, []);
  return [selected, select];
}

function useMeta(): Meta | null {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    fetch("/v1/meta")
      .then((r) => (r.ok ? (r.json() as Promise<Meta>) : null))
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);
  return meta;
}

export function App() {
  const { ponds, link } = useLivePonds();
  const now = useNow();
  const meta = useMeta();
  const [selected, select] = useSelectedPond();
  const list = useMemo(() => [...ponds.values()], [ponds]);
  const counts = countBy(list.map((p) => effectiveStatus(p, now)));
  const offset = meta?.farm_clock_offset_hours ?? null;
  const open = selected ? ponds.get(selected) : undefined;
  const toggle = useCallback((id: string) => select(id === selected ? null : id), [select, selected]);
  const close = useCallback(() => select(null), [select]);

  useEffect(() => {
    document.title = counts.alert ? `(${counts.alert}) Firstlight` : "Firstlight";
  }, [counts.alert]);

  return (
    <div className="min-h-dvh">
      <TopBar now={now} offsetHours={offset} counts={counts} link={link} />
      {link === "reconnecting" && (
        <div className="bg-amber-400/15 px-4 py-2 text-center text-sm text-amber-200" role="alert">
          Connection to the farms lost. Reconnecting; the values below may be out of date.
        </div>
      )}
      <main
        className={`mx-auto max-w-[1600px] space-y-8 px-4 py-6 transition-opacity sm:px-6 ${
          open ? "xl:pr-[544px]" : ""
        } ${link === "live" ? "" : "opacity-60"}`}
      >
        {link === "connecting" && list.length === 0 ? (
          <p className="py-20 text-center text-sm text-slate-500">Connecting to the farms…</p>
        ) : list.length === 0 ? (
          <p className="py-20 text-center text-sm text-slate-500">Waiting for the first gateway to report.</p>
        ) : (
          <>
            <section aria-labelledby="attention-title">
              <h2 id="attention-title" className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                Needs attention
              </h2>
              <Attention ponds={list} now={now} selected={selected} onSelect={toggle} />
            </section>
            <section aria-labelledby="fleet-title">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h2 id="fleet-title" className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                  All ponds · dissolved oxygen, mg/L
                </h2>
                <Legend />
              </div>
              <FleetMap ponds={list} now={now} selected={selected} onSelect={toggle} />
            </section>
          </>
        )}
      </main>
      {open && <PondDrawer pond={open} now={now} offsetHours={offset ?? 0} onClose={close} />}
    </div>
  );
}

function Legend() {
  const items = [
    ["bg-emerald-500/40", "Safe"],
    ["bg-amber-400/60", "Watch: under 4, falling or an aerator down"],
    ["bg-red-500", "Alert: under 3 within 30 min"],
    ["blind-hatch ring-1 ring-slate-500/50", "Blind: no data"],
  ];
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
      {items.map(([swatch, label]) => (
        <li key={label} className="flex items-center gap-1.5">
          <span className={`size-2.5 rounded-sm ${swatch}`} />
          {label}
        </li>
      ))}
    </ul>
  );
}

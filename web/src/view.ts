import { useCallback, useEffect, useState } from "react";

export type View = "ponds" | "incidents" | "night";

export const VIEWS: { id: View; label: string }[] = [
  { id: "ponds", label: "Ponds" },
  { id: "incidents", label: "Incidents" },
  { id: "night", label: "The night" },
];

function read(): View {
  const value = new URLSearchParams(window.location.search).get("view");
  return VIEWS.some((v) => v.id === value) ? (value as View) : "ponds";
}

/** The open tab lives in the query string, so a link can open it; the hash stays the selected pond. */
export function useView(): [View, (view: View) => void] {
  const [view, setView] = useState<View>(read);
  useEffect(() => {
    const onPop = () => setView(read());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const select = useCallback((next: View) => {
    setView(next);
    const url = new URL(window.location.href);
    if (next === "ponds") url.searchParams.delete("view");
    else url.searchParams.set("view", next);
    window.history.pushState(null, "", url);
    window.scrollTo({ top: 0 });
  }, []);
  return [view, select];
}

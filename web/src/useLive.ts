import { useEffect, useRef, useState } from "react";

import type { Incident, PondState } from "./types";

export type Link = "connecting" | "live" | "reconnecting";

const SILENT_MS = 25_000; // two missed heartbeats: the connection is dead even if the browser has not noticed

/**
 * Live pond states over server-sent events: a snapshot on connect, then one batch of changes per second
 * and a heartbeat every 10 s. Every (re)connect starts from a fresh snapshot.
 */
export function useLivePonds() {
  const [ponds, setPonds] = useState<Map<string, PondState>>(new Map());
  const [incidents, setIncidents] = useState<Map<string, Incident>>(new Map());
  const [link, setLink] = useState<Link>("connecting");
  const lastEvent = useRef(Date.now());

  useEffect(() => {
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    const parse = <T = PondState>(event: Event) => JSON.parse((event as MessageEvent<string>).data) as T[];
    const heard = () => {
      lastEvent.current = Date.now();
    };

    const connect = () => {
      lastEvent.current = Date.now();
      const current = new EventSource("/v1/stream");
      source = current;
      current.addEventListener("snapshot", (event) => {
        attempt = 0;
        setPonds(new Map(parse(event).map((p) => [p._id, p])));
        setIncidents(new Map()); // the open and recent incidents follow right after
        setLink("live");
        heard();
      });
      current.addEventListener("incidents", (event) => {
        const changed = parse<Incident>(event);
        setIncidents((previous) => {
          const next = new Map(previous);
          for (const incident of changed) next.set(incident._id, incident);
          return next;
        });
        heard();
      });
      current.addEventListener("ponds", (event) => {
        const changed = parse(event);
        setPonds((previous) => {
          const next = new Map(previous);
          for (const pond of changed) next.set(pond._id, pond);
          return next;
        });
        heard();
      });
      current.addEventListener("tick", heard);
      current.onerror = () => {
        setLink("reconnecting");
        // The browser retries a dropped stream by itself, but gives up on an HTTP error such as the
        // 502 the proxy returns while the API restarts. Then it is up to us, with backoff.
        if (current.readyState === EventSource.CLOSED) reconnect();
      };
    };
    const reconnect = () => {
      source?.close();
      clearTimeout(retry);
      retry = setTimeout(connect, Math.min(30_000, 1000 * 2 ** attempt++));
    };

    connect();
    const watchdog = setInterval(() => {
      if (Date.now() - lastEvent.current > SILENT_MS) {
        setLink("reconnecting");
        lastEvent.current = Date.now(); // one reconnect per silent period
        reconnect();
      }
    }, 5_000);
    return () => {
      clearInterval(watchdog);
      clearTimeout(retry);
      source?.close();
    };
  }, []);

  return { ponds, incidents, link };
}

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

import { useEffect, useState } from "react";

type Health = { status: string; mongo: string; version: string };

export function App() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    fetch("/v1/healthz")
      .then((r) => r.json() as Promise<Health>)
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <main className="shell">
      <h1>Firstlight</h1>
      <p className="tagline">Every pond makes it to morning.</p>
      <p className="muted">The night board is being built.</p>
      <p className="status">
        API {health ? `${health.status} · MongoDB ${health.mongo} · ${health.version}` : "not reachable yet"}
      </p>
    </main>
  );
}

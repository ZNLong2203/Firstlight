import { useCallback, useState } from "react";

const KEY = "firstlight.demo-code";

function load(): string {
  try {
    return window.localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

/** The demo code unlocks the chaos panel and approvals. Kept per browser, never sent anywhere else. */
export function useDemoCode(): [string, (code: string) => void] {
  const [code, setCode] = useState(load);
  const save = useCallback((next: string) => {
    setCode(next);
    try {
      if (next) window.localStorage.setItem(KEY, next);
      else window.localStorage.removeItem(KEY);
    } catch {
      // private mode: the code lasts for this page only
    }
  }, []);
  return [code, save];
}

export async function demoFetch<T>(path: string, code: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Demo-Code": code, ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}) as { detail?: string });
    throw new Error((detail as { detail?: string }).detail ?? `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

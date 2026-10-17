import type { PondState, Status } from "./types";

export const HYPOXIA_MGL = 3;
export const SAFE_MGL = 4;
const NO_DATA_S = 120; // the brain marks a pond blind after 60 s; the console also checks on its own

export const STATUS_LABEL: Record<Status, string> = { ok: "Safe", watch: "Watch", alert: "Alert", blind: "Blind" };

/** The brain's status, unless the last reading is so old that the brain itself may have stopped. */
export function effectiveStatus(pond: PondState, now: number): Status {
  if (!pond.last || now - Date.parse(pond.last.ts) > NO_DATA_S * 1000) return "blind";
  return pond.status ?? "ok";
}

/** Sort key for the attention queue: hypoxia now, then soonest forecast, then blind, then watch. */
export function urgency(pond: PondState, status: Status): number {
  const minutes = pond.forecast?.minutes_to_hypoxia ?? 10_000;
  if (status === "alert") return pond.last && pond.last.do <= HYPOXIA_MGL ? 0 : 1 + minutes;
  if (status === "blind") return 20_000;
  if (status === "watch") return 30_000 + minutes;
  return 100_000;
}

/** Why a pond is not safe, in the order the brain checks it. */
export function reasons(pond: PondState, status: Status, now: number): string[] {
  const last = pond.last;
  if (status === "blind" || !last) return [last ? `No data for ${ago((now - Date.parse(last.ts)) / 1000)}` : "No data yet"];
  const out: string[] = [];
  const minutes = pond.forecast?.minutes_to_hypoxia;
  if (last.do <= HYPOXIA_MGL) out.push("Below 3 mg/L now");
  else if (minutes != null) out.push(`3 mg/L in ${Math.round(minutes)} min`);
  else if (last.do < SAFE_MGL) out.push("Below 4 mg/L");
  if (last.aerators_running < last.aerators_on) {
    out.push(`${last.aerators_running} of ${last.aerators_on} aerators turning`);
  }
  return out;
}

export function ago(seconds: number): string {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

export function perHour(slopePerMin: number | undefined): string {
  if (slopePerMin == null) return "–";
  const value = slopePerMin * 60;
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}`;
}

/** The farm clock is real time shifted by a fixed offset, so a demo by day can run on a farm at night. */
export function farmClock(now: number, offsetHours: number): Date {
  return new Date(now + offsetHours * 3_600_000);
}

export function hhmm(date: Date): string {
  return `${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")}`;
}

/** Minutes since 18:00 on the farm clock while it is night (18:00 to 06:00), otherwise null. */
export function nightElapsed(farm: Date): number | null {
  const minutes = farm.getUTCHours() * 60 + farm.getUTCMinutes();
  if (minutes >= 18 * 60) return minutes - 18 * 60;
  if (minutes < 6 * 60) return minutes + 6 * 60;
  return null;
}

export function duration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h} h ${String(m).padStart(2, "0")} min` : `${m} min`;
}

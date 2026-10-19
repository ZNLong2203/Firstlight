import type { Incident, PondState, Status, TimelineEntry } from "./types";

export const HYPOXIA_MGL = 3;
export const SAFE_MGL = 4;
const NO_DATA_S = 120; // the brain marks a pond blind after 60 s; the console also checks on its own


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
  if (status === "sensor") return 50_000;
  return 100_000;
}

/** Why a pond is not safe, in the order the brain checks it. */
export function reasons(pond: PondState, status: Status, now: number): string[] {
  const last = pond.last;
  if (status === "blind" || !last) return [last ? `No data for ${ago((now - Date.parse(last.ts)) / 1000)}` : "No data yet"];
  if (status === "sensor") return ["Probe reads wrong", "Cleaning ticket open, nobody woken"];
  const out: string[] = [];
  const minutes = pond.forecast?.minutes_to_hypoxia;
  if (last.do <= HYPOXIA_MGL) out.push("Below 3 mg/L now");
  else if (minutes != null) out.push(`3 mg/L in ${Math.round(minutes)} min`);
  else if (last.do < SAFE_MGL) out.push("Below 4 mg/L");
  const repairs = pond.repair_tickets ?? [];
  if (repairs.length) out.push(`Running on its standby; ${repairs.map((t) => t.device).join(", ")} awaits repair`);
  else if (last.aerators_running < last.aerators_on) {
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

export const VIETNAM_UTC_OFFSET = 7;

/** The farm clock: real time at the farms' UTC offset, Vietnam time unless the simulator is shifted. */
export function farmClock(now: number, offsetHours: number): Date {
  return new Date(now + offsetHours * 3_600_000);
}

export function clockName(offsetHours: number): string {
  return offsetHours === VIETNAM_UTC_OFFSET ? "Vietnam time" : "farm time";
}

/** Minutes until 18:00 on the farm clock during the day, otherwise null. */
export function minutesToNight(farm: Date): number | null {
  const minutes = farm.getUTCHours() * 60 + farm.getUTCMinutes();
  return minutes >= 6 * 60 && minutes < 18 * 60 ? 18 * 60 - minutes : null;
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

export function clockTime(iso: string | undefined, offsetHours: number, seconds = false): string {
  if (!iso) return "--:--";
  const date = farmClock(Date.parse(iso), offsetHours);
  const base = hhmm(date);
  return seconds ? `${base}:${String(date.getUTCSeconds()).padStart(2, "0")}` : base;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A time on the farm clock, with its day when that day is not today. */
export function clockDay(iso: string | undefined, offsetHours: number): string {
  if (!iso) return "--:--";
  const date = farmClock(Date.parse(iso), offsetHours);
  const today = farmClock(Date.now(), offsetHours);
  if (date.toISOString().slice(0, 10) === today.toISOString().slice(0, 10)) return hhmm(date);
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${hhmm(date)}`;
}

export const CAUSE_LABEL: Record<string, string> = {
  aerator_failure: "Aerator failure",
  power_outage: "Power cut",
  sensor_fault: "Probe fault",
  gateway_offline: "Gateway offline",
  ingest_regression: "Ingest stopped",
  unknown: "Unexplained",
};

const SIGNAL_LABEL: Record<string, string> = {
  aerator_down: "an aerator stopped turning",
  hypoxia_risk: "heading for 3 mg/L",
  no_data: "no data",
  probe_degraded: "probe signal weak",
  fast_drop: "DO falling fast",
  gateway_silent: "the gateway went silent",
  farm_dark: "every aerator on the farm stopped",
  fleet_silent: "most gateways went silent",
};

const ESCALATION_LABEL: Record<string, string> = {
  command_failed: "a command could not be carried out",
  standby_idle: "the standby aerator is on but not turning",
  no_recovery: "oxygen has not recovered",
};

export function target(incident: Incident): string {
  if (incident.scope === "pond") return `Pond ${incident.pond}`;
  if (incident.scope === "gateway") return `Gateway ${incident.gateway} · ${incident.ponds.length} ponds`;
  if (incident.scope === "farm") return `Farm ${incident.farm} · ${incident.ponds.length} ponds`;
  return `${incident.ponds.length} ponds across the estate`;
}

/** One line of an incident timeline in plain words. */
export function describe(entry: TimelineEntry): string {
  const text = (key: string) => String(entry[key] ?? "");
  switch (entry.kind) {
    case "detected":
      return `Detected: ${((entry.signals as string[]) ?? []).map((s) => SIGNAL_LABEL[s] ?? s).join(", ")}`;
    case "diagnosed":
      return `Diagnosed: ${CAUSE_LABEL[text("cause")] ?? text("cause")}, ${Math.round(Number(entry.confidence) * 100)}% sure`;
    case "action_sent":
      return `Sent ${text("action")}${entry.device ? ` to ${text("device")}` : ""}`;
    case "action_done":
      return `${entry.device ? text("device") : text("action")} confirmed by the gateway`;
    case "action_failed":
      return `${text("action")} failed on the gateway`;
    case "action_expired":
      return `${text("action")} was never acknowledged`;
    case "notify":
      return `Message to the ${text("to")}: “${text("text")}”`;
    case "ticket":
      return `Ticket: ${text("text")}`;
    case "ticket_closed":
      return `Ticket closed: ${text("detail")}`;
    case "verifying":
      return `Verifying: ${text("detail")}`;
    case "approval_requested":
      return `Waiting for a person to approve ${text("action")}`;
    case "approved":
      return `${text("action")} approved`;
    case "no_standby":
      return "No standby aerator left to start";
    case "telegram":
      return `Sent on Telegram to the ${text("to")}`;
    case "acknowledged":
      return `${text("by")} acknowledged on Telegram`;
    case "unacknowledged":
      return "Nobody acknowledged in 3 min: reminded on Telegram";
    case "ai_investigation": {
      const verdict =
        entry.agrees == null ? ", where the rules had no answer" : entry.agrees ? ", agrees with the rules" : ", disagrees with the rules";
      return `AI investigator: ${CAUSE_LABEL[text("cause")] ?? text("cause")}${verdict}`;
    }
    case "datadog": {
      const count = Number(entry.count ?? 1);
      const groups = count > 1 ? ` on ${count} ${entry.per ? `${text("per")}s` : "groups"}` : "";
      const after = entry.after_brain_s != null ? `, ${text("after_brain_s")} s after Firstlight` : "";
      return `Datadog ${text("transition")}: ${text("monitor")}${groups}${after}`;
    }
    case "escalated":
      return `Escalated: ${ESCALATION_LABEL[text("detail")] ?? text("detail")}`;
    case "notebook":
      return "The proof of recovery is in a Datadog notebook";
    case "resolved":
      return entry.gap ? "Data back; the blind spell was checked" : entry.note ? `Closed: ${text("note")}` : "Recovered";
    default:
      return entry.kind;
  }
}

/** The step a person most needs to see on a card. */
export function headline(incident: Incident): TimelineEntry | undefined {
  const skip = new Set(["notify"]);
  return [...incident.timeline].reverse().find((entry) => !skip.has(entry.kind));
}

export function seconds(value: number | null | undefined): string {
  if (value == null) return "–";
  return value < 90 ? `${value} s` : `${(value / 60).toFixed(1)} min`;
}

/** Vietnamese dong, rounded the way people say it: 1.2 bn, 850 m. */
export function vnd(value: number | null | undefined): string {
  if (!value) return "–";
  return value >= 1e9 ? `${(value / 1e9).toFixed(1)} bn VND` : `${Math.round(value / 1e6)} m VND`;
}

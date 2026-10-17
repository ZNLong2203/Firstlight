import type { IncidentStatus, Status } from "./types";

/** Every status colour in one place: tiles, cards, badges and dots stay consistent. */
export const STATUS_LABEL: Record<Status, string> = {
  ok: "Safe",
  watch: "Watch",
  alert: "Alert",
  sensor: "Sensor",
  blind: "Blind",
};

export const STATUS_ORDER: Status[] = ["alert", "blind", "watch", "sensor", "ok"];

export const TILE: Record<Status, string> = {
  ok: "bg-emerald-500/15 text-emerald-200 ring-emerald-400/25 hover:bg-emerald-500/25",
  watch: "bg-amber-400/25 text-amber-100 ring-amber-300/60 hover:bg-amber-400/35",
  alert: "bg-red-500/80 text-white ring-red-300/80 alert-glow hover:bg-red-500",
  sensor: "bg-violet-500/25 text-violet-100 ring-violet-300/60 hover:bg-violet-500/35",
  blind: "blind-hatch text-slate-400 ring-slate-500/40 hover:ring-slate-300/60",
};

export const CARD: Record<Status, string> = {
  alert: "border-red-500/70 bg-red-500/10 alert-glow",
  blind: "border-slate-500/50 bg-night-800 blind-hatch",
  watch: "border-amber-400/50 bg-amber-400/[0.06]",
  sensor: "border-violet-400/50 bg-violet-500/[0.07]",
  ok: "border-night-700 bg-night-800",
};

export const BADGE: Record<Status, string> = {
  alert: "bg-red-500 text-white",
  blind: "bg-slate-600 text-slate-100",
  watch: "bg-amber-400 text-night-950",
  sensor: "bg-violet-400 text-night-950",
  ok: "bg-emerald-500 text-night-950",
};

export const DOT: Record<Status, string> = {
  alert: "bg-red-500",
  watch: "bg-amber-400",
  sensor: "bg-violet-400",
  blind: "bg-slate-400",
  ok: "bg-emerald-400",
};

export const LEGEND: [string, string][] = [
  ["bg-emerald-500/40", "Safe"],
  ["bg-amber-400/60", "Watch: under 4, falling or an aerator down"],
  ["bg-red-500", "Alert: under 3 within 30 min"],
  ["bg-violet-400/70", "Sensor: probe wrong, ticket open"],
  ["blind-hatch ring-1 ring-slate-500/50", "Blind: no data"],
];

export const INCIDENT_LABEL: Record<IncidentStatus, string> = {
  investigating: "Investigating",
  mitigating: "Acting",
  verifying: "Verifying",
  monitoring: "Watching blind",
  awaiting_approval: "Needs approval",
  escalated: "Escalated",
  resolved: "Resolved",
  dismissed: "False alarm stopped",
};

export const INCIDENT_BADGE: Record<IncidentStatus, string> = {
  investigating: "bg-sky-400 text-night-950",
  mitigating: "bg-amber-400 text-night-950",
  verifying: "bg-teal-300 text-night-950",
  monitoring: "bg-slate-500 text-white",
  awaiting_approval: "bg-orange-500 text-white",
  escalated: "bg-red-500 text-white",
  resolved: "bg-emerald-500 text-night-950",
  dismissed: "bg-violet-400 text-night-950",
};

export const INCIDENT_CARD: Record<IncidentStatus, string> = {
  investigating: "border-sky-400/60 bg-sky-400/[0.07]",
  mitigating: "border-amber-400/60 bg-amber-400/[0.07]",
  verifying: "border-teal-300/60 bg-teal-300/[0.06]",
  monitoring: "border-slate-500/60 bg-night-800 blind-hatch",
  awaiting_approval: "border-orange-500/80 bg-orange-500/10 alert-glow",
  escalated: "border-red-500/80 bg-red-500/10 alert-glow",
  resolved: "border-emerald-500/30 bg-emerald-500/[0.05]",
  dismissed: "border-violet-400/30 bg-violet-500/[0.05]",
};

/** Most urgent first. */
export const INCIDENT_ORDER: IncidentStatus[] = [
  "escalated",
  "awaiting_approval",
  "investigating",
  "mitigating",
  "monitoring",
  "verifying",
  "resolved",
  "dismissed",
];

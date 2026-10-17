import type { IncidentStatus, Status } from "./types";

/** Every status colour in one place, so the map, the queue and the drawers say the same thing. */
export const STATUS_LABEL: Record<Status, string> = {
  ok: "Safe",
  watch: "Watch",
  alert: "Alert",
  sensor: "Probe not trusted",
  blind: "Blind",
};

export const STATUS_ORDER: Status[] = ["alert", "blind", "watch", "sensor", "ok"];

export const STATUS_TEXT: Record<Status, string> = {
  alert: "text-rust",
  blind: "text-fog",
  watch: "text-ochre",
  sensor: "text-lavender",
  ok: "text-sea",
};

/** The ring around a pond on the map: only for ponds that need a person. */
export const STATUS_RING: Record<Status, string> = {
  alert: "ring-2 ring-rust ring-offset-2 ring-offset-ink-900",
  watch: "ring-[1.5px] ring-ochre ring-offset-1 ring-offset-ink-900",
  blind: "",
  sensor: "",
  ok: "",
};

/** Dissolved oxygen as the colour of the water: deep teal when it is rich, sand near 4, rust under 3. */
const OXYGEN: [number, [number, number, number]][] = [
  [2.5, [140, 44, 40]],
  [3.0, [181, 72, 46]],
  [3.5, [205, 120, 58]],
  [4.0, [204, 168, 82]],
  [4.5, [118, 165, 136]],
  [5.0, [66, 142, 133]],
  [6.0, [44, 112, 120]],
  [7.0, [38, 90, 108]],
];

function oxygenRgb(mgl: number): [number, number, number] {
  if (mgl <= OXYGEN[0][0]) return OXYGEN[0][1];
  for (let i = 1; i < OXYGEN.length; i++) {
    const [x1, c1] = OXYGEN[i];
    if (mgl <= x1) {
      const [x0, c0] = OXYGEN[i - 1];
      const f = (mgl - x0) / (x1 - x0);
      return [0, 1, 2].map((k) => Math.round(c0[k] + (c1[k] - c0[k]) * f)) as [number, number, number];
    }
  }
  return OXYGEN.at(-1)![1];
}

export function oxygenColor(mgl: number): string {
  const [r, g, b] = oxygenRgb(mgl);
  return `rgb(${r} ${g} ${b})`;
}

/** Ink on the light sandy middle of the scale, paper on the deep ends. */
export function textOn(mgl: number): string {
  const [r, g, b] = oxygenRgb(mgl).map((c) => (c / 255) ** 2.2);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.2 ? "#0b1112" : "#ece5d5";
}

export const INCIDENT_LABEL: Record<IncidentStatus, string> = {
  investigating: "Investigating",
  mitigating: "Acting",
  verifying: "Verifying recovery",
  monitoring: "Watching, blind",
  awaiting_approval: "Needs your approval",
  escalated: "Escalated to a person",
  resolved: "Recovered",
  dismissed: "False alarm stopped",
};

export const INCIDENT_TONE: Record<IncidentStatus, string> = {
  investigating: "text-paper",
  mitigating: "text-ochre",
  verifying: "text-sea",
  monitoring: "text-fog",
  awaiting_approval: "text-dawn",
  escalated: "text-rust",
  resolved: "text-sea",
  dismissed: "text-lavender",
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

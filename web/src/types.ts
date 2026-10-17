export type Status = "ok" | "watch" | "alert" | "sensor" | "blind";

export interface AeratorNow {
  id: string;
  on: boolean;
  amp: number;
}

export interface PondLast {
  ts: string;
  do: number;
  temp: number;
  ph: number;
  aerators_on: number;
  aerators_running: number;
  aer?: AeratorNow[];
  probe_q: number;
}

export interface Forecast {
  at: string;
  minutes_to_hypoxia: number | null;
  slope_per_min: number;
  points: number;
  rate_3m?: number;
}

export interface PondState {
  _id: string;
  farm: string;
  gateway: string;
  status?: Status;
  last?: PondLast;
  forecast?: Forecast;
  freshness_s?: number | null;
  area_m2?: number;
  open_incident?: string;
  repair_tickets?: { device: string; incident: string }[];
  sensor_ticket?: { incident: string; probe?: string };
}

export interface Device {
  _id: string;
  type: string;
  aerator?: { kw: number; standby: boolean };
  probe?: { model: string };
}

export interface PondDetail extends PondState {
  devices: Device[];
  aerators?: string[];
  standby?: string[];
}

export interface HistoryPoint {
  ts: string;
  do: number;
  temp: number;
  ph: number;
  running?: number;
}

export interface Meta {
  version: string;
  env: string;
  farm_clock_offset_hours: number;
}

export type IncidentStatus =
  | "investigating"
  | "mitigating"
  | "verifying"
  | "monitoring"
  | "awaiting_approval"
  | "escalated"
  | "resolved"
  | "dismissed";

export interface TimelineEntry {
  t: string;
  kind: string;
  [key: string]: unknown;
}

export interface EvidenceItem {
  check: string;
  cause: string;
  verdict: "support" | "against";
  weight: number;
  detail: string;
  at?: string;
}

export interface IncidentMetrics {
  mttd_s?: number;
  time_to_action_s?: number | null;
  mttr_min?: number;
  min_do?: number;
  oxygen_debt?: number;
  below_safe_min?: number;
  lead_time_min?: number | null;
  blind_s?: number;
  coverage?: number | null;
}

export interface Incident {
  _id: string;
  key: string;
  scope: "pond" | "gateway" | "farm" | "estate";
  open?: boolean;
  pond: string | null;
  ponds: string[];
  farm: string | null;
  gateway: string | null;
  status: IncidentStatus;
  opened_at: string;
  closed_at?: string;
  signals: string[];
  diagnosis?: { cause: string; confidence: number; onset?: string; device?: string };
  evidence: EvidenceItem[];
  timeline: TimelineEntry[];
  actions: { kind: string; action?: string; device?: string; status?: string; text?: string }[];
  approvals?: { action: string; status: string }[];
  metrics?: IncidentMetrics;
  false_alarm_prevented?: boolean;
  investigation?: Investigation;
  postmortem?: { status: string; title?: string; postmortem_md?: string; follow_ups?: string[] };
  evals?: {
    agrees_with_rules?: boolean;
    explained_unknown?: boolean;
    grounded?: number;
    farmer_message_ok?: boolean;
    truth?: string;
    rca_correct?: boolean;
    rules_correct?: boolean;
  };
}

export interface Investigation {
  status: "running" | "done" | "failed";
  cause?: string;
  confidence?: number;
  summary?: string;
  farmer_message_vi?: string;
  next_steps?: string[];
  model?: string;
  rounds?: number;
  tool_calls?: { tool: string; args: Record<string, unknown> }[];
  latency_ms?: number;
}

export interface AiStats {
  investigated: number;
  agrees?: number;
  grounded?: number;
  message_ok?: number;
  scored?: number;
  ai_correct?: number;
  rules_correct?: number;
}

export interface Fault {
  _id: string;
  kind: string;
  status: string;
  farm?: string;
  pond?: string;
  gateway?: string;
  device?: string;
  started_at?: string;
  cleared_at?: string;
}

export const PROVINCES: Record<string, string> = {
  BL: "Bạc Liêu",
  ST: "Sóc Trăng",
  CM: "Cà Mau",
  BT: "Bến Tre",
  KG: "Kiên Giang",
};

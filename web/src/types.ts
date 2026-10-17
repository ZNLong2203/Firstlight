export type Status = "ok" | "watch" | "alert" | "blind";

export interface PondLast {
  ts: string;
  do: number;
  temp: number;
  ph: number;
  aerators_on: number;
  aerators_running: number;
  probe_q: number;
}

export interface Forecast {
  at: string;
  minutes_to_hypoxia: number | null;
  slope_per_min: number;
  points: number;
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

export const PROVINCES: Record<string, string> = {
  BL: "Bạc Liêu",
  ST: "Sóc Trăng",
  CM: "Cà Mau",
  BT: "Bến Tre",
  KG: "Kiên Giang",
};

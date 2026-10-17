import { LineChart, type LineSeriesOption } from "echarts/charts";
import {
  AxisPointerComponent,
  GridComponent,
  type GridComponentOption,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  type TooltipComponentOption,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { farmClock, HYPOXIA_MGL, hhmm, SAFE_MGL } from "../format";
import type { HistoryPoint, PondState } from "../types";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  AxisPointerComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
]);

type Option = echarts.ComposeOption<LineSeriesOption | GridComponentOption | TooltipComponentOption>;

const AXIS = { color: "#5f655e", fontSize: 10, fontFamily: "JetBrains Mono, ui-monospace, monospace" };
const SPLIT = { lineStyle: { color: "#1c2828" } };

/** Where the trend crosses 3 mg/L, or where it is in an hour, drawn from the latest reading. */
function forecastLine(pond: PondState): [number, number][] {
  const { last, forecast } = pond;
  if (!last || !forecast || forecast.slope_per_min >= -0.005) return [];
  const start: [number, number] = [Date.parse(last.ts), last.do];
  const minutes = forecast.minutes_to_hypoxia;
  if (minutes != null && minutes <= 60) return [start, [Date.parse(forecast.at) + minutes * 60_000, HYPOXIA_MGL]];
  return [start, [start[0] + 3_600_000, last.do + forecast.slope_per_min * 60]];
}

function buildOption(
  history: HistoryPoint[],
  pond: PondState,
  now: number,
  offsetHours: number,
  trusted: boolean,
): Option {
  const clock = (ms: number) => hhmm(farmClock(ms, offsetHours));
  const forecast = trusted ? forecastLine(pond) : []; // no forecast from a probe known to be wrong
  const end = Math.max(now + 10 * 60_000, (forecast.at(-1)?.[0] ?? 0) + 5 * 60_000);
  const aerators = Math.max(pond.last?.aerators_on ?? 0, ...history.map((p) => p.running ?? 0), 1);
  const xAxis = {
    type: "time" as const,
    min: now - 2 * 3_600_000,
    max: end,
    axisLine: { lineStyle: { color: "#22302f" } },
    axisTick: { show: false },
    splitLine: { show: false },
  };

  return {
    animation: false,
    grid: [
      { left: 34, right: 12, top: 22, height: "60%" },
      { left: 34, right: 12, top: "78%", bottom: 22 },
    ],
    axisPointer: { link: [{ xAxisIndex: "all" }], lineStyle: { color: "#5f655e" } },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#0f1718",
      borderColor: "#304140",
      textStyle: { color: "#ece5d5", fontSize: 12, fontFamily: "Be Vietnam Pro, ui-sans-serif, sans-serif" },
      valueFormatter: (value) => (typeof value === "number" ? value.toFixed(2) : String(value)),
      axisPointer: { label: { show: false } },
    },
    xAxis: [
      { ...xAxis, gridIndex: 0, axisLabel: { show: false } },
      { ...xAxis, gridIndex: 1, axisLabel: { ...AXIS, formatter: (value: number) => clock(value) } },
    ],
    yAxis: [
      {
        type: "value",
        gridIndex: 0,
        min: (range: { min: number }) => Math.max(0, Math.min(2, Math.floor(range.min - 0.5))),
        max: (range: { max: number }) => Math.ceil(range.max + 0.5),
        interval: 1,
        axisLabel: AXIS,
        splitLine: SPLIT,
      },
      {
        type: "value",
        gridIndex: 1,
        min: 0,
        max: aerators,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "DO mg/L",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        lineStyle: { color: "#ece5d5", width: 1.8 },
        itemStyle: { color: "#ece5d5" },
        data: history.map((p) => [Date.parse(p.ts), p.do]),
        markArea: {
          silent: true,
          label: { position: "insideTopLeft", fontSize: 10, distance: 4 },
          data: [
            [
              { name: "hypoxia", yAxis: 0, itemStyle: { color: "rgba(224,113,78,0.10)" }, label: { color: "#e0714e", fontFamily: "Be Vietnam Pro, sans-serif" } },
              { yAxis: HYPOXIA_MGL },
            ],
            [
              { name: "stress", yAxis: HYPOXIA_MGL, itemStyle: { color: "rgba(214,176,98,0.06)" }, label: { color: "#d6b062", fontFamily: "Be Vietnam Pro, sans-serif" } },
              { yAxis: SAFE_MGL },
            ],
          ],
        },
        markLine: {
          silent: true,
          symbol: "none",
          data: [
            {
              name: "now",
              xAxis: now,
              lineStyle: { color: "#f0a35e", type: "solid", width: 1 },
              label: { formatter: "now", position: "end", color: "#f0a35e", fontSize: 10 },
            },
            { yAxis: HYPOXIA_MGL, lineStyle: { color: "#e0714e", type: "dashed", width: 1 }, label: { show: false } },
            { yAxis: SAFE_MGL, lineStyle: { color: "#d6b062", type: "dashed", width: 1 }, label: { show: false } },
          ],
        },
      },
      {
        name: "Forecast",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        lineStyle: { color: "#f0a35e", width: 1.8, type: "dashed" },
        itemStyle: { color: "#f0a35e" },
        tooltip: { show: false },
        data: forecast,
        markPoint:
          forecast.length && forecast[1][1] === HYPOXIA_MGL
            ? {
                symbol: "circle",
                symbolSize: 8,
                itemStyle: { color: "#e0714e" },
                label: { show: true, position: "bottom", color: "#e0714e", fontSize: 10, formatter: clock(forecast[1][0]) },
                data: [{ name: "3 mg/L", coord: forecast[1] }],
              }
            : undefined,
      },
      {
        name: "Aerators turning",
        type: "line",
        step: "end",
        xAxisIndex: 1,
        yAxisIndex: 1,
        showSymbol: false,
        lineStyle: { color: "#86bfa9", width: 1.4 },
        itemStyle: { color: "#86bfa9" },
        areaStyle: { color: "rgba(134,191,169,0.14)" },
        data: history.filter((p) => p.running != null).map((p) => [Date.parse(p.ts), p.running!]),
      },
    ],
  };
}

export function DoChart(props: {
  history: HistoryPoint[];
  pond: PondState;
  now: number;
  offsetHours: number;
  trusted: boolean;
}) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!element.current) return;
    const instance = echarts.init(element.current, null, { renderer: "canvas" });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  const { history, pond, now, offsetHours, trusted } = props;
  const tick = Math.floor(now / 10_000) * 10_000; // the clock moves the chart every 10 s, data at once
  useEffect(() => {
    chart.current?.setOption(buildOption(history, pond, tick, offsetHours, trusted), { notMerge: true });
  }, [history, pond, tick, offsetHours, trusted]);

  return <div ref={element} className="h-72 w-full" role="img" aria-label={`Dissolved oxygen in ${pond._id} over the last two hours`} />;
}

import { memo, useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SeriesPoint } from "../../api/types";
import { formatNumber } from "../../lib/format";

export interface SeriesConfig {
  key: string;
  name: string;
  color: string;
  type?: "line" | "area";
  unit?: string;
  axis?: "left" | "right";
}

interface TimeChartProps {
  data: SeriesPoint[];
  series: SeriesConfig[];
  stepSeconds: number;
  /** Порог рисуется прямо на графике: без него ряд ни о чём не говорит. */
  threshold?: { value: number; label: string; axis?: "left" | "right" } | null;
  height?: number;
}

/** Подпись времени под шаг ряда: по суткам не нужны минуты, по часу — дата. */
function tickFormatter(stepSeconds: number) {
  return (value: string) => {
    const date = new Date(value.replace(" ", "T") + "Z");
    if (Number.isNaN(date.getTime())) return value;
    if (stepSeconds >= 24 * 3600) {
      return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
    }
    return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  };
}

// Оформление осей и подсказки — постоянные объекты. Если создавать их заново
// при каждой отрисовке, график считает, что настройки поменялись, и
// пересчитывается; на странице с живыми данными это зацикливалось.
const TICK = { fill: "var(--text-faint)", fontSize: 12 };
const AXIS_LINE = { stroke: "var(--border)" };
const TOOLTIP_STYLE = {
  background: "var(--bg-surface)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-md)",
  fontSize: 13,
};
const LEGEND_STYLE = { fontSize: 12, color: "var(--text-muted)", paddingTop: 8 };

function tooltipLabel(value: unknown): string {
  const date = new Date(String(value).replace(" ", "T") + "Z");
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/**
 * График перерисовывается только когда меняются данные или настройки рядов,
 * а не при каждой перерисовке страницы: рядом с ним живая часть обновляется
 * до 25 раз в секунду.
 */
export const TimeChart = memo(TimeChartView, (before, after) =>
  before.data === after.data &&
  before.stepSeconds === after.stepSeconds &&
  before.height === after.height &&
  JSON.stringify(before.series) === JSON.stringify(after.series) &&
  JSON.stringify(before.threshold ?? null) === JSON.stringify(after.threshold ?? null),
);

function TimeChartView({ data, series, stepSeconds, threshold, height = 260 }: TimeChartProps) {
  const rightAxis = series.some((item) => item.axis === "right");
  const margin = useMemo(() => ({ top: 8, right: rightAxis ? 8 : 16, bottom: 0, left: -12 }), [rightAxis]);
  const formatTick = useMemo(() => tickFormatter(stepSeconds), [stepSeconds]);
  const formatValue = useMemo(
    () => (value: unknown, name: unknown) => {
      const config = series.find((item) => item.name === name);
      const number = typeof value === "number" ? value : Number(value);
      return [`${formatNumber(number)} ${config?.unit ?? ""}`.trim(), String(name)] as [string, string];
    },
    [series],
  );

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={margin}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="at"
          tickFormatter={formatTick}
          tick={TICK}
          axisLine={AXIS_LINE}
          tickLine={false}
          minTickGap={28}
        />
        <YAxis
          yAxisId="left"
          tick={TICK}
          axisLine={false}
          tickLine={false}
          width={48}
        />
        {rightAxis && (
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={TICK}
            axisLine={false}
            tickLine={false}
            width={44}
          />
        )}
        <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={tooltipLabel} formatter={formatValue} />
        <Legend wrapperStyle={LEGEND_STYLE} iconType="plainline" />

        {threshold && (
          <ReferenceLine
            yAxisId={threshold.axis ?? "left"}
            y={threshold.value}
            stroke="var(--danger)"
            strokeDasharray="5 4"
            label={{
              value: threshold.label,
              position: "insideTopRight",
              fill: "var(--danger)",
              fontSize: 11,
            }}
          />
        )}

        {series.map((item) =>
          item.type === "area" ? (
            <Area
              key={item.key}
              yAxisId={item.axis ?? "left"}
              type="monotone"
              dataKey={item.key}
              name={item.name}
              stroke={item.color}
              fill={item.color}
              fillOpacity={0.14}
              strokeWidth={2}
              connectNulls={false}
              dot={false}
            />
          ) : (
            <Line
              key={item.key}
              yAxisId={item.axis ?? "left"}
              type="monotone"
              dataKey={item.key}
              name={item.name}
              stroke={item.color}
              strokeWidth={2}
              connectNulls={false}
              dot={false}
            />
          ),
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

import type { HeatmapView } from "../../api/types";
import { formatNumber } from "../../lib/format";

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

interface HeatmapGridProps {
  heatmap: HeatmapView;
  metric?: "flow" | "queue";
  /** Выбор ячейки сужает период до этого дня и часа (ТЗ, раздел 5.3). */
  onSelect?: (weekday: number, hour: number) => void;
}

export function HeatmapGrid({ heatmap, metric = "flow", onSelect }: HeatmapGridProps) {
  const values = heatmap.cells.map((cell) => cell[metric]);
  const max = Math.max(1, ...values);
  const index = new Map(heatmap.cells.map((cell) => [`${cell.weekday}-${cell.hour}`, cell]));

  return (
    <div className="heatmap" role="table" aria-label="Нагрузка по дням недели и часам">
      <div className="heatmap__hours" aria-hidden="true">
        <span />
        {Array.from({ length: 24 }, (_, hour) => (
          <span key={hour}>{hour % 3 === 0 ? hour : ""}</span>
        ))}
      </div>
      {WEEKDAYS.map((title, weekday) => (
        <div className="heatmap__row" key={title} role="row">
          <span className="heatmap__day">{title}</span>
          {Array.from({ length: 24 }, (_, hour) => {
            const cell = index.get(`${weekday}-${hour}`);
            const value = cell ? cell[metric] : null;
            const intensity = value === null ? 0 : Math.min(1, value / max);
            return (
              <button
                key={hour}
                type="button"
                className="heatmap__cell"
                style={{
                  background:
                    value === null
                      ? "var(--bg-muted)"
                      : `color-mix(in srgb, var(--accent) ${Math.round(intensity * 100)}%, var(--bg-muted))`,
                }}
                title={
                  value === null
                    ? `${title}, ${hour}:00 — данных нет`
                    : `${title}, ${hour}:00 — ${formatNumber(value)} ${metric === "flow" ? "чел/ч" : "чел в очереди"}`
                }
                onClick={() => onSelect?.(weekday, hour)}
                disabled={!onSelect || value === null}
                aria-label={`${title}, ${hour} часов`}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

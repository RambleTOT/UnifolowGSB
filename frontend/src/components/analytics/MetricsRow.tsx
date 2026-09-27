import type { MetricView } from "../../api/types";
import { Metric } from "../common/Metric";

/** Показатели раздела: один и тот же компонент во всех разделах. */
export function MetricsRow({ metrics }: { metrics: MetricView[] }) {
  return (
    <div className="metrics-row">
      {metrics.map((metric) => (
        <div key={metric.key} className="metrics-row__item">
          <Metric
            metric={{
              label: metric.label,
              value: metric.value,
              unit: metric.unit,
              whole: metric.unit === "чел" || metric.unit === "шт",
              deltaPercent: metric.deltaPercent,
              direction: metric.direction,
              meaning: metric.meaning,
              level: metric.level,
              hint: metric.hint ?? undefined,
              missingReason: metric.missingReason ?? undefined,
            }}
          />
          {metric.incomplete && (
            <p className="metrics-row__incomplete" title={metric.incomplete.names.join(", ")}>
              учтено {metric.incomplete.counted} из {metric.incomplete.total} источников
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

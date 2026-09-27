import { formatDelta, formatValue } from "../../lib/format";

export type MetricLevel = "normal" | "good" | "attention" | "critical";
export type ChangeDirection = "up" | "down" | "flat";
export type ChangeMeaning = "better" | "worse" | "neutral";

export interface MetricValue {
  label: string;
  value: number | null;
  unit?: string;
  whole?: boolean;
  /** Изменение к предыдущему периоду; null — сравнивать не с чем. */
  deltaPercent?: number | null;
  direction?: ChangeDirection;
  /** Оценка изменения отделена от направления: рост очереди — это ухудшение. */
  meaning?: ChangeMeaning;
  level?: MetricLevel;
  hint?: string;
  /** Причина прочерка: почему метрика не считается. */
  missingReason?: string;
}

const ARROW: Record<ChangeDirection, string> = { up: "▲", down: "▼", flat: "→" };

/**
 * Показатель — один компонент на все разделы (ТЗ, раздел 3.5).
 * Направление изменения и его оценка показываются раздельно.
 */
export function Metric({ metric }: { metric: MetricValue }) {
  const {
    label,
    value,
    unit,
    whole,
    deltaPercent,
    direction = "flat",
    meaning = "neutral",
    level = "normal",
    hint,
    missingReason,
  } = metric;

  const missing = value === null || value === undefined;

  return (
    <article className={`metric metric--${level}`}>
      <header className="metric__label">
        {label}
        {hint && (
          <span className="metric__hint" title={hint} aria-label={hint}>
            ?
          </span>
        )}
      </header>

      <div className="metric__value tabular">
        {missing ? (
          <span className="metric__dash" title={missingReason}>
            —
          </span>
        ) : (
          <>
            <strong>{formatValue(value, undefined, whole)}</strong>
            {unit && <span className="metric__unit">{unit}</span>}
          </>
        )}
      </div>

      {missing && missingReason ? (
        <p className="metric__note">{missingReason}</p>
      ) : (
        <p className={`metric__change metric__change--${meaning}`}>
          <span aria-hidden="true">{deltaPercent === null || deltaPercent === undefined ? "" : ARROW[direction]}</span>{" "}
          {formatDelta(deltaPercent)}
          {meaning !== "neutral" && deltaPercent !== null && deltaPercent !== undefined && (
            <span className="metric__meaning">
              {meaning === "better" ? " — стало лучше" : " — стало хуже"}
            </span>
          )}
        </p>
      )}
    </article>
  );
}

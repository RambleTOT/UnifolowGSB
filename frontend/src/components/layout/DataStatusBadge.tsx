import { useState } from "react";
import { Link } from "react-router-dom";

import type { DataStatus } from "../../api/types";
import { label } from "../../lib/dictionary";

interface DataStatusBadgeProps {
  status: DataStatus | null;
  /** Связь с сервером потеряна — это отдельное состояние, не «нет данных». */
  disconnected: boolean;
  paused: boolean;
  staleSince?: string | null;
}

/**
 * Индикатор состояния данных (ТЗ, раздел 4.3): отражает реальное положение дел
 * и открывает список проблемных источников.
 */
export function DataStatusBadge({ status, disconnected, paused, staleSince }: DataStatusBadgeProps) {
  const [open, setOpen] = useState(false);

  const state = disconnected
    ? "disconnected"
    : paused
      ? "paused"
      : (status?.state ?? "no_sources");

  const tone =
    state === "ok" ? "ok" : state === "partial" ? "warn" : state === "paused" ? "muted" : "danger";

  const text =
    state === "partial" && status
      ? `Частично: ${status.healthy} из ${status.countable}`
      : label("dataStatus", state);

  const problems = status?.problems ?? [];
  const hasList = problems.length > 0 && !disconnected;

  return (
    <div className="data-status">
      <button
        type="button"
        className={`data-status__button data-status__button--${tone}`}
        aria-label={text}
        onClick={() => hasList && setOpen((value) => !value)}
        aria-expanded={hasList ? open : undefined}
        title={
          disconnected && staleSince
            ? `Значения на экране получены ${staleSince}`
            : hasList
              ? "Показать источники с проблемами"
              : undefined
        }
      >
        <span className={`pill__dot pill__dot--${tone}`} aria-hidden="true" />
        {/* На телефоне остаётся только цветная точка; текст — в подписи кнопки. */}
        <span className="data-status__text">{text}</span>
      </button>

      {open && hasList && (
        <div className="data-status__list">
          <div className="data-status__title">Источники, с которыми есть проблема</div>
          {problems.map((problem) => (
            <Link
              key={problem.sourceId}
              to={`/monitor?source=${problem.sourceId}`}
              className="data-status__item"
              onClick={() => setOpen(false)}
            >
              <strong>{problem.name}</strong>
              <span>{label("sourceStatus", problem.status)}</span>
              {problem.error && <small>{problem.error}</small>}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";

import type { Source } from "../../api/types";
import { label } from "../../lib/dictionary";
import { formatDurationSeconds, formatFreshness } from "../../lib/format";
import { StatusPill } from "../common/StatusPill";

interface SourceWallProps {
  sources: Source[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  /** Живое изображение показываем не всем сразу: браузер не держит много потоков. */
  liveLimit?: number;
}

/** Главная метрика источника определяется его разметкой (ТЗ, раздел 3.1). */
function primaryMetric(source: Source): { title: string; value: string } {
  const metrics = source.live?.metrics;
  switch (source.primaryMetric) {
    case "flow":
      return {
        title: "Входы и выходы",
        value: metrics ? `↑ ${metrics.entriesToday} / ↓ ${metrics.exitsToday} чел` : "—",
      };
    case "queue":
      return {
        title: "Очередь и ожидание",
        value: metrics
          ? `${metrics.queue} чел · ${formatDurationSeconds(metrics.avgWaitSeconds ?? null)}`
          : "—",
      };
    case "occupancy":
      return { title: "Людей в зоне", value: metrics ? `${metrics.peopleInZone} чел` : "—" };
    default:
      return { title: "Нет разметки", value: "—" };
  }
}

/**
 * Проблемные источники идут первыми: их ищут чаще всего. Источник без видео и
 * выключенный проблемой не считаются, но и выше работающих быть не должны.
 */
function order(source: Source): number {
  if (!source.enabled) return 5;
  if (source.status === "no_video") return 4;
  if (source.status === "offline") return 0;
  if (source.status === "degraded") return 1;
  if (source.readiness.state === "no_markup") return 2;
  return 3;
}

export function SourceWall({ sources, selectedId, onSelect, liveLimit = 6 }: SourceWallProps) {
  const [filter, setFilter] = useState<"all" | "problems">("all");
  const [tick, setTick] = useState(0);

  // Снимки кадров обновляются сами: открывать поток на каждый источник нельзя.
  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => value + 1), 2000);
    return () => window.clearInterval(timer);
  }, []);

  const problems = sources.filter(
    (source) => source.status !== "online" || source.readiness.state === "no_markup",
  );
  const visible = (filter === "problems" ? problems : sources)
    .slice()
    .sort((left, right) => order(left) - order(right) || left.name.localeCompare(right.name, "ru"));

  return (
    <div className="wall">
      <div className="wall__filters">
        <button
          type="button"
          className={`chip ${filter === "all" ? "chip--active" : ""}`}
          onClick={() => setFilter("all")}
        >
          Все источники ({sources.length})
        </button>
        <button
          type="button"
          className={`chip ${filter === "problems" ? "chip--active" : ""}`}
          onClick={() => setFilter("problems")}
          disabled={problems.length === 0}
          title={problems.length === 0 ? "Проблемных источников нет" : undefined}
        >
          Только проблемные ({problems.length})
        </button>
        <span className="wall__hint">
          Проблемные источники всегда идут первыми. Выберите источник, чтобы разобрать его подробно.
        </span>
      </div>

      <ul className="wall__grid">
        {visible.map((source, index) => {
          const metric = primaryMetric(source);
          // «Нестабильно» — это медленный анализ, а не отсутствие кадров: картинку показываем.
          const showLive = (source.status === "online" || source.status === "degraded") && index < liveLimit;
          return (
            <li key={source.id}>
              <button
                type="button"
                className={`card ${selectedId === source.id ? "card--selected" : ""}`}
                onClick={() => onSelect(source.id)}
                aria-pressed={selectedId === source.id}
              >
                <div className="card__media">
                  {showLive ? (
                    <img
                      src={`/api/sources/${source.id}/snapshot.jpg?t=${tick}`}
                      alt={`Кадр источника «${source.name}»`}
                      loading="lazy"
                    />
                  ) : (
                    <div className="card__media-empty">
                      {source.status === "no_video"
                        ? source.connectionType === "stream"
                          ? "Не указана ссылка на поток"
                          : "Видео не назначено"
                        : source.enabled
                          ? "Кадров нет"
                          : "Источник выключен"}
                    </div>
                  )}
                  <span className="card__status">
                    <StatusPill status={source.status} />
                  </span>
                </div>

                <div className="card__body">
                  <div className="card__title">
                    <strong>{source.name}</strong>
                    <span className="muted">
                      {label("scope", source.scope)} · {source.location}
                    </span>
                  </div>

                  <div className="card__metric">
                    <span className="muted">{metric.title}</span>
                    <strong className="tabular">{metric.value}</strong>
                  </div>

                  <div className="card__foot">
                    <span className={`readiness readiness--${source.readiness.state}`}>
                      {label("readiness", source.readiness.state)}
                    </span>
                    <span className="muted">
                      {source.lastSignalAt ? `сигнал ${formatFreshness(source.lastSignalAt)}` : "сигнала не было"}
                    </span>
                  </div>

                  <div className="card__tech muted">
                    <span>{source.connectionType === "stream" ? "Прямой эфир" : "Видеофайл (по кругу)"}</span>
                    {(source.live?.resolution ?? source.video?.resolution) && (
                      <span>{source.live?.resolution ?? source.video?.resolution}</span>
                    )}
                    {source.live && <span>{source.live.technical.fps.toFixed(1)} кадр/с</span>}
                  </div>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

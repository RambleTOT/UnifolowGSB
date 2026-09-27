import { Link } from "react-router-dom";

import { useDashboard, useSources, useUpdateProfile } from "../api/queries";
import type { Source } from "../api/types";
import { Button } from "../components/common/Button";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { StatusPill } from "../components/common/StatusPill";
import { MetricsRow } from "../components/analytics/MetricsRow";
import { HeatmapGrid } from "../components/charts/HeatmapGrid";
import { ShareBars } from "../components/charts/ShareBars";
import { TimeChart } from "../components/charts/TimeChart";
import { EventCard } from "../components/events/EventCard";
import { label } from "../lib/dictionary";
import { useFilters } from "../state/filters";
import { useSession } from "../state/session";

/** Первый запуск: путь из трёх шагов до работающих счётчиков (ТЗ, раздел 5.0). */
function FirstRun({ sources }: { sources: Source[] }) {
  const updateProfile = useUpdateProfile();
  const withVideo = sources.filter((source) => source.videoAvailable);
  const marked = withVideo.filter((source) => source.readiness.state !== "no_markup");
  const counting = marked.filter((source) => source.status === "online");

  const steps = [
    {
      done: withVideo.length > 0,
      title: "Добавить источник и загрузить видео",
      text: "Источник — видеофайл, который воспроизводится по кругу, или прямой поток с камеры.",
      action: <Link to="/sources/new">Добавить источник</Link>,
    },
    {
      done: marked.length > 0,
      title: "Разметить контрольную линию и зоны",
      text: "Без разметки считается только число людей в кадре: входы, выходы и очередь — нет.",
      action: withVideo[0] ? (
        <Link to={`/sources/${withVideo[0].id}/markup`}>Перейти к разметке</Link>
      ) : (
        <span className="muted">Сначала нужен источник с видео</span>
      ),
    },
    {
      done: counting.length > 0,
      title: "Открыть мониторинг и убедиться, что счётчики работают",
      text: "На кадре видно, что именно считается, и каждый засчитанный проход.",
      action: <Link to="/monitor">Открыть мониторинг</Link>,
    },
  ];

  return (
    <Panel title="С чего начать" meta="Три шага до первых засчитанных проходов">
      <ol className="steps">
        {steps.map((step, index) => (
          <li key={step.title} className={`steps__item ${step.done ? "steps__item--done" : ""}`}>
            <span className="steps__number" aria-hidden="true">
              {step.done ? "✓" : index + 1}
            </span>
            <div className="steps__body">
              <strong>{step.title}</strong>
              <p>{step.text}</p>
              <div className="steps__action">{step.action}</div>
            </div>
          </li>
        ))}
      </ol>

      <div className="steps__demo">
        Хотите посмотреть продукт на готовых данных, пока своих мало?
        <Button
          variant="ghost"
          onClick={() => updateProfile.mutate({ dataset: "demo" })}
          loading={updateProfile.isPending}
        >
          Включить демо-режим
        </Button>
      </div>
    </Panel>
  );
}

export function HomePage() {
  const { filters } = useFilters();
  const { user } = useSession();
  const dataset = user?.dataset ?? "real";
  const sourcesQuery = useSources();
  const dashboard = useDashboard(
    { period: filters.period, scope: filters.scope, from: filters.from, to: filters.to },
    dataset,
  );

  const sources = sourcesQuery.data?.sources ?? [];
  const working = sources.filter((source) => source.status === "online");
  const data = dashboard.data;
  const firstRun = dataset === "real" && working.length === 0 && (data?.metrics[1]?.value ?? 0) === 0;

  const enoughHistory = (block: { daysCollected: number; daysRequired: number }) =>
    block.daysCollected >= block.daysRequired;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">Главная</h1>
          <p className="page__subtitle">
            {data
              ? `Период: ${label("period", data.window.period)} · шаг ${data.window.stepTitle}`
              : "Сводная картина по очередям, потоку и состоянию источников"}
            {dataset === "demo" && " · показаны демо-данные"}
          </p>
        </div>
        <Link className="btn btn--secondary btn--md" to="/reports">
          Сформировать отчёт
        </Link>
      </header>

      {firstRun ? (
        <FirstRun sources={sources} />
      ) : (
        <DataBlock
          state={blockState({
            isLoading: dashboard.isLoading,
            isFetching: dashboard.isFetching,
            isError: dashboard.isError,
          })}
          error={dashboard.error}
          onRetry={() => dashboard.refetch()}
        >
          {data && (
            <div className="page__stack">
              <Panel
                title="Что требует внимания сейчас"
                meta={
                  data.attention.events.length + data.attention.sources.length === 0
                    ? "Всё в порядке"
                    : `${data.attention.events.length} событий · ${data.attention.sources.length} источников`
                }
                actions={<Link to="/events">Весь журнал</Link>}
              >
                {data.attention.events.length === 0 && data.attention.sources.length === 0 ? (
                  <p className="ok-note">
                    Продолжающихся событий нет, все включённые источники работают. Счётчики идут.
                  </p>
                ) : (
                  <div className="attention-grid">
                    {data.attention.events.slice(0, 4).map((event) => (
                      <EventCard key={event.id} event={event} compact />
                    ))}
                    {data.attention.sources.map((source) => (
                      <article key={source.sourceId} className="attention-source">
                        <StatusPill status={source.status} />
                        <Link to={`/monitor?source=${source.sourceId}`}>{source.name}</Link>
                        <p className="muted">{attentionText(source)}</p>
                      </article>
                    ))}
                  </div>
                )}
              </Panel>

              <MetricsRow metrics={data.metrics} />

              <Panel
                title="Поток за период"
                meta={`шаг ${data.window.stepTitle}`}
                updatedAt={data.window.to}
              >
                {data.flowSeries.some((point) => point.entered !== null) ? (
                  <TimeChart
                    data={data.flowSeries}
                    stepSeconds={data.window.stepSeconds}
                    series={[
                      { key: "peopleInZone", name: "Людей в зоне", color: "#8992a2", type: "area", unit: "чел" },
                      { key: "entered", name: "Входы", color: "#1b5fcb", unit: "чел" },
                      { key: "exited", name: "Выходы", color: "#1b6b4e", unit: "чел" },
                    ]}
                  />
                ) : (
                  <EmptyState
                    title="За период данных нет"
                    description="Источники не передавали данные в этом периоде. Выберите другой период или проверьте источники."
                    action={<Link to="/monitor">Открыть мониторинг</Link>}
                  />
                )}
              </Panel>

              <div className="grid-2">
                <Panel title="Очередь и ожидание" meta={`порог очереди ${data.thresholds.queue} чел`}>
                  {data.queueSeries.some((point) => point.queue !== null) ? (
                    <TimeChart
                      data={data.queueSeries}
                      stepSeconds={data.window.stepSeconds}
                      series={[
                        { key: "queue", name: "Очередь", color: "#1b5fcb", type: "area", unit: "чел" },
                        { key: "waitMinutes", name: "Ожидание", color: "#9a6b12", unit: "мин", axis: "right" },
                      ]}
                      threshold={{ value: data.thresholds.queue, label: "порог очереди" }}
                    />
                  ) : (
                    <EmptyState
                      title="Очередь не считается"
                      description="Ни у одного источника выборки нет зоны очереди."
                      action={<Link to="/sources">Разметить зоны</Link>}
                    />
                  )}
                </Panel>

                <Panel title="Нагрузка по источникам" meta="Кто загружен сильнее">
                  {data.sourceLoad.length > 0 ? (
                    <ShareBars
                      unit="проходов"
                      items={data.sourceLoad.map((item) => ({
                        id: item.sourceId,
                        name: item.name,
                        note: `очередь в среднем ${item.queueAvg} чел`,
                        value: item.flow,
                        share: data.distribution.find((d) => d.sourceId === item.sourceId)?.share,
                      }))}
                    />
                  ) : (
                    <EmptyState title="Сравнивать нечего" description="За период ни один источник не дал данных." />
                  )}
                </Panel>
              </div>

              <div className="grid-2">
                <Panel
                  title="Тепловая карта нагрузки"
                  meta="По дням недели и часам · для планирования смен"
                >
                  {enoughHistory(data.heatmap) ? (
                    <HeatmapGrid heatmap={data.heatmap} />
                  ) : (
                    <EmptyState
                      title="Недостаточно истории"
                      description={`Накоплено ${data.heatmap.daysCollected} из ${data.heatmap.daysRequired} суток. Карта заполнится, когда данных станет больше — или посмотрите её на демо-данных.`}
                    />
                  )}
                </Panel>

                <Panel title="Профиль по часам" meta="Типовая кривая дня">
                  {enoughHistory(data.hourlyProfile) ? (
                    <TimeChart
                      data={data.hourlyProfile.points.map((point) => ({
                        at: `${String(point.hour).padStart(2, "0")}:00`,
                        samples: 1,
                        flow: point.flow,
                      }))}
                      stepSeconds={3600}
                      series={[{ key: "flow", name: "Проходов в час", color: "#1b5fcb", type: "area", unit: "чел" }]}
                    />
                  ) : (
                    <EmptyState
                      title="Недостаточно истории"
                      description={`Накоплено ${data.hourlyProfile.daysCollected} из ${data.hourlyProfile.daysRequired} суток.`}
                    />
                  )}
                </Panel>
              </div>
            </div>
          )}
        </DataBlock>
      )}
    </div>
  );
}

/**
 * Одна фраза о том, что не так с источником. Причина берётся из статуса:
 * у «нестабильного» источника проблема в скорости анализа, а не в разметке.
 */
function attentionText(source: {
  status: string;
  error: string | null;
  readiness: { state: string; missing: string[] };
}): string {
  if (source.error) return source.error;
  const missing = source.readiness.missing;
  switch (source.status) {
    case "no_video":
      return missing.length > 0 ? capitalize(missing.join(", ")) : "Нечего анализировать.";
    case "degraded":
      return "Анализ отстаёт от видео: счётчики могут запаздывать.";
    case "offline":
      return "Нет сигнала: источник не передаёт данные.";
    default:
      return missing.length > 0 ? `Размечено не всё: ${missing.join(", ")}.` : "Источник не передаёт данные.";
  }
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

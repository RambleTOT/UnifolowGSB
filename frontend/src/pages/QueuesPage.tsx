import { Link } from "react-router-dom";

import { useQueuesAnalytics } from "../api/queries";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { MetricsRow } from "../components/analytics/MetricsRow";
import { HeatmapGrid } from "../components/charts/HeatmapGrid";
import { ShareBars } from "../components/charts/ShareBars";
import { TimeChart } from "../components/charts/TimeChart";
import { EventCard } from "../components/events/EventCard";
import { label } from "../lib/dictionary";
import { formatDateTime, formatDurationSeconds, formatNumber } from "../lib/format";
import { useFilters } from "../state/filters";
import { useSession } from "../state/session";

export function QueuesPage() {
  const { filters, update } = useFilters();
  const { user } = useSession();
  const dataset = user?.dataset ?? "real";
  const query = useQueuesAnalytics(
    { period: filters.period, scope: filters.scope, from: filters.from, to: filters.to },
    dataset,
  );
  const data = query.data;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">Анализ очередей</h1>
          <p className="page__subtitle">
            {data
              ? `Период: ${label("period", data.window.period)} · шаг ${data.window.stepTitle}`
              : "Где и когда возникают очереди и сколько люди ждут"}
          </p>
        </div>
        <Link className="btn btn--secondary btn--md" to="/reports">
          Отчёт по этому срезу
        </Link>
      </header>

      <DataBlock
        state={blockState({
          isLoading: query.isLoading,
          isFetching: query.isFetching,
          isError: query.isError,
        })}
        error={query.error}
        onRetry={() => query.refetch()}
      >
        {data && !data.applicable ? (
          <Panel>
            <EmptyState
              tone="warn"
              title="В выборке нет зон очереди"
              description={data.notApplicableReason ?? ""}
              action={
                <div className="row-actions">
                  <button type="button" className="btn btn--secondary btn--md" onClick={() => update({ scope: "canteen" })}>
                    Смотреть столовую
                  </button>
                  <Link className="btn btn--primary btn--md" to="/sources">
                    Разметить зону очереди
                  </Link>
                </div>
              }
            />
          </Panel>
        ) : (
          data && (
            <div className="page__stack">
              <MetricsRow metrics={data.metrics} />

              <Panel
                title="Очередь и ожидание"
                meta={`порог очереди ${data.thresholds.queue} чел · порог ожидания ${data.thresholds.waitMinutes} мин`}
              >
                {data.queueSeries.some((point) => point.queue !== null) ? (
                  <TimeChart
                    data={data.queueSeries}
                    stepSeconds={data.window.stepSeconds}
                    series={[
                      { key: "queue", name: "Очередь", color: "#1b5fcb", type: "area", unit: "чел" },
                      { key: "queueMax", name: "Пик очереди", color: "#4b84ff", unit: "чел" },
                      { key: "waitMinutes", name: "Ожидание", color: "#9a6b12", unit: "мин", axis: "right" },
                    ]}
                    threshold={{ value: data.thresholds.queue, label: "порог очереди" }}
                    height={300}
                  />
                ) : (
                  <EmptyState
                    title="За период данных нет"
                    description="Выберите другой период или проверьте, работают ли источники."
                  />
                )}
              </Panel>

              <div className="grid-2">
                <Panel title="Сравнение зон очереди" meta="Какая зона даёт наибольшую задержку">
                  {data.zones.length > 0 ? (
                    <ShareBars
                      unit="чел"
                      items={data.zones.map((zone) => ({
                        id: `${zone.sourceId}-${zone.zoneId}`,
                        name: `${zone.name} · ${zone.sourceName}`,
                        note:
                          zone.waitAvgMinutes !== null
                            ? `ожидание ${zone.waitAvgMinutes} мин · пик ${zone.queueMax} чел`
                            : `пик ${zone.queueMax} чел`,
                        value: zone.queueAvg,
                      }))}
                    />
                  ) : (
                    <EmptyState title="Зон очереди в выборке нет" description="Разметьте зону очереди у источника." />
                  )}
                </Panel>

                <Panel title="Тепловая карта очередей" meta="Концентрация нагрузки по дням и часам">
                  {data.heatmap.daysCollected >= data.heatmap.daysRequired ? (
                    <HeatmapGrid
                      heatmap={data.heatmap}
                      metric="queue"
                      onSelect={() => update({ period: "day" })}
                    />
                  ) : (
                    <EmptyState
                      title="Недостаточно истории"
                      description={`Накоплено ${data.heatmap.daysCollected} из ${data.heatmap.daysRequired} суток.`}
                    />
                  )}
                </Panel>
              </div>

              <Panel
                title="События очереди"
                meta="Рост очереди и длительное ожидание"
                actions={<Link to="/events?type=queue_spike">Открыть журнал</Link>}
              >
                {data.events.length > 0 ? (
                  <>
                    <div className="event-grid">
                      {data.events.slice(0, 4).map((event) => (
                        <EventCard key={event.id} event={event} compact />
                      ))}
                    </div>

                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Начало</th>
                            <th>Длительность</th>
                            <th>Событие</th>
                            <th>Приоритет</th>
                            <th>Источник</th>
                            <th>Пик / порог</th>
                            <th>Статус</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.events.map((event) => (
                            <tr key={event.id}>
                              <td className="tabular">{formatDateTime(event.startedAt)}</td>
                              <td className="tabular">
                                {event.ongoing ? "идёт" : formatDurationSeconds(event.durationSeconds)}
                              </td>
                              <td>
                                <Link to={`/events/${event.id}`}>{label("eventType", event.type)}</Link>
                              </td>
                              <td>{label("severity", event.severity)}</td>
                              <td>
                                <Link to={`/monitor?source=${event.sourceId}`}>{event.sourceName}</Link>
                              </td>
                              <td className="tabular">
                                {formatNumber(event.peakValue)} / {formatNumber(event.threshold)}
                              </td>
                              <td>{label("eventStatus", event.status)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <p className="ok-note">За период очередь ни разу не выходила за порог.</p>
                )}
              </Panel>
            </div>
          )
        )}
      </DataBlock>
    </div>
  );
}

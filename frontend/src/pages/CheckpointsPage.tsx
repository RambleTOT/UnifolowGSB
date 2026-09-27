import { Link } from "react-router-dom";

import { useCheckpointsAnalytics } from "../api/queries";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { MetricsRow } from "../components/analytics/MetricsRow";
import { ShareBars } from "../components/charts/ShareBars";
import { TimeChart } from "../components/charts/TimeChart";
import { EventCard } from "../components/events/EventCard";
import { label } from "../lib/dictionary";
import { formatNumber } from "../lib/format";
import { useFilters } from "../state/filters";
import { useSession } from "../state/session";

export function CheckpointsPage() {
  const { filters, update } = useFilters();
  const { user } = useSession();
  const dataset = user?.dataset ?? "real";
  const query = useCheckpointsAnalytics(
    { period: filters.period, scope: filters.scope, from: filters.from, to: filters.to },
    dataset,
  );
  const data = query.data;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">Анализ КПП</h1>
          <p className="page__subtitle">
            {data
              ? `Период: ${label("period", data.window.period)} · шаг ${data.window.stepTitle}`
              : "Поток через проходные, их сбалансированность и пропускная способность"}
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
              title="В выборке нет контрольных линий"
              description={data.notApplicableReason ?? ""}
              action={
                <div className="row-actions">
                  <button type="button" className="btn btn--secondary btn--md" onClick={() => update({ scope: "gate" })}>
                    Смотреть КПП
                  </button>
                  <Link className="btn btn--primary btn--md" to="/sources">
                    Разметить линию
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
                title="Входы и выходы во времени"
                meta={`шаг ${data.window.stepTitle} · порог перегрузки ${data.thresholds.checkpointPerMinute} чел/мин`}
              >
                {data.flowSeries.some((point) => point.entered !== null) ? (
                  <TimeChart
                    data={data.flowSeries}
                    stepSeconds={data.window.stepSeconds}
                    series={[
                      { key: "entered", name: "Входы", color: "#1b5fcb", type: "area", unit: "чел" },
                      { key: "exited", name: "Выходы", color: "#1b6b4e", unit: "чел" },
                    ]}
                    height={300}
                  />
                ) : (
                  <EmptyState title="За период данных нет" description="Проверьте период и состояние источников." />
                )}
              </Panel>

              <div className="grid-2">
                <Panel title="Баланс направлений" meta="Сколько людей входит и сколько выходит">
                  <div className="balance">
                    <div className="balance__bar">
                      <div
                        className="balance__in"
                        style={{ width: `${data.direction.enteredShare}%` }}
                        title={`Входы: ${formatNumber(data.direction.entered)} чел`}
                      />
                      <div
                        className="balance__out"
                        style={{ width: `${100 - data.direction.enteredShare}%` }}
                        title={`Выходы: ${formatNumber(data.direction.exited)} чел`}
                      />
                    </div>
                    <div className="balance__legend">
                      <span>
                        <b className="tabular">{formatNumber(data.direction.entered)} чел</b> входы ·{" "}
                        {data.direction.enteredShare} %
                      </span>
                      <span>
                        <b className="tabular">{formatNumber(data.direction.exited)} чел</b> выходы ·{" "}
                        {Math.round(100 - data.direction.enteredShare)} %
                      </span>
                    </div>
                  </div>
                </Panel>

                <Panel
                  title="Сравнение проходов"
                  meta={data.singleCheckpoint ? "Нужно минимум два источника" : "Доля нагрузки каждой линии"}
                >
                  {data.singleCheckpoint ? (
                    <EmptyState
                      title="Сравнивать не с чем"
                      description="В выборке один источник. Добавьте второй проход или смените контур, чтобы увидеть сравнение."
                      action={<Link to="/sources/new">Добавить источник</Link>}
                    />
                  ) : data.lines.length > 0 ? (
                    <ShareBars
                      unit="проходов"
                      items={data.lines.map((line) => ({
                        id: `${line.sourceId}-${line.lineId}`,
                        name: `${line.sourceName} · ${line.name}`,
                        note: `↑ ${line.entered} / ↓ ${line.exited}`,
                        value: line.total,
                        share: line.share,
                      }))}
                    />
                  ) : (
                    <EmptyState title="Линий в выборке нет" description="Разметьте контрольную линию у источника." />
                  )}
                </Panel>
              </div>

              <Panel title="Сравнение по дням недели" meta="Текущая неделя против типового профиля">
                {data.weekdays.some((day) => day.baseline !== null) ? (
                  <TimeChart
                    data={data.weekdays.map((day) => ({
                      at: day.title,
                      samples: 1,
                      current: day.current,
                      baseline: day.baseline,
                    }))}
                    stepSeconds={24 * 3600}
                    series={[
                      { key: "current", name: "Текущая неделя", color: "#1b5fcb", unit: "чел" },
                      { key: "baseline", name: "Типовой профиль", color: "#8992a2", unit: "чел" },
                    ]}
                    height={220}
                  />
                ) : (
                  <EmptyState
                    title="Недостаточно истории"
                    description="Типовой профиль строится по нескольким неделям наблюдений."
                  />
                )}
              </Panel>

              <Panel
                title="События КПП"
                meta="Перегрузка, нетипичный трафик и проблемы с источником"
                actions={<Link to="/events?type=checkpoint_overload">Открыть журнал</Link>}
              >
                {data.events.length > 0 ? (
                  <div className="event-grid">
                    {data.events.slice(0, 6).map((event) => (
                      <EventCard key={event.id} event={event} compact />
                    ))}
                  </div>
                ) : (
                  <p className="ok-note">За период поток через проходы не выходил за порог.</p>
                )}
              </Panel>
            </div>
          )
        )}
      </DataBlock>
    </div>
  );
}

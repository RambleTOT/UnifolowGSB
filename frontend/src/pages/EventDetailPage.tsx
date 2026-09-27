import { Link, useNavigate, useParams } from "react-router-dom";

import { useEvent } from "../api/queries";
import { Button } from "../components/common/Button";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { StatusPill } from "../components/common/StatusPill";
import { useToasts } from "../components/common/Toasts";
import { TimeChart } from "../components/charts/TimeChart";
import { EventCard } from "../components/events/EventCard";
import { StatusControls } from "../components/events/StatusControls";
import { label, severityTone } from "../lib/dictionary";
import { formatClock, formatDateTime, formatDurationSeconds, formatNumber } from "../lib/format";

const SERIES_BY_TYPE: Record<string, { key: string; name: string; color: string; unit: string }> = {
  queue_spike: { key: "queue", name: "Очередь", color: "#1b5fcb", unit: "чел" },
  slow_movement: { key: "waitMinutes", name: "Ожидание", color: "#9a6b12", unit: "мин" },
  checkpoint_overload: { key: "entered", name: "Входы", color: "#1b5fcb", unit: "чел" },
  abnormal_traffic: { key: "entered", name: "Входы", color: "#1b5fcb", unit: "чел" },
  camera_drop: { key: "entered", name: "Входы", color: "#1b5fcb", unit: "чел" },
};

export function EventDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const toasts = useToasts();
  const eventId = Number(params.id);
  const query = useEvent(Number.isFinite(eventId) ? eventId : null);

  const data = query.data;
  const event = data?.event;
  const series = SERIES_BY_TYPE[event?.type ?? "queue_spike"] ?? SERIES_BY_TYPE.queue_spike;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{event?.title ?? "Событие"}</h1>
          <p className="page__subtitle">
            {event
              ? `${label("eventType", event.type)} · ${event.sourceName}`
              : "Разбор одного эпизода"}
          </p>
        </div>
        <div className="row-actions">
          <Button onClick={() => navigate(-1)}>Назад</Button>
          {event && (
            <>
              <Link className="btn btn--secondary btn--md" to={`/monitor?source=${event.sourceId}`}>
                Открыть источник
              </Link>
              <Button
                onClick={() => {
                  navigator.clipboard?.writeText(window.location.href);
                  toasts.success("Ссылка на событие скопирована");
                }}
              >
                Скопировать ссылку
              </Button>
            </>
          )}
        </div>
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
        {!event ? (
          <Panel>
            <EmptyState
              title="Событие не найдено"
              description="Возможно, оно относится к другому набору данных или было удалено."
              action={<Link to="/events">К журналу событий</Link>}
            />
          </Panel>
        ) : (
          <div className="detail">
            <div className="page__stack">
              <Panel title="Что произошло">
                <div className="event-summary">
                  <div className="event-summary__badges">
                    <StatusPill
                      status={event.severity}
                      dictionary="severity"
                      tone={severityTone(event.severity)}
                    />
                    <StatusPill
                      status={event.status}
                      dictionary="eventStatus"
                      tone={event.status === "resolved" ? "ok" : "warn"}
                    />
                    <span className={event.ongoing ? "event__ongoing" : "muted"}>
                      {event.ongoing ? "Идёт сейчас" : "Завершилось"}
                    </span>
                  </div>
                  <p>{event.description}</p>
                  <dl className="readout">
                    <div className="readout__row">
                      <dt>Начало</dt>
                      <dd className="tabular">{formatDateTime(event.startedAt)}</dd>
                    </div>
                    <div className="readout__row">
                      <dt>Окончание</dt>
                      <dd className="tabular">
                        {event.endedAt ? formatDateTime(event.endedAt) : "ещё идёт"}
                      </dd>
                    </div>
                    <div className="readout__row">
                      <dt>Длительность</dt>
                      <dd className="tabular">{formatDurationSeconds(event.durationSeconds)}</dd>
                    </div>
                    {event.type !== "camera_drop" && (
                      <>
                        <div className="readout__row">
                          <dt>Значение при срабатывании</dt>
                          <dd className="tabular">{formatNumber(event.metricValue)}</dd>
                        </div>
                        <div className="readout__row">
                          <dt>Пик за эпизод</dt>
                          <dd className="tabular">{formatNumber(event.peakValue)}</dd>
                        </div>
                        <div className="readout__row">
                          <dt>Порог</dt>
                          <dd className="tabular">
                            {formatNumber(event.threshold)}
                            {event.exceedPercent !== null && (
                              <span className="readout__note">превышение на {event.exceedPercent} %</span>
                            )}
                          </dd>
                        </div>
                      </>
                    )}
                    {event.videoPositionSeconds !== null && (
                      <div className="readout__row">
                        <dt>Позиция в файле</dt>
                        <dd className="tabular">
                          {formatClock(event.videoPositionSeconds)}
                          {event.loopNumber && (
                            <span className="readout__note">круг {event.loopNumber}</span>
                          )}
                        </dd>
                      </div>
                    )}
                  </dl>
                </div>
              </Panel>

              <Panel
                title="Динамика вокруг события"
                meta={`шаг ${data?.seriesWindow.stepTitle ?? "1 минута"} · получас до и после`}
              >
                {data && data.series.length > 0 ? (
                  <TimeChart
                    data={data.series}
                    stepSeconds={60}
                    series={[{ ...series, type: "area" }]}
                    threshold={
                      event.type === "camera_drop"
                        ? null
                        : { value: event.threshold, label: "порог" }
                    }
                  />
                ) : (
                  <EmptyState
                    title="Динамики нет"
                    description="За этот отрезок интервалы не сохранились: данные могли быть удалены по сроку хранения."
                  />
                )}
              </Panel>

              <Panel title="Кадр события">
                {event.snapshotAvailable ? (
                  <img
                    className="event-snapshot"
                    src={`/api/events/${event.id}/snapshot`}
                    alt={`Кадр события «${event.title}»`}
                  />
                ) : (
                  <EmptyState
                    title="Кадр не сохранён"
                    description={
                      event.dataset === "demo"
                        ? "Это демо-событие: кадра для него не существует."
                        : "Сохранение кадров выключено в настройках, поэтому изображение не записано."
                    }
                  />
                )}
              </Panel>
            </div>

            <div className="detail__side">
              <Panel title="Обработка">
                <StatusControls event={event} />
                <h3 className="subhead">История</h3>
                {event.history && event.history.length > 0 ? (
                  <ol className="history">
                    {event.history.map((item, index) => (
                      <li key={index}>
                        <strong>
                          {label("eventStatus", item.fromStatus || "open")} →{" "}
                          {label("eventStatus", item.toStatus)}
                        </strong>
                        <span className="muted">
                          {formatDateTime(item.at)} · {item.author}
                        </span>
                        {item.comment && <p>{item.comment}</p>}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="muted">Статус ещё никто не менял.</p>
                )}
              </Panel>

              <Panel title="Рядом по времени">
                {data && data.nearby.length > 0 ? (
                  <div className="event-grid">
                    {data.nearby.map((item) => (
                      <EventCard key={item.id} event={item} compact />
                    ))}
                  </div>
                ) : (
                  <p className="muted">Других событий этого источника рядом нет.</p>
                )}
              </Panel>
            </div>
          </div>
        )}
      </DataBlock>
    </div>
  );
}

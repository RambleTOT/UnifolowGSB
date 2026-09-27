import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { eventsParams, useBulkEventStatus, useEvents, useSources } from "../api/queries";
import type { EventView } from "../api/types";
import { Button } from "../components/common/Button";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { Panel } from "../components/common/Panel";
import { StatusPill } from "../components/common/StatusPill";
import { useToasts } from "../components/common/Toasts";
import { EventCard } from "../components/events/EventCard";
import { label, options, severityTone } from "../lib/dictionary";
import { formatDateTime, formatDurationSeconds, formatNumber } from "../lib/format";
import { useFilters } from "../state/filters";
import { useSession } from "../state/session";

/** Колонки журнала: у сортируемых есть ключ, по которому сортирует сервер. */
const COLUMNS: Array<{ title: string; sort?: string }> = [
  { title: "" },
  { title: "Начало", sort: "started_at" },
  { title: "Длительность" },
  { title: "Событие", sort: "type" },
  { title: "Источник" },
  { title: "Приоритет", sort: "severity" },
  { title: "Состояние" },
  { title: "Статус", sort: "status" },
  { title: "Значение / порог" },
];

export function EventsPage() {
  const { filters } = useFilters();
  const { user } = useSession();
  const toasts = useToasts();
  const [params, setParams] = useSearchParams();
  const sourcesQuery = useSources();
  const bulk = useBulkEventStatus();
  const [selected, setSelected] = useState<number[]>([]);

  const query = useMemo(
    () => ({
      period: filters.period,
      scope: filters.scope,
      from: filters.from,
      to: filters.to,
      severity: params.get("severity") ?? "all",
      status: params.get("status") ?? "all",
      state: params.get("state") ?? "all",
      type: params.get("type") ?? "all",
      sourceId: params.get("eventSource") ? Number(params.get("eventSource")) : null,
      q: params.get("q") ?? "",
      sort: params.get("sort") ?? "started_at",
      order: params.get("order") ?? "desc",
      page: Number(params.get("page") ?? 1),
      pageSize: 25,
    }),
    [filters, params],
  );

  const eventsQuery = useEvents(query, user?.dataset ?? "real");
  const data = eventsQuery.data;

  const setFilter = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (!value || value === "all" || value === "") next.delete(key);
    else next.set(key, value);
    next.delete("page");
    setParams(next);
  };

  const sortBy = (field: string) => {
    const next = new URLSearchParams(params);
    if (query.sort === field) {
      next.set("order", query.order === "desc" ? "asc" : "desc");
    } else {
      next.set("sort", field);
      next.set("order", "desc");
    }
    next.delete("page");
    setParams(next);
  };

  const activeFilters = [
    query.severity !== "all" && { key: "severity", text: `Приоритет: ${label("severity", query.severity)}` },
    query.status !== "all" && { key: "status", text: `Статус: ${label("eventStatus", query.status)}` },
    query.state !== "all" && {
      key: "state",
      text: query.state === "ongoing" ? "Только продолжающиеся" : "Только завершившиеся",
    },
    query.type !== "all" && { key: "type", text: `Тип: ${label("eventType", query.type)}` },
    query.sourceId && {
      key: "eventSource",
      text: `Источник: ${sourcesQuery.data?.sources.find((item) => item.id === query.sourceId)?.name ?? query.sourceId}`,
    },
    query.q && { key: "q", text: `Поиск: ${query.q}` },
  ].filter(Boolean) as Array<{ key: string; text: string }>;

  const attention = (data?.events ?? []).filter(
    (event) => event.status !== "resolved" && ["high", "critical"].includes(event.severity),
  );

  const toggle = (id: number) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );

  const exportUrl = (format: "csv" | "xlsx") =>
    `/api/events/export?${eventsParams({ ...query, page: undefined, pageSize: undefined })}&format=${format}`;

  const pages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">История и события</h1>
          <p className="page__subtitle">
            Журнал эпизодов для разбора и отчётности. Период и контур берутся из верхней панели.
          </p>
        </div>
        <div className="row-actions">
          <a className="btn btn--secondary btn--md" href={exportUrl("csv")}>
            Выгрузить CSV
          </a>
          <a className="btn btn--secondary btn--md" href={exportUrl("xlsx")}>
            Выгрузить Excel
          </a>
        </div>
      </header>

      <Panel title="Фильтры" meta={data ? `Найдено событий: ${data.total}` : undefined}>
        <div className="filters">
          <input
            className="input"
            placeholder="Поиск по заголовку и описанию"
            defaultValue={query.q}
            onKeyDown={(event) => {
              if (event.key === "Enter") setFilter("q", (event.target as HTMLInputElement).value);
            }}
            onBlur={(event) => setFilter("q", event.target.value)}
          />
          <select className="input" value={query.severity} onChange={(e) => setFilter("severity", e.target.value)}>
            <option value="all">Любой приоритет</option>
            {options("severity").map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <select className="input" value={query.status} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="all">Любой статус</option>
            {options("eventStatus").map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <select className="input" value={query.state} onChange={(e) => setFilter("state", e.target.value)}>
            <option value="all">Любое состояние</option>
            <option value="ongoing">Продолжается</option>
            <option value="finished">Завершилось</option>
          </select>
          <select className="input" value={query.type} onChange={(e) => setFilter("type", e.target.value)}>
            <option value="all">Любой тип</option>
            {options("eventType").map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <select
            className="input"
            value={query.sourceId ?? "all"}
            onChange={(e) => setFilter("eventSource", e.target.value)}
          >
            <option value="all">Любой источник</option>
            {sourcesQuery.data?.sources.map((source) => (
              <option key={source.id} value={source.id}>{source.name}</option>
            ))}
          </select>
        </div>

        {activeFilters.length > 0 && (
          <div className="filters__active">
            {activeFilters.map((item) => (
              <button key={item.key} type="button" className="chip chip--active" onClick={() => setFilter(item.key, null)}>
                {item.text} ×
              </button>
            ))}
            <Button size="sm" variant="ghost" onClick={() => setParams(new URLSearchParams())}>
              Сбросить всё
            </Button>
          </div>
        )}
      </Panel>

      <DataBlock
        state={blockState({
          isLoading: eventsQuery.isLoading,
          isFetching: eventsQuery.isFetching,
          isError: eventsQuery.isError,
          isEmpty: data?.total === 0 && activeFilters.length === 0,
        })}
        error={eventsQuery.error}
        onRetry={() => eventsQuery.refetch()}
        emptyTitle="Событий ещё не было"
        emptyDescription="События появляются, когда очередь, поток или состояние источника выходят за пороги из настроек."
      >
        {data && data.total === 0 && activeFilters.length > 0 ? (
          <Panel>
            <DataBlock
              state="empty-by-filter"
              onResetFilters={() => setParams(new URLSearchParams())}
              filterDescription="По выбранным фильтрам событий нет. Снимите часть условий или расширьте период."
            >
              <span />
            </DataBlock>
          </Panel>
        ) : (
          <div className="page__stack">
            {attention.length > 0 && (
              <Panel title="Требуют внимания" meta="Продолжающиеся и неразобранные, высокий и критический приоритет">
                <div className="event-grid">
                  {attention.slice(0, 4).map((event) => (
                    <EventCard key={event.id} event={event} compact />
                  ))}
                </div>
              </Panel>
            )}

            <Panel
              title="Журнал событий"
              meta={data ? `Страница ${data.page} из ${pages}` : undefined}
              actions={
                selected.length > 0 && (
                  <div className="row-actions">
                    <span className="muted">Выбрано: {selected.length}</span>
                    <Button
                      size="sm"
                      onClick={() =>
                        bulk.mutate(
                          { ids: selected, status: "investigating" },
                          {
                            onSuccess: (result) => {
                              toasts.success(result.message);
                              setSelected([]);
                            },
                          },
                        )
                      }
                    >
                      Взять в работу
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() =>
                        bulk.mutate(
                          { ids: selected, status: "resolved" },
                          {
                            onSuccess: (result) => {
                              toasts.success(result.message);
                              setSelected([]);
                            },
                          },
                        )
                      }
                    >
                      Решено
                    </Button>
                  </div>
                )
              }
            >
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      {COLUMNS.map((column) => (
                        <th key={column.title || "checkbox"}>
                          {column.sort ? (
                            <button
                              type="button"
                              className={`table__sort ${query.sort === column.sort ? "table__sort--active" : ""}`}
                              onClick={() => sortBy(column.sort!)}
                              title={
                                query.sort === column.sort
                                  ? "Изменить порядок сортировки"
                                  : `Сортировать по колонке «${column.title}»`
                              }
                            >
                              {column.title}
                              <span aria-hidden="true">
                                {query.sort === column.sort ? (query.order === "desc" ? "↓" : "↑") : "↕"}
                              </span>
                            </button>
                          ) : (
                            column.title
                          )}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data?.events.map((event: EventView) => (
                      <tr key={event.id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selected.includes(event.id)}
                            onChange={() => toggle(event.id)}
                            aria-label={`Выбрать событие «${event.title}»`}
                          />
                        </td>
                        <td className="tabular">{formatDateTime(event.startedAt)}</td>
                        <td className="tabular">
                          {event.ongoing ? "идёт" : formatDurationSeconds(event.durationSeconds)}
                        </td>
                        <td>
                          <Link to={`/events/${event.id}`}>{event.title}</Link>
                          <div className="muted">{event.description}</div>
                        </td>
                        <td>
                          <Link to={`/monitor?source=${event.sourceId}`}>{event.sourceName}</Link>
                        </td>
                        <td>
                          <StatusPill
                            status={event.severity}
                            dictionary="severity"
                            tone={severityTone(event.severity)}
                          />
                        </td>
                        <td>{event.ongoing ? "Продолжается" : "Завершилось"}</td>
                        <td>{label("eventStatus", event.status)}</td>
                        <td className="tabular">
                          {event.type === "camera_drop"
                            ? "—"
                            : `${formatNumber(event.peakValue)} / ${formatNumber(event.threshold)}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {pages > 1 && (
                <div className="pager">
                  <Button
                    size="sm"
                    disabled={query.page <= 1}
                    disabledReason="Это первая страница"
                    onClick={() => setFilter("page", String(query.page - 1))}
                  >
                    Назад
                  </Button>
                  <span className="muted">
                    Страница {query.page} из {pages}
                  </span>
                  <Button
                    size="sm"
                    disabled={query.page >= pages}
                    disabledReason="Это последняя страница"
                    onClick={() => setFilter("page", String(query.page + 1))}
                  >
                    Вперёд
                  </Button>
                </div>
              )}
            </Panel>
          </div>
        )}
      </DataBlock>
    </div>
  );
}

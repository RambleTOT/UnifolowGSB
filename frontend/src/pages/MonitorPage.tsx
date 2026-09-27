import { useEffect } from "react";
import { Link } from "react-router-dom";

import { useSources } from "../api/queries";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { SourceDetail } from "../components/monitor/SourceDetail";
import { SourceWall } from "../components/monitor/SourceWall";
import { useFilters } from "../state/filters";
import { useSession } from "../state/session";

export function MonitorPage() {
  const { filters, update } = useFilters();
  const { liveUpdates, user } = useSession();
  const sourcesQuery = useSources();

  const all = sourcesQuery.data?.sources ?? [];
  const requestedMissing =
    filters.sourceId !== null &&
    all.length > 0 &&
    !all.some((item) => item.id === filters.sourceId);
  // Контур фильтрует список источников, живая часть от периода не зависит.
  const sources = filters.scope === "all" ? all : all.filter((item) => item.scope === filters.scope);
  const selected = sources.find((item) => item.id === filters.sourceId) ?? sources[0] ?? null;

  // Выбранный источник живёт в адресе: ссылкой можно поделиться.
  useEffect(() => {
    if (requestedMissing) return;
    if (selected && filters.sourceId !== selected.id) {
      update({ sourceId: selected.id }, { replace: true });
    }
  }, [selected?.id]);

  // Переход к источнику вне выбранного контура сбрасывает контур (ТЗ, 4.5).
  useEffect(() => {
    if (filters.sourceId && !sources.some((item) => item.id === filters.sourceId)) {
      const outside = all.find((item) => item.id === filters.sourceId);
      if (outside) update({ scope: "all" }, { replace: true });
    }
  }, [filters.sourceId, sources.length, all.length]);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">Оперативный мониторинг</h1>
          <p className="page__subtitle">
            Живая часть не зависит от периода: она всегда показывает текущий момент.
            {user?.dataset === "demo" && " Этот раздел показывает реальное состояние, а не демо-данные."}
          </p>
        </div>
      </header>

      <DataBlock
        state={blockState({
          isLoading: sourcesQuery.isLoading,
          isFetching: sourcesQuery.isFetching,
          isError: sourcesQuery.isError,
          isEmpty: all.length === 0,
        })}
        error={sourcesQuery.error}
        onRetry={() => sourcesQuery.refetch()}
        emptyTitle="Источников пока нет"
        emptyDescription="Добавьте источник и загрузите видео — после этого появится живая картинка."
        emptyAction={<Link to="/sources/new">Добавить источник</Link>}
      >
        {requestedMissing ? (
          <Panel>
            <EmptyState
              tone="warn"
              title="Источник не найден"
              description="Возможно, его удалили или ссылка устарела. Выберите источник из списка."
              action={
                <div className="row-actions">
                  <button
                    type="button"
                    className="btn btn--secondary btn--md"
                    onClick={() => update({ sourceId: null }, { replace: true })}
                  >
                    Показать все источники
                  </button>
                  <Link className="btn btn--primary btn--md" to="/sources">
                    К списку источников
                  </Link>
                </div>
              }
            />
          </Panel>
        ) : sources.length === 0 ? (
          <Panel>
            <EmptyState
              tone="warn"
              title="В выбранном контуре нет источников"
              description="Смените контур в верхней панели или добавьте источник в этот контур."
              action={<Link to="/sources/new">Добавить источник</Link>}
            />
          </Panel>
        ) : (
          <div className="page__stack">
            <SourceWall
              sources={sources}
              selectedId={selected?.id ?? null}
              onSelect={(id) => update({ sourceId: id })}
            />
            {/* Новый источник — новый просмотр: рамки, медианы и вспышки не переносятся. */}
            {selected && <SourceDetail key={selected.id} source={selected} enabled={liveUpdates} />}
          </div>
        )}
      </DataBlock>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { fetchFrame, useGeometry, useSaveGeometry, useSource } from "../api/queries";
import type { FramePreview } from "../api/types";
import { Button } from "../components/common/Button";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { EmptyState } from "../components/common/EmptyState";
import { Field } from "../components/common/Field";
import { Panel } from "../components/common/Panel";
import { useToasts } from "../components/common/Toasts";
import { useUnsavedGuard } from "../components/common/UnsavedGuard";
import { MarkupCanvas } from "../components/markup/MarkupCanvas";
import {
  cloneMarkup,
  defaultLine,
  defaultZone,
  emptyMarkup,
  type Draft,
} from "../components/markup/geometry";
import { label, options } from "../lib/dictionary";
import { formatClock } from "../lib/format";

export function MarkupPage() {
  const params = useParams();
  const sourceId = Number(params.id);
  const toasts = useToasts();

  const sourceQuery = useSource(sourceId);
  const geometryQuery = useGeometry(sourceId);
  const save = useSaveGeometry(sourceId);

  const [draft, setDraft] = useState<Draft>(emptyMarkup());
  const [saved, setSaved] = useState<Draft>(emptyMarkup());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [frame, setFrame] = useState<FramePreview | null>(null);
  const [frameLoading, setFrameLoading] = useState(false);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [position, setPosition] = useState(0);

  // История — состояние, а не ссылка: кнопки «Отменить» и «Повторить» должны
  // гаснуть и загораться сразу, а не на следующей перерисовке по другой причине.
  const [history, setHistory] = useState<Draft[]>([]);
  const [future, setFuture] = useState<Draft[]>([]);
  // Снимок разметки до начала перетаскивания: в историю попадает он, иначе
  // отмена после перетаскивания отбросила бы и все правки до него.
  const beforeDrag = useRef<Draft | null>(null);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(saved), [draft, saved]);
  useUnsavedGuard(dirty);

  useEffect(() => {
    const markup = geometryQuery.data;
    if (!markup) return;
    setDraft(cloneMarkup(markup));
    setSaved(cloneMarkup(markup));
    setHistory([]);
    setFuture([]);
    beforeDrag.current = null;
  }, [geometryQuery.data]);

  const loadFrame = useCallback(
    (seconds: number) => {
      setFrameLoading(true);
      setFrameError(null);
      fetchFrame(sourceId, seconds)
        .then((data) => setFrame(data))
        .catch((error: ApiError) => setFrameError(error.message))
        .finally(() => setFrameLoading(false));
    },
    [sourceId],
  );

  useEffect(() => {
    if (sourceQuery.data?.videoAvailable) loadFrame(0);
  }, [sourceQuery.data?.videoAvailable, loadFrame]);

  const remember = (state: Draft) => {
    setHistory((items) => [...items.slice(-49), cloneMarkup(state)]);
    setFuture([]);
  };

  const commit = (next: Draft) => {
    remember(draft);
    setDraft(next);
  };

  const change = (next: Draft, options?: { commit?: boolean }) => {
    if (options?.commit) {
      // Перетаскивание закончилось: в историю уходит состояние до его начала.
      const before = beforeDrag.current;
      beforeDrag.current = null;
      if (before) remember(before);
      return;
    }
    if (!beforeDrag.current) beforeDrag.current = cloneMarkup(draft);
    setDraft(next);
  };

  const undo = () => {
    const previous = history[history.length - 1];
    if (!previous) return;
    setHistory((items) => items.slice(0, -1));
    setFuture((items) => [...items, cloneMarkup(draft)]);
    setDraft(previous);
  };

  const redo = () => {
    const next = future[future.length - 1];
    if (!next) return;
    setFuture((items) => items.slice(0, -1));
    setHistory((items) => [...items, cloneMarkup(draft)]);
    setDraft(next);
  };

  const revert = () => {
    remember(draft);
    setDraft(cloneMarkup(saved));
    setProblems({});
  };

  const addZone = (kind: "queue" | "occupancy") => {
    const zone = defaultZone(kind, draft.zones.map((item) => item.id));
    commit({ ...draft, zones: [...draft.zones, zone] });
    setSelectedId(zone.id);
  };

  const addLine = () => {
    const line = defaultLine(draft.lines.map((item) => item.id));
    commit({ ...draft, lines: [...draft.lines, line] });
    setSelectedId(line.id);
  };

  const removeSelected = () => {
    if (!selectedId) return;
    commit({
      ...draft,
      zones: draft.zones.filter((zone) => zone.id !== selectedId),
      lines: draft.lines.filter((line) => line.id !== selectedId),
    });
    setSelectedId(null);
  };

  const selectedZone = draft.zones.find((zone) => zone.id === selectedId) ?? null;
  const selectedLine = draft.lines.find((line) => line.id === selectedId) ?? null;

  const patchZone = (changes: Partial<(typeof draft.zones)[number]>) => {
    if (!selectedZone) return;
    commit({
      ...draft,
      zones: draft.zones.map((zone) => (zone.id === selectedZone.id ? { ...zone, ...changes } : zone)),
    });
  };

  const patchLine = (changes: Partial<(typeof draft.lines)[number]>) => {
    if (!selectedLine) return;
    commit({
      ...draft,
      lines: draft.lines.map((line) => (line.id === selectedLine.id ? { ...line, ...changes } : line)),
    });
  };

  const onSave = () => {
    setProblems({});
    save.mutate(draft, {
      onSuccess: (data) => {
        setSaved(cloneMarkup(data.markup));
        setDraft(cloneMarkup(data.markup));
        toasts.success("Разметка сохранена", data.message);
      },
      onError: (error) => {
        if (error instanceof ApiError && error.objects.length > 0) {
          const map: Record<string, string> = {};
          error.objects.forEach((problem) => {
            map[problem.id] = problem.message;
          });
          setProblems(map);
          toasts.error("Разметку нельзя сохранить", error.objects.map((item) => item.message).join(" "));
          return;
        }
        toasts.error("Не удалось сохранить разметку", (error as Error).message);
      },
    });
  };

  const source = sourceQuery.data;
  const empty = draft.zones.length === 0 && draft.lines.length === 0;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">Настройка зон и линий</h1>
          <p className="page__subtitle">
            {source ? `${source.name} · ${source.location}` : ""} — разметка применяется сразу и
            влияет только на новые данные, история не пересчитывается.
          </p>
        </div>
        <div className="row-actions">
          <Link className="btn btn--ghost btn--md" to="/sources">
            К источникам
          </Link>
          <Link className="btn btn--secondary btn--md" to={`/monitor?source=${sourceId}`}>
            В мониторинг
          </Link>
        </div>
      </header>

      <DataBlock
        state={blockState({
          isLoading: sourceQuery.isLoading || geometryQuery.isLoading,
          isError: sourceQuery.isError || geometryQuery.isError,
        })}
        error={sourceQuery.error ?? geometryQuery.error}
        onRetry={() => {
          sourceQuery.refetch();
          geometryQuery.refetch();
        }}
      >
        {!source?.videoAvailable ? (
          <Panel>
            <EmptyState
              tone="warn"
              title="Размечать нечего"
              description={
                source?.connectionType === "stream"
                  ? "У источника не указана ссылка на поток. Укажите её в параметрах источника."
                  : source?.video
                    ? "Видеофайл источника не найден на диске. Замените файл в параметрах источника."
                    : "У источника нет видеофайла. Сначала загрузите видео."
              }
              action={<Link to={`/sources/${sourceId}/edit`}>Параметры источника</Link>}
            />
          </Panel>
        ) : (
          <div className="markup">
            <div className="markup__main">
              <MarkupCanvas
                image={frame?.image ?? null}
                anchors={frame?.anchors ?? []}
                draft={draft}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onChange={change}
                problems={problems}
              />

              <div className="markup__frame-controls">
                {source.connectionType === "stream" ? (
                  <>
                    <span className="muted">Кадр из прямого эфира</span>
                    <Button size="sm" onClick={() => loadFrame(0)} loading={frameLoading}>
                      Взять свежий кадр
                    </Button>
                  </>
                ) : (
                  <>
                    <span className="tabular">
                      Кадр {formatClock(frame?.positionSeconds ?? 0)} из{" "}
                      {formatClock(frame?.durationSeconds ?? source.video?.durationSeconds ?? 0)}
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={Math.max(1, Math.floor(frame?.durationSeconds ?? source.video?.durationSeconds ?? 1))}
                      value={position}
                      onChange={(event) => setPosition(Number(event.target.value))}
                      onMouseUp={() => loadFrame(position)}
                      onTouchEnd={() => loadFrame(position)}
                      aria-label="Позиция в файле"
                    />
                    <Button size="sm" onClick={() => loadFrame(position)} loading={frameLoading}>
                      Выбрать другой кадр
                    </Button>
                  </>
                )}
                <span className="muted">
                  {frame
                    ? frame.anchors.length > 0
                      ? `на кадре найдено людей: ${frame.anchors.length} — белые точки показывают их «ноги»`
                      : "на этом кадре людей не видно: выберите другой момент"
                    : ""}
                </span>
                {frameError && <span className="source-error">{frameError}</span>}
              </div>

              <div className="markup__toolbar">
                <Button size="sm" onClick={() => addZone("queue")}>
                  + Зона очереди
                </Button>
                <Button size="sm" onClick={() => addZone("occupancy")}>
                  + Зона заполненности
                </Button>
                <Button size="sm" onClick={addLine}>
                  + Контрольная линия
                </Button>
                <span className="markup__divider" aria-hidden="true" />
                <Button size="sm" onClick={undo} disabled={history.length === 0} disabledReason="Отменять нечего">
                  Отменить
                </Button>
                <Button size="sm" onClick={redo} disabled={future.length === 0} disabledReason="Повторять нечего">
                  Повторить
                </Button>
                <Button size="sm" onClick={revert} disabled={!dirty} disabledReason="Изменений нет">
                  Вернуть сохранённое
                </Button>
                <span className="markup__divider" aria-hidden="true" />
                <Button variant="primary" onClick={onSave} loading={save.isPending} disabled={!dirty} disabledReason="Изменений нет">
                  Сохранить разметку
                </Button>
                {dirty && <span className="muted">Есть несохранённые изменения</span>}
              </div>
            </div>

            <aside className="markup__side">
              <Panel title="Объекты разметки">
                {empty ? (
                  <p className="muted">
                    Пока пусто. Начните с контрольной линии: по ней считаются входы и выходы.
                  </p>
                ) : (
                  <ul className="object-list">
                    {draft.lines.map((line) => (
                      <li key={line.id}>
                        <button
                          type="button"
                          className={`object-list__item ${selectedId === line.id ? "object-list__item--active" : ""}`}
                          onClick={() => setSelectedId(line.id)}
                        >
                          <strong>{line.name}</strong>
                          <span className="muted">
                            Линия · {label("lineCounts", line.counts)}
                          </span>
                          {problems[line.id] && <span className="source-error">{problems[line.id]}</span>}
                        </button>
                      </li>
                    ))}
                    {draft.zones.map((zone) => (
                      <li key={zone.id}>
                        <button
                          type="button"
                          className={`object-list__item ${selectedId === zone.id ? "object-list__item--active" : ""}`}
                          onClick={() => setSelectedId(zone.id)}
                        >
                          <strong>{zone.name}</strong>
                          <span className="muted">
                            {label("zoneKind", zone.kind)}
                            {zone.kind === "queue" ? ` · порог ${zone.min_dwell_seconds} с` : ""}
                          </span>
                          {problems[zone.id] && <span className="source-error">{problems[zone.id]}</span>}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>

              {selectedLine && (
                <Panel title="Контрольная линия">
                  <Field label="Название" htmlFor="line-name">
                    <input
                      id="line-name"
                      className="input"
                      value={selectedLine.name}
                      onChange={(event) => patchLine({ name: event.target.value })}
                    />
                  </Field>

                  <div className="notice">
                    Сторона «вход» показана стрелкой на кадре. Если направление перепутано, оно
                    меняется одним действием.
                  </div>
                  <Button size="sm" onClick={() => patchLine({ entry_side: selectedLine.entry_side > 0 ? -1 : 1 })}>
                    Развернуть направление
                  </Button>

                  <Field label="Что считать" htmlFor="line-counts">
                    <select
                      id="line-counts"
                      className="input"
                      value={selectedLine.counts}
                      onChange={(event) => patchLine({ counts: event.target.value as "in" | "out" | "both" })}
                    >
                      {options("lineCounts").map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </Field>

                  <Button size="sm" variant="danger" onClick={removeSelected}>
                    Удалить объект
                  </Button>
                </Panel>
              )}

              {selectedZone && (
                <Panel title={label("zoneKind", selectedZone.kind)}>
                  <Field label="Название" htmlFor="zone-name">
                    <input
                      id="zone-name"
                      className="input"
                      value={selectedZone.name}
                      onChange={(event) => patchZone({ name: event.target.value })}
                    />
                  </Field>

                  {selectedZone.kind === "queue" ? (
                    <Field
                      label="Минимальное время в зоне, с"
                      htmlFor="zone-dwell"
                      hint="После этого времени человек считается стоящим в очереди"
                    >
                      <input
                        id="zone-dwell"
                        className="input"
                        type="number"
                        min={1}
                        max={600}
                        value={selectedZone.min_dwell_seconds}
                        onChange={(event) => patchZone({ min_dwell_seconds: Number(event.target.value) })}
                      />
                    </Field>
                  ) : (
                    <Field
                      label="Вместимость, чел"
                      htmlFor="zone-capacity"
                      hint="Необязательно: нужна, чтобы показывать заполненность в процентах"
                    >
                      <input
                        id="zone-capacity"
                        className="input"
                        type="number"
                        min={1}
                        value={selectedZone.capacity ?? ""}
                        onChange={(event) =>
                          patchZone({ capacity: event.target.value ? Number(event.target.value) : null })
                        }
                      />
                    </Field>
                  )}

                  <p className="muted">
                    Точки многоугольника перетаскиваются, вся зона двигается целиком.
                  </p>
                  <Button size="sm" variant="danger" onClick={removeSelected}>
                    Удалить объект
                  </Button>
                </Panel>
              )}

              <Panel title="Как размечать">
                <ul className="tips">
                  <li>
                    Линию ставьте там, где люди проходят её целиком и примерно перпендикулярно
                    движению — подальше от края кадра и дверного проёма.
                  </li>
                  <li>
                    Зону очереди рисуйте по полу там, где люди стоят, а не там, где проходят мимо.
                  </li>
                  <li>
                    Белые точки на кадре — «ноги» найденных людей. Именно по ним засчитывается
                    проход, поэтому ориентируйтесь на них, а не на головы.
                  </li>
                </ul>
              </Panel>
            </aside>
          </div>
        )}
      </DataBlock>
    </div>
  );
}

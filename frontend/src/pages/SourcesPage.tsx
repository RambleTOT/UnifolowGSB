import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useDeleteSource, useSourceAction, useSources } from "../api/queries";
import type { Source } from "../api/types";
import { Button } from "../components/common/Button";
import { ConfirmDialog } from "../components/common/ConfirmDialog";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { Panel } from "../components/common/Panel";
import { StatusPill } from "../components/common/StatusPill";
import { useToasts } from "../components/common/Toasts";
import { label } from "../lib/dictionary";
import { formatFreshness, formatValue } from "../lib/format";

export function SourcesPage() {
  const sourcesQuery = useSources();
  const action = useSourceAction();
  const remove = useDeleteSource();
  const toasts = useToasts();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState<Source | null>(null);

  const sources = sourcesQuery.data?.sources ?? [];

  const runAction = (source: Source, kind: "enable" | "disable" | "check" | "restart") => {
    action.mutate(
      { id: source.id, action: kind },
      {
        onSuccess: (data) => {
          if (kind === "check") {
            const ok = (data as { ok: boolean }).ok;
            const message = (data as { message: string }).message;
            const video = (data as { video?: { durationSeconds: number; resolution: string; fps: number } }).video;
            const stream = (data as { stream?: { resolution: string; fps: number } }).stream;
            if (ok && video) {
              toasts.success(message, `${video.resolution}, ${video.fps} кадр/с, ${Math.round(video.durationSeconds)} с`);
            } else if (ok && stream) {
              toasts.success(message, `${stream.resolution}, ${stream.fps} кадр/с`);
            } else if (ok) {
              toasts.success(message);
            } else {
              toasts.error("Источник недоступен", message);
            }
            return;
          }
          toasts.success(
            kind === "enable"
              ? `Источник «${source.name}» включён`
              : kind === "disable"
                ? `Источник «${source.name}» выключен`
                : `Анализ источника «${source.name}» перезапущен`,
          );
        },
        onError: (error) => toasts.error("Действие не выполнено", (error as Error).message),
      },
    );
  };

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">Источники видео</h1>
          <p className="page__subtitle">
            Источник — это видеофайл, который воспроизводится по кругу, или прямой поток с камеры по
            ссылке. Раздел всегда показывает реальное состояние.
          </p>
        </div>
        <Button variant="primary" onClick={() => navigate("/sources/new")}>
          Добавить источник
        </Button>
      </header>

      <DataBlock
        state={blockState({
          isLoading: sourcesQuery.isLoading,
          isFetching: sourcesQuery.isFetching,
          isError: sourcesQuery.isError,
          isEmpty: sources.length === 0,
        })}
        error={sourcesQuery.error}
        onRetry={() => sourcesQuery.refetch()}
        emptyTitle="Источников пока нет"
        emptyDescription="Добавьте первый источник: загрузите видео и разметьте линию — счётчики пойдут сразу."
        emptyAction={<Link to="/sources/new">Добавить источник</Link>}
      >
        <div className="page__stack">
          {sources.map((source) => (
            <Panel
              key={source.id}
              title={
                <span className="source-head">
                  {source.name}
                  <StatusPill status={source.status} />
                  <span className={`readiness readiness--${source.readiness.state}`}>
                    {label("readiness", source.readiness.state)}
                  </span>
                </span>
              }
              meta={
                <>
                  <span>{label("scope", source.scope)}</span>
                  {source.location && <span>{source.location}</span>}
                  {source.lastSignalAt && <span>сигнал {formatFreshness(source.lastSignalAt)}</span>}
                </>
              }
              actions={
                <div className="row-actions">
                  <Link className="btn btn--secondary btn--sm" to={`/monitor?source=${source.id}`}>
                    Мониторинг
                  </Link>
                  <Link className="btn btn--secondary btn--sm" to={`/sources/${source.id}/markup`}>
                    Зоны и линии
                  </Link>
                  <Link className="btn btn--secondary btn--sm" to={`/sources/${source.id}/edit`}>
                    Параметры
                  </Link>
                  <Button
                    size="sm"
                    onClick={() => runAction(source, "check")}
                    loading={action.isPending}
                    disabled={source.connectionType === "stream" ? !source.streamUrl : !source.video}
                    disabledReason={
                      source.connectionType === "stream"
                        ? "Не указана ссылка на поток"
                        : "Источнику не назначен видеофайл"
                    }
                  >
                    Проверить
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => runAction(source, source.enabled ? "disable" : "enable")}
                  >
                    {source.enabled ? "Выключить" : "Включить"}
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => setConfirm(source)}>
                    Удалить
                  </Button>
                </div>
              }
            >
              <div className="source-grid">
                {source.connectionType === "stream" ? (
                  <>
                    <Detail title="Прямой поток" value={streamHost(source.streamUrl)} />
                    <Detail title="Разрешение" value={liveResolution(source)} />
                    <Detail title="Анализ" value="в реальном времени" />
                  </>
                ) : (
                  <>
                    <Detail title="Видеофайл" value={source.video?.name ?? "не назначен"} />
                    <Detail title="Разрешение" value={source.video?.resolution ?? "—"} />
                    <Detail
                      title="Длительность"
                      value={formatValue(source.video?.durationSeconds ?? null, "с", true)}
                    />
                  </>
                )}
                <Detail title="Профиль модели" value={label("modelProfile", source.modelProfile)} />
                <Detail
                  title="Порог уверенности"
                  value={source.confidence === null ? "из настроек системы" : String(source.confidence)}
                />
                <Detail
                  title="Интервал агрегации"
                  value={
                    source.aggregationSeconds === null
                      ? "из настроек системы"
                      : `${source.aggregationSeconds} с`
                  }
                />
              </div>

              {source.readiness.missing.length > 0 && (
                <p className="source-missing">
                  Не считается: {source.readiness.missing.join(", ")}.{" "}
                  <Link to={`/sources/${source.id}/markup`}>Разметить</Link>
                </p>
              )}
              {source.lastError && <p className="source-error">{source.lastError}</p>}
            </Panel>
          ))}
        </div>
      </DataBlock>

      <ConfirmDialog
        open={confirm !== null}
        tone="danger"
        title={`Удалить источник «${confirm?.name}»?`}
        description={
          <>
            Источник перестанет анализироваться и исчезнет из списков. Накопленные данные и события
            останутся в аналитике и журнале с пометкой «источник удалён».
          </>
        }
        confirmLabel="Удалить"
        busy={remove.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (!confirm) return;
          remove.mutate(confirm.id, {
            onSuccess: (data) => {
              toasts.success("Источник удалён", data.message);
              setConfirm(null);
            },
            onError: (error) => toasts.error("Не удалось удалить источник", (error as Error).message),
          });
        }}
      />
    </div>
  );
}

function Detail({ title, value }: { title: string; value: string }) {
  return (
    <div className="source-grid__item">
      <span className="muted">{title}</span>
      <strong>{value}</strong>
    </div>
  );
}

/** Для карточки хватает адреса камеры: полная ссылка длинная и бывает с токенами. */
function streamHost(url: string | null): string {
  if (!url) return "ссылка не указана";
  try {
    return new URL(url).host;
  } catch {
    return url.slice(0, 40);
  }
}

/** Разрешение потока известно только после подключения — его сообщает рабочий поток. */
function liveResolution(source: Source): string {
  return source.live?.resolution ?? "станет известно после подключения";
}

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, upload } from "../api/client";
import {
  useCreateSource,
  useHealth,
  useSource,
  useUpdateSource,
  useVideos,
} from "../api/queries";
import type { ConnectionType, ModelProfile, Video } from "../api/types";
import { Button } from "../components/common/Button";
import { Field } from "../components/common/Field";
import { Panel } from "../components/common/Panel";
import { useToasts } from "../components/common/Toasts";
import { useUnsavedGuard } from "../components/common/UnsavedGuard";
import { formatFileSize, formatValue } from "../lib/format";
import { options } from "../lib/dictionary";

interface FormState {
  name: string;
  scope: "canteen" | "gate";
  location: string;
  tags: string;
  connection_type: ConnectionType;
  video_id: number | null;
  stream_url: string;
  model_profile: "" | ModelProfile;
}

const EMPTY: FormState = {
  name: "",
  scope: "canteen",
  location: "",
  tags: "",
  connection_type: "video_loop",
  video_id: null,
  stream_url: "",
  model_profile: "",
};

const STREAM_URL = /^(https?|rtsps?|rtmp):\/\//i;

export function SourceFormPage() {
  const params = useParams();
  const navigate = useNavigate();
  const toasts = useToasts();
  const sourceId = params.id ? Number(params.id) : null;

  const sourceQuery = useSource(sourceId);
  const videosQuery = useVideos();
  const health = useHealth();
  const create = useCreateSource();
  const update = useUpdateSource(sourceId ?? 0);

  const [form, setForm] = useState<FormState>(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [progress, setProgress] = useState<number | null>(null);
  const cancelUpload = useRef<(() => void) | null>(null);

  useUnsavedGuard(dirty);

  useEffect(() => {
    const source = sourceQuery.data;
    if (!source) return;
    setForm({
      name: source.name,
      scope: source.scope,
      location: source.location,
      tags: (source.tags ?? []).join(", "),
      connection_type: source.connectionType,
      video_id: source.video?.id ?? null,
      stream_url: source.streamUrl ?? "",
      model_profile: source.modelProfileOverride ? source.modelProfile : "",
    });
  }, [sourceQuery.data?.id]);

  const patch = (changes: Partial<FormState>) => {
    setForm((previous) => ({ ...previous, ...changes }));
    setDirty(true);
  };

  const limits = health.data?.upload;
  const videos = videosQuery.data ?? [];
  const selectedVideo = videos.find((video) => video.id === form.video_id) ?? null;
  const markupExists = (sourceQuery.data?.markup?.lines?.length ?? 0) > 0 ||
    (sourceQuery.data?.markup?.zones?.length ?? 0) > 0;
  const isStream = form.connection_type === "stream";
  const streamUrl = form.stream_url.trim();
  const streamUrlProblem =
    isStream && streamUrl && !STREAM_URL.test(streamUrl)
      ? "Нужна ссылка на поток: http(s)://, rtsp:// или rtmp://"
      : undefined;

  const onUpload = (file: File) => {
    setProgress(0);
    const task = upload<{ video: Video }>("/api/videos", file, setProgress);
    cancelUpload.current = task.cancel;

    task.promise
      .then((data) => {
        videosQuery.refetch();
        patch({ video_id: data.video.id });
        toasts.success(
          `Видео «${data.video.name}» загружено`,
          `${data.video.resolution}, ${data.video.fps} кадр/с, ${Math.round(data.video.durationSeconds)} с`,
        );
      })
      .catch((error: ApiError) => {
        if (error.code !== "cancelled") {
          toasts.error("Загрузка не удалась", error.message);
        }
      })
      .finally(() => {
        setProgress(null);
        cancelUpload.current = null;
      });
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setFieldErrors({});
    if (streamUrlProblem) {
      setFieldErrors({ stream_url: streamUrlProblem });
      return;
    }
    const payload = {
      name: form.name.trim(),
      scope: form.scope,
      location: form.location.trim(),
      tags: form.tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      connection_type: form.connection_type,
      video_id: isStream ? null : form.video_id,
      stream_url: isStream ? streamUrl || null : null,
      model_profile: form.model_profile || null,
    };

    const onError = (error: unknown) => {
      if (error instanceof ApiError) {
        setFieldErrors(error.fields);
        toasts.error("Не удалось сохранить", error.message);
      } else {
        toasts.error("Не удалось сохранить", (error as Error).message);
      }
    };

    if (sourceId === null) {
      create.mutate(payload, {
        onSuccess: (data) => {
          setDirty(false);
          toasts.success(`Источник «${data.source.name}» создан`);
          // Без разметки считается только число людей в кадре — ведём дальше.
          navigate(
            data.source.video || data.source.streamUrl
              ? `/sources/${data.source.id}/markup`
              : `/sources/${data.source.id}/edit`,
          );
        },
        onError,
      });
      return;
    }

    update.mutate(payload, {
      onSuccess: (data) => {
        setDirty(false);
        toasts.success("Параметры сохранены", data.warning ?? undefined);
        navigate("/sources");
      },
      onError,
    });
  };

  return (
    <div className="page page--narrow">
      <header className="page__header">
        <div>
          <h1 className="page__title">
            {sourceId === null ? "Новый источник" : `Параметры: ${sourceQuery.data?.name ?? ""}`}
          </h1>
          <p className="page__subtitle">
            Источник — видеофайл, который играет по кругу, или прямой поток с камеры по ссылке.
          </p>
        </div>
        <Link className="btn btn--ghost btn--md" to="/sources">
          К источникам
        </Link>
      </header>

      <form onSubmit={submit}>
        <Panel title="Основное">
          <div className="form-grid">
            <Field label="Название" required error={fieldErrors.name} htmlFor="name">
              <input
                id="name"
                className="input"
                value={form.name}
                onChange={(event) => patch({ name: event.target.value })}
                required
                maxLength={160}
              />
            </Field>

            <Field label="Контур" required error={fieldErrors.scope} htmlFor="scope">
              <select
                id="scope"
                className="input"
                value={form.scope}
                onChange={(event) => patch({ scope: event.target.value as FormState["scope"] })}
              >
                <option value="canteen">Столовая</option>
                <option value="gate">КПП</option>
              </select>
            </Field>

            <Field label="Расположение" htmlFor="location" hint="Где именно стоит источник">
              <input
                id="location"
                className="input"
                value={form.location}
                onChange={(event) => patch({ location: event.target.value })}
                maxLength={200}
              />
            </Field>

            <Field label="Теги" htmlFor="tags" hint="Через запятую: по ним работает поиск">
              <input
                id="tags"
                className="input"
                value={form.tags}
                onChange={(event) => patch({ tags: event.target.value })}
              />
            </Field>

            <Field
              label="Профиль модели"
              htmlFor="profile"
              hint="По умолчанию берётся из Настроек. Здесь его можно переопределить только для этого источника"
            >
              <select
                id="profile"
                className="input"
                value={form.model_profile}
                onChange={(event) =>
                  patch({ model_profile: event.target.value as FormState["model_profile"] })
                }
              >
                <option value="">Как в настройках системы</option>
                {options("modelProfile").map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </Panel>

        <Panel title="Подключение">
          <div className="chips" role="radiogroup" aria-label="Тип подключения">
            {options("connectionType").map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={form.connection_type === option.value}
                className={`chip${form.connection_type === option.value ? " chip--active" : ""}`}
                onClick={() => patch({ connection_type: option.value as ConnectionType })}
              >
                {option.label}
              </button>
            ))}
          </div>
          {isStream ? (
            <p className="muted">
              Камера по ссылке: HLS (.m3u8), RTSP или HTTP. Анализ идёт в реальном времени — заранее
              посчитать эфир нельзя, поэтому нужен компьютер с ускорителем. Для широкого плана, где
              люди на кадре мелкие, выберите профиль модели «Дальний план».
            </p>
          ) : (
            <p className="muted">Файл играет по кругу и анализируется так же, как живой поток.</p>
          )}
        </Panel>

        {isStream ? (
          <Panel title="Прямой поток">
            <Field
              label="Ссылка на поток"
              required
              htmlFor="stream_url"
              error={fieldErrors.stream_url ?? streamUrlProblem}
              hint="Например, https://…/master.m3u8 или rtsp://логин:пароль@адрес:554/stream"
            >
              <input
                id="stream_url"
                className="input"
                value={form.stream_url}
                onChange={(event) => patch({ stream_url: event.target.value })}
                placeholder="https://"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                maxLength={1000}
              />
            </Field>
            {sourceId !== null && markupExists && streamUrl !== (sourceQuery.data?.streamUrl ?? "") && (
              <p className="notice notice--warn">
                Разметка привязана к кадру. После смены камеры её нужно проверить: линия и зоны
                могут оказаться не на своих местах.
              </p>
            )}
          </Panel>
        ) : (
          <Panel
            title="Видеофайл"
            meta={
              limits
                ? `Допустимо: ${limits.formats.join(", ")} · не больше ${limits.maxSizeMb} МБ`
                : undefined
            }
          >
            <div className="upload">
              <label className="upload__drop">
                <input
                  type="file"
                  accept={limits?.formats.join(",")}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) onUpload(file);
                    event.target.value = "";
                  }}
                  disabled={progress !== null}
                />
                <span>
                  {progress === null
                    ? "Выбрать файл для загрузки"
                    : `Загрузка… ${progress} %`}
                </span>
              </label>

              {progress !== null && (
                <div className="upload__progress">
                  <progress value={progress} max={100} />
                  <Button size="sm" onClick={() => cancelUpload.current?.()}>
                    Отменить
                  </Button>
                </div>
              )}

              <Field label="Или выбрать уже загруженный" htmlFor="video">
                <select
                  id="video"
                  className="input"
                  value={form.video_id ?? ""}
                  onChange={(event) =>
                    patch({ video_id: event.target.value ? Number(event.target.value) : null })
                  }
                >
                  <option value="">Не назначен</option>
                  {videos.map((video) => (
                    <option key={video.id} value={video.id}>
                      {video.name} · {video.resolution} · {Math.round(video.durationSeconds)} с
                    </option>
                  ))}
                </select>
              </Field>

              {selectedVideo && (
                <dl className="readout">
                  <div className="readout__row">
                    <dt>Длительность</dt>
                    <dd className="tabular">{formatValue(selectedVideo.durationSeconds, "с", true)}</dd>
                  </div>
                  <div className="readout__row">
                    <dt>Разрешение и частота</dt>
                    <dd className="tabular">
                      {selectedVideo.resolution} · {selectedVideo.fps} кадр/с
                    </dd>
                  </div>
                  <div className="readout__row">
                    <dt>Размер файла</dt>
                    <dd className="tabular">{formatFileSize(selectedVideo.sizeBytes)}</dd>
                  </div>
                </dl>
              )}

              {sourceId !== null && markupExists && form.video_id !== sourceQuery.data?.video?.id && (
                <p className="notice notice--warn">
                  Разметка привязана к кадру. После замены файла её нужно проверить: линия и зоны
                  могут оказаться не на своих местах.
                </p>
              )}
            </div>
          </Panel>
        )}

        <div className="form-actions">
          <Button type="submit" variant="primary" loading={create.isPending || update.isPending}>
            {sourceId === null ? "Создать источник" : "Сохранить"}
          </Button>
          <Button type="button" onClick={() => navigate("/sources")}>
            Отмена
          </Button>
          {dirty && <span className="muted">Есть несохранённые изменения</span>}
        </div>
      </form>
    </div>
  );
}

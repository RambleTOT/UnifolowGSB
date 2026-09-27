import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  useDemoStatus,
  useHealth,
  useLogout,
  useResetSettings,
  useSaveSettings,
  useSettings,
  useUpdateProfile,
} from "../api/queries";
import type { SystemSettings } from "../api/types";
import { Button } from "../components/common/Button";
import { ConfirmDialog } from "../components/common/ConfirmDialog";
import { DataBlock, blockState } from "../components/common/DataBlock";
import { Field } from "../components/common/Field";
import { Panel } from "../components/common/Panel";
import { useToasts } from "../components/common/Toasts";
import { useUnsavedGuard } from "../components/common/UnsavedGuard";
import { label, options } from "../lib/dictionary";
import { useSession } from "../state/session";

/** Поля системных настроек: подпись, пояснение и на что влияет. */
const FIELDS: Array<{
  key: keyof SystemSettings;
  label: string;
  hint: string;
  kind: "number" | "select" | "toggle";
  choices?: Array<{ value: string; label: string }>;
  step?: number;
  /** Меняет поведение анализа: источники перезапустятся. */
  restarts?: boolean;
}> = [
  {
    key: "model_profile",
    label: "Профиль модели",
    hint: "Точнее — медленнее. После смены источники ненадолго уйдут в «модель прогревается»",
    kind: "select",
    choices: options("modelProfile"),
    restarts: true,
  },
  {
    key: "tracker",
    label: "Алгоритм сопровождения",
    hint: "ByteTrack устойчивее при перекрытиях, BoT-SORT точнее на редком движении",
    kind: "select",
    choices: [
      { value: "bytetrack.yaml", label: "ByteTrack" },
      { value: "botsort.yaml", label: "BoT-SORT" },
    ],
    restarts: true,
  },
  {
    key: "confidence",
    label: "Порог уверенности распознавания",
    hint: "Ниже порог — больше людей находится, но и больше ложных срабатываний",
    kind: "number",
    step: 0.05,
    restarts: true,
  },
  {
    key: "queue_threshold",
    label: "Порог очереди, человек",
    hint: "Определяет, когда появится событие «Рост очереди»",
    kind: "number",
    step: 1,
  },
  {
    key: "wait_threshold_minutes",
    label: "Порог ожидания, минут",
    hint: "Определяет, когда появится событие «Длительное ожидание»",
    kind: "number",
    step: 1,
  },
  {
    key: "checkpoint_threshold_per_minute",
    label: "Порог перегрузки КПП, человек в минуту",
    hint: "Определяет, когда появится событие «Перегрузка КПП»",
    kind: "number",
    step: 1,
  },
  {
    key: "event_min_duration_seconds",
    label: "Минимальная длительность превышения, секунд",
    hint: "Защита от единичных всплесков: короче этого события не создаются",
    kind: "number",
    step: 5,
  },
  {
    key: "retention_days",
    label: "Срок хранения данных, дней",
    hint: "Более старые интервалы и кадры событий удаляются фоновой задачей",
    kind: "number",
    step: 1,
  },
  {
    key: "aggregation_seconds",
    label: "Интервал агрегации, секунд",
    hint: "Как часто кадры складываются в интервал. Влияет на новые данные",
    kind: "number",
    step: 5,
    restarts: true,
  },
  {
    key: "save_event_snapshots",
    label: "Сохранять кадры при событиях",
    hint: "Кадр с наложением попадает в детали события и удаляется по сроку хранения",
    kind: "toggle",
  },
];

export function SettingsPage() {
  const settingsQuery = useSettings();
  const save = useSaveSettings();
  const reset = useResetSettings();
  const updateProfile = useUpdateProfile();
  const logout = useLogout();
  const health = useHealth();
  const toasts = useToasts();
  const navigate = useNavigate();
  const { user, liveUpdates, setLiveUpdates } = useSession();

  const [values, setValues] = useState<SystemSettings | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [confirmReset, setConfirmReset] = useState(false);
  const [displayName, setDisplayName] = useState(user?.displayName ?? "");

  const demoStatus = useDemoStatus(user?.dataset === "demo");
  const saved = settingsQuery.data?.values ?? null;
  const bounds = settingsQuery.data?.bounds ?? {};

  useEffect(() => {
    if (saved && values === null) setValues({ ...saved });
  }, [saved, values]);

  const changed = useMemo(() => {
    if (!saved || !values) return [];
    return (Object.keys(values) as Array<keyof SystemSettings>).filter(
      (key) => values[key] !== saved[key],
    );
  }, [saved, values]);

  useUnsavedGuard(changed.length > 0);

  const restartWarning = changed.some(
    (key) => FIELDS.find((field) => field.key === key)?.restarts,
  );

  const submit = () => {
    if (!values) return;
    setFieldErrors({});
    const payload = Object.fromEntries(changed.map((key) => [key, values[key]]));
    save.mutate(payload, {
      onSuccess: (data) => {
        setValues({ ...data.values });
        toasts.success("Настройки сохранены", data.message);
      },
      onError: (error) => {
        if (error instanceof ApiError) {
          setFieldErrors(error.fields);
          toasts.error("Настройки не сохранены", error.message);
        } else {
          toasts.error("Настройки не сохранены", (error as Error).message);
        }
      },
    });
  };

  return (
    <div className="page page--narrow">
      <header className="page__header">
        <div>
          <h1 className="page__title">Настройки</h1>
          <p className="page__subtitle">
            Системные параметры общие для всех и влияют только на новые данные. Личные действуют
            только для вашей учётной записи.
          </p>
        </div>
      </header>

      <DataBlock
        state={blockState({
          isLoading: settingsQuery.isLoading,
          isFetching: settingsQuery.isFetching,
          isError: settingsQuery.isError,
        })}
        error={settingsQuery.error}
        onRetry={() => settingsQuery.refetch()}
      >
        {values && (
          <div className="page__stack">
            <Panel
              title="Системные настройки"
              meta="Общие для всех пользователей · применяются к новым данным"
              actions={
                <div className="row-actions">
                  {changed.length > 0 && (
                    <Button onClick={() => setValues(saved ? { ...saved } : values)}>
                      Отменить изменения
                    </Button>
                  )}
                  <Button
                    variant="primary"
                    onClick={submit}
                    loading={save.isPending}
                    disabled={changed.length === 0}
                    disabledReason="Изменений нет"
                  >
                    Сохранить
                  </Button>
                </div>
              }
            >
              {restartWarning && (
                <p className="notice notice--warn">
                  Вы меняете параметры анализа. После сохранения источники перезапустятся и на время
                  перейдут в состояние «модель прогревается».
                </p>
              )}

              <div className="form-grid">
                {FIELDS.map((field) => {
                  const range = bounds[field.key as string];
                  const dirty = changed.includes(field.key);
                  const value = values[field.key];

                  return (
                    <div key={field.key} className={dirty ? "settings-field settings-field--dirty" : "settings-field"}>
                      <Field
                        label={field.label}
                        htmlFor={field.key}
                        hint={
                          range
                            ? `${field.hint}. Допустимо от ${range[0]} до ${range[1]}`
                            : field.hint
                        }
                        error={fieldErrors[field.key as string]}
                      >
                        {field.kind === "select" ? (
                          <select
                            id={field.key}
                            className="input"
                            value={String(value)}
                            onChange={(event) =>
                              setValues({ ...values, [field.key]: event.target.value })
                            }
                          >
                            {field.choices?.map((choice) => (
                              <option key={choice.value} value={choice.value}>
                                {choice.label}
                              </option>
                            ))}
                          </select>
                        ) : field.kind === "toggle" ? (
                          <label className="toggle">
                            <input
                              id={field.key}
                              type="checkbox"
                              checked={Boolean(value)}
                              onChange={(event) =>
                                setValues({ ...values, [field.key]: event.target.checked })
                              }
                            />
                            <span>{value ? "Включено" : "Выключено"}</span>
                          </label>
                        ) : (
                          <input
                            id={field.key}
                            className="input"
                            type="number"
                            step={field.step}
                            min={range?.[0]}
                            max={range?.[1]}
                            value={Number(value)}
                            onChange={(event) =>
                              setValues({ ...values, [field.key]: Number(event.target.value) })
                            }
                          />
                        )}
                      </Field>
                      {dirty && <span className="settings-field__mark">изменено</span>}
                    </div>
                  );
                })}
              </div>

              <div className="form-actions">
                <Button variant="ghost" onClick={() => setConfirmReset(true)}>
                  Вернуть значения по умолчанию
                </Button>
                {changed.length > 0 && (
                  <span className="muted">Есть несохранённые изменения: {changed.length}</span>
                )}
              </div>
            </Panel>

            <Panel title="Личные настройки" meta="Действуют только для вашей учётной записи">
              <div className="form-grid">
                <Field
                  label="Профиль"
                  htmlFor="profile"
                  hint="Определяет, какой раздел и контур открываются после входа"
                >
                  <select
                    id="profile"
                    className="input"
                    value={user?.profile ?? "ops"}
                    onChange={(event) =>
                      updateProfile.mutate(
                        { profile: event.target.value as never },
                        { onSuccess: () => toasts.success("Профиль изменён") },
                      )
                    }
                  >
                    {options("profile").map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </Field>

                <Field
                  label="Режим данных"
                  htmlFor="dataset"
                  hint="Демо-данные нужны, чтобы посмотреть аналитику, пока своей истории мало. Наборы не смешиваются"
                >
                  <select
                    id="dataset"
                    className="input"
                    value={user?.dataset ?? "real"}
                    onChange={(event) =>
                      updateProfile.mutate(
                        { dataset: event.target.value as never },
                        {
                          onSuccess: (data) =>
                            toasts.success(
                              `Режим данных: ${label("dataset", data.user.dataset)}`,
                              data.user.dataset === "demo" && data.demoReady === false
                                ? "Собираем демо-историю за 30 суток, это занимает несколько секунд."
                                : undefined,
                            ),
                        },
                      )
                    }
                  >
                    {options("dataset").map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </Field>

                <Field label="Отображаемое имя" htmlFor="display-name" hint="Оно пишется в историю обработки событий">
                  <input
                    id="display-name"
                    className="input"
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    onBlur={() => {
                      if (displayName && displayName !== user?.displayName) {
                        updateProfile.mutate(
                          { displayName },
                          { onSuccess: () => toasts.success("Имя сохранено") },
                        );
                      }
                    }}
                  />
                </Field>

                <Field
                  label="Обновление в реальном времени"
                  htmlFor="live"
                  hint="Когда выключено, живые кадры и счётчики не обновляются, а в верхней панели видно почему"
                >
                  <label className="toggle">
                    <input
                      id="live"
                      type="checkbox"
                      checked={liveUpdates}
                      onChange={(event) => setLiveUpdates(event.target.checked)}
                    />
                    <span>{liveUpdates ? "Включено" : "Выключено"}</span>
                  </label>
                </Field>
              </div>

              {user?.dataset === "demo" && demoStatus.data?.running && (
                <p className="notice">Демо-история собирается, через несколько секунд она появится.</p>
              )}
            </Panel>

            <Panel title="Учётная запись">
              <dl className="readout">
                <div className="readout__row">
                  <dt>Логин</dt>
                  <dd>{user?.login}</dd>
                </div>
                <div className="readout__row">
                  <dt>Профиль</dt>
                  <dd>{user?.profileTitle}</dd>
                </div>
                <div className="readout__row">
                  <dt>Часовой пояс объекта</dt>
                  <dd>{health.data?.timezone ?? "—"}</dd>
                </div>
                <div className="readout__row">
                  <dt>Устройство анализа</dt>
                  <dd>{health.data?.deviceTitle ?? "—"}</dd>
                </div>
              </dl>
              <p className="muted">
                Пароль меняется командой <code>python -m app.cli set-password --login {user?.login}</code>:
                интерфейса управления учётными записями в этой версии нет.
              </p>
              <div className="form-actions">
                <Button onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}>
                  Выйти
                </Button>
              </div>
            </Panel>
          </div>
        )}
      </DataBlock>

      <ConfirmDialog
        open={confirmReset}
        title="Вернуть значения по умолчанию?"
        description="Все системные параметры — профиль модели, пороги событий и хранение — вернутся к исходным. Накопленные данные не затрагиваются."
        confirmLabel="Вернуть"
        busy={reset.isPending}
        onCancel={() => setConfirmReset(false)}
        onConfirm={() =>
          reset.mutate(undefined, {
            onSuccess: (data) => {
              setValues({ ...data.values });
              setConfirmReset(false);
              toasts.success("Значения возвращены к исходным");
            },
          })
        }
      />
    </div>
  );
}

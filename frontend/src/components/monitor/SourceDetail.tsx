import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useSourceLive } from "../../api/live";
import { useSourceAction, useSourceSummary } from "../../api/queries";
import type { Source } from "../../api/types";
import { label } from "../../lib/dictionary";
import { formatClock, formatDurationSeconds, formatFreshness, formatShare, formatValue } from "../../lib/format";
import { MetricsRow } from "../analytics/MetricsRow";
import { TimeChart } from "../charts/TimeChart";
import type { SeriesConfig } from "../charts/TimeChart";
import { Button } from "../common/Button";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import { StatusPill } from "../common/StatusPill";
import { useToasts } from "../common/Toasts";
import { useFilters } from "../../state/filters";
import { useSession } from "../../state/session";
import { useCalmLive } from "./calm";
import { diagnose } from "./diagnosis";
import { FrameOverlay } from "./FrameOverlay";
import type { OverlayToggles } from "./FrameOverlay";

type ViewMode = "live" | "analysis";

const PERIOD_SERIES: SeriesConfig[] = [
  { key: "entered", name: "Входы", color: "#1b5fcb", unit: "чел" },
  { key: "exited", name: "Выходы", color: "#1b6b4e", unit: "чел" },
  { key: "peopleInZone", name: "Людей в зоне", color: "#8992a2", type: "area", unit: "чел" },
];

interface Flash {
  id: number;
  x: number;
  y: number;
  direction: "in" | "out";
  line: string;
  at: number;
}

export function SourceDetail({ source, enabled }: { source: Source; enabled: boolean }) {
  const live = useSourceLive(source.id, enabled);
  const action = useSourceAction();
  const toasts = useToasts();
  const { filters } = useFilters();
  const { user } = useSession();
  // Блоки «за период» зависят от глобального периода, живая часть — нет.
  const summary = useSourceSummary(
    source.id,
    { period: filters.period, scope: "all", from: filters.from, to: filters.to },
    user?.dataset ?? "real",
  );

  const [mode, setMode] = useState<ViewMode>("live");
  const [toggles, setToggles] = useState<OverlayToggles>({
    boxes: true,
    trackIds: false,
    geometry: true,
  });
  const [flashes, setFlashes] = useState<Flash[]>([]);
  const flashId = useRef(0);
  const [loopNote, setLoopNote] = useState<number | null>(null);
  const previousLoop = useRef<number | null>(null);

  // Кадр принимается, только если он от этого источника: страховка на случай,
  // если в подключение попадёт чужое сообщение.
  const frame = live.data && live.data.sourceId === source.id ? live.data : null;
  // Числа «сейчас» — раз в секунду и медианой: иначе они дрожат с каждым кадром.
  const calm = useCalmLive(frame ?? null);
  const analysisReady = (frame?.frameIndex ?? -1) >= 0 && frame?.modelStatus === "ready";

  // Каждый засчитанный проход виден на изображении — так пользователь
  // убеждается, что система считает правильно (ТЗ, раздел 5.2).
  useEffect(() => {
    if (!frame?.crossings?.length) return;
    const now = Date.now();
    const created = frame.crossings.map((crossing) => ({
      id: (flashId.current += 1),
      x: crossing.point[0],
      y: crossing.point[1],
      direction: crossing.direction,
      line: crossing.lineName,
      at: now,
    }));
    setFlashes((previous) => [...previous.filter((item) => now - item.at < 1500), ...created]);
  }, [frame?.frameIndex]);

  // Граница круга: сцена меняется скачком, номера треков начинаются заново.
  // Пользователю про это говорим прямо, чтобы он не принял это за сбой.
  useEffect(() => {
    const current = frame?.loop.number;
    if (current === undefined) return;
    if (previousLoop.current !== null && current !== previousLoop.current) {
      setLoopNote(current);
      const timer = window.setTimeout(() => setLoopNote(null), 7000);
      previousLoop.current = current;
      return () => window.clearTimeout(timer);
    }
    previousLoop.current = current;
  }, [frame?.loop.number]);

  const diagnosis = useMemo(
    () => diagnose(source, frame ?? null, live.link, live.attempt, live.nextRetrySeconds),
    [source, frame, live.link, live.attempt, live.nextRetrySeconds],
  );

  const isStream = source.connectionType === "stream";

  const imageSrc =
    mode === "analysis"
      ? `/api/sources/${source.id}/analysis.jpg?frame=${frame?.frameIndex ?? 0}`
      : `/api/sources/${source.id}/stream.mjpg`;

  const restart = () =>
    action.mutate(
      { id: source.id, action: "restart-playback" },
      {
        onSuccess: () => toasts.success("Файл запущен с начала", "Круг закрыт, счётчик круга обнулён."),
        onError: (error) => toasts.error("Не удалось запустить файл с начала", (error as Error).message),
      },
    );

  return (
    <div className="detail">
      <Panel
        title={source.name}
        meta={
          <>
            <span>{label("scope", source.scope)}</span>
            <span>{source.location}</span>
            <span>{isStream ? "Прямой эфир" : "Видеофайл (по кругу)"}</span>
          </>
        }
        actions={
          <>
            <Link className="btn btn--secondary btn--md" to={`/sources/${source.id}/edit`}>
              Параметры источника
            </Link>
            <Link className="btn btn--primary btn--md" to={`/sources/${source.id}/markup`}>
              Зоны и линии
            </Link>
          </>
        }
        padded={false}
      >
        <div className={`diagnosis diagnosis--${diagnosis.tone}`}>
          <div>
            <strong>{diagnosis.title}</strong>
            {diagnosis.advice && <p>{diagnosis.advice}</p>}
          </div>
          <div className="diagnosis__side">
            {diagnosis.action && (
              <Link className="btn btn--secondary btn--sm" to={diagnosis.action.to}>
                {diagnosis.action.label}
              </Link>
            )}
            <div className="diagnosis__statuses">
              <StatusPill status={frame?.status ?? source.status} />
              <StatusPill status={live.link === "live" ? "live" : live.link === "reconnecting" ? "offline" : "connecting"} dictionary="connectionStatus" tone={live.link === "live" ? "ok" : "warn"} />
              <StatusPill
                status={frame?.modelStatus ?? "unavailable"}
                dictionary="modelStatus"
                tone={frame?.modelStatus === "ready" ? "ok" : frame?.modelStatus === "warming_up" ? "warn" : "danger"}
              />
              <span className="muted">
                сигнал {formatFreshness(frame?.updatedAt ?? source.lastSignalAt)}
              </span>
            </div>
          </div>
        </div>

        <div className="stage">
          {loopNote !== null && (
            <p className="notice" role="status">
              Файл начался заново: идёт круг {loopNote}. Номера треков начались с начала, а значения
              «сейчас» могли измениться скачком — это не сбой.
            </p>
          )}
          <div className="stage__frame">
            {frame || mode === "live" ? (
              <img className="stage__image" src={imageSrc} alt={`Кадр источника «${source.name}»`} />
            ) : (
              <div className="stage__placeholder">Ожидаем первый кадр…</div>
            )}
            <FrameOverlay
              frame={frame ?? null}
              toggles={toggles}
              flashes={flashes}
              zoneCounts={calm.zones}
              smooth={mode === "live"}
            />
          </div>

          <div className="stage__controls">
            <div className="chips" role="group" aria-label="Наложение">
              <span className="chips__label">Наложение:</span>
              {(
                [
                  ["boxes", "Рамки людей"],
                  ["trackIds", "Номера треков"],
                  ["geometry", "Зоны и линии"],
                ] as const
              ).map(([key, title]) => (
                <button
                  key={key}
                  type="button"
                  className={`chip ${toggles[key] ? "chip--active" : ""}`}
                  aria-pressed={toggles[key]}
                  onClick={() => setToggles({ ...toggles, [key]: !toggles[key] })}
                >
                  {title}
                </button>
              ))}
            </div>

            <div className="chips" role="group" aria-label="Режим просмотра">
              <span className="chips__label">Режим:</span>
              <button
                type="button"
                className={`chip ${mode === "live" ? "chip--active" : ""}`}
                onClick={() => setMode("live")}
              >
                Видео в реальном времени
              </button>
              <button
                type="button"
                className={`chip ${mode === "analysis" ? "chip--active" : ""}`}
                onClick={() => analysisReady && setMode("analysis")}
                disabled={!analysisReady}
                title={
                  analysisReady
                    ? "Показывать именно те кадры, которые обработала модель"
                    : "Пока не пришёл ни один обработанный кадр: модель ещё не отдала результат"
                }
              >
                Точный анализ
              </button>
            </div>

            <p className="stage__hint">
              {mode === "live"
                ? "Видео идёт плавно, наложение может на доли секунды расходиться с картинкой."
                : "Показаны кадры, которые обработала модель: частота ниже, зато рамки точно совпадают с подсчётом."}
            </p>
          </div>

          {isStream ? (
            <div className="playback">
              <div className="playback__line">
                <span className="tabular">в эфире {formatClock(frame?.positionSeconds)}</span>
                <span className="muted">
                  картинка идёт с запасом ~25 с: камера отдаёт видео кусками, запас сглаживает рывки
                </span>
              </div>
              <div className="playback__loops tabular">
                <span>
                  За сегодня: ↑ {frame?.metrics.entriesToday ?? 0} / ↓ {frame?.metrics.exitsToday ?? 0}
                </span>
                {frame?.resolution && <span className="muted">{frame.resolution}</span>}
              </div>
            </div>
          ) : (
            <div className="playback">
              <div className="playback__line">
                <span className="tabular">
                  {formatClock(frame?.positionSeconds)} из {formatClock(frame?.durationSeconds ?? source.video?.durationSeconds)}
                </span>
                <span>круг {frame?.loop.number ?? "—"}</span>
                <Button size="sm" onClick={restart} loading={action.isPending}>
                  Запустить с начала
                </Button>
              </div>
              <progress
                className="playback__bar"
                value={frame?.positionSeconds ?? 0}
                max={frame?.durationSeconds || source.video?.durationSeconds || 1}
              />
              <div className="playback__loops tabular">
                <span>
                  Итог за круг: ↑ {frame?.loop.entered ?? 0} / ↓ {frame?.loop.exited ?? 0}
                </span>
                <span className="muted">
                  прошлый круг:{" "}
                  {frame?.loop.previousEntered === null || frame?.loop.previousEntered === undefined
                    ? "ещё не завершён"
                    : `↑ ${frame.loop.previousEntered} / ↓ ${frame.loop.previousExited}`}
                </span>
              </div>
            </div>
          )}
        </div>
      </Panel>

      <div className="detail__side">
        <Panel title="Сейчас" updatedAt={calm.updatedAt ?? undefined}>
          <dl className="readout">
            <Readout label="Людей в кадре" value={formatValue(calm.peopleInFrame, "чел", true)} />
            <Readout
              label="Людей в зоне"
              value={
                source.readiness.state === "no_markup"
                  ? "—"
                  : formatValue(calm.peopleInZone, "чел", true)
              }
              note={source.readiness.state === "no_markup" ? "не задана зона заполненности" : undefined}
            />
            <Readout
              label="Очередь"
              value={formatValue(calm.queue, "чел", true)}
              note={source.readiness.missing.includes("не задана зона очереди") ? "не задана зона очереди" : undefined}
            />
            <Readout label="Входы за сегодня" value={formatValue(frame?.metrics.entriesToday ?? null, "чел", true)} />
            <Readout label="Выходы за сегодня" value={formatValue(frame?.metrics.exitsToday ?? null, "чел", true)} />
            <Readout label="Внутри сейчас (оценка)" value={formatValue(frame?.metrics.insideNow ?? null, "чел", true)} />
            <Readout label="Среднее ожидание" value={formatDurationSeconds(calm.avgWaitSeconds)} />
          </dl>
        </Panel>

        <Panel title="Техническое состояние">
          <dl className="readout">
            <Readout label="Частота кадров" value={formatValue(calm.fps, "кадр/с")} />
            <Readout label="Задержка обработки" value={formatValue(calm.latencyMs, "мс", true)} />
            <Readout label="Средняя уверенность" value={formatShare(calm.confidence)} />
            <Readout label="Разрешение" value={frame?.resolution ?? source.video?.resolution ?? "—"} />
            <Readout label="Режим анализа" value={label("analysisMode", frame?.analysisMode ?? "auto")} />
            <Readout label="Профиль модели" value={label("modelProfile", source.modelProfile)} />
          </dl>
        </Panel>

        <Panel title="Зоны источника">
          {frame && frame.zones.length > 0 ? (
            <ul className="zone-list">
              {frame.zones.map((zone) => (
                <li key={zone.id}>
                  <span className={`zone-dot zone-dot--${zone.kind}`} aria-hidden="true" />
                  <strong>{zone.name}</strong>
                  <span className="muted">{label("zoneKind", zone.kind)}</span>
                  <span className="tabular">{calm.zones[zone.id] ?? zone.people} чел</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              Зоны не заданы. Пока считается только число людей в кадре.{" "}
              <Link to={`/sources/${source.id}/markup`}>Разметить</Link>
            </p>
          )}
        </Panel>

        <Panel
          title="Показатели за период"
          meta={
            summary.data
              ? `${label("period", summary.data.window.period)} · шаг ${summary.data.window.stepTitle}`
              : "зависят от периода в верхней панели"
          }
        >
          {summary.data ? (
            <>
              <MetricsRow metrics={summary.data.metrics} />
              {summary.data.flowSeries.some((point) => point.entered !== null) ? (
                <TimeChart
                  data={summary.data.flowSeries}
                  stepSeconds={summary.data.window.stepSeconds}
                  series={PERIOD_SERIES}
                  height={220}
                />
              ) : (
                <EmptyState
                  title="За период данных нет"
                  description="Источник не передавал данные в выбранном периоде."
                />
              )}
            </>
          ) : (
            <p className="muted">Загружаем показатели за период…</p>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Readout({ label: title, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="readout__row">
      <dt>{title}</dt>
      <dd className="tabular">
        {value}
        {note && <span className="readout__note">{note}</span>}
      </dd>
    </div>
  );
}

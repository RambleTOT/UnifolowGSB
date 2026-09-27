import type { LinkState } from "../../api/live";
import type { LiveMessage, Source } from "../../api/types";

export interface Diagnosis {
  tone: "ok" | "warn" | "danger" | "muted";
  title: string;
  /** Что делать дальше: у состояния не должно быть тупика. */
  advice?: string;
  action?: { label: string; to: string };
}

/**
 * Диагностика одной фразой (ТЗ, раздел 5.2).
 *
 * Три статуса — источника, соединения и модели — сводятся в одно объяснение:
 * в чём проблема и что с ней делать. Сами статусы при этом остаются на экране.
 */
export function diagnose(
  source: Source,
  frame: LiveMessage | null,
  link: LinkState,
  attempt: number,
  nextRetrySeconds: number,
): Diagnosis {
  if (!source.enabled) {
    return {
      tone: "muted",
      title: "Источник выключен",
      advice: "Анализ остановлен вами, а не сбоем. Включите источник, чтобы счётчики пошли.",
      action: { label: "Включить", to: `/sources/${source.id}/edit` },
    };
  }

  const isStream = source.connectionType === "stream";

  if (isStream && !source.streamUrl) {
    return {
      tone: "muted",
      title: "Не указана ссылка на поток",
      advice: "Без ссылки на камеру считать нечего.",
      action: { label: "Параметры источника", to: `/sources/${source.id}/edit` },
    };
  }

  if (!isStream && !source.video) {
    return {
      tone: "muted",
      title: "Видео не назначено",
      advice: "У источника нет файла: считать нечего.",
      action: { label: "Параметры источника", to: `/sources/${source.id}/edit` },
    };
  }

  if (!source.videoAvailable) {
    return {
      tone: "danger",
      title: "Файл не найден",
      advice: source.lastError ?? "Файл источника пропал с диска. Замените его или загрузите заново.",
      action: { label: "Параметры источника", to: `/sources/${source.id}/edit` },
    };
  }

  if (link === "reconnecting") {
    return {
      tone: "warn",
      title: "Связь с сервером потеряна",
      advice: `Значения на экране устарели. Переподключение через ${nextRetrySeconds} с (попытка ${attempt}).`,
    };
  }

  if (link === "connecting" || !frame) {
    return {
      tone: "muted",
      title: "Подключаемся к потоку",
      advice: "Соединение устанавливается, первые кадры вот-вот придут.",
    };
  }

  if (frame.status === "offline") {
    return {
      tone: "danger",
      title: "Нет сигнала",
      advice:
        frame.error ??
        (isStream
          ? "Камера не отвечает. Система переподключается сама; если долго нет кадров — проверьте ссылку."
          : "Файл не читается или воспроизведение остановилось."),
      action: { label: "Параметры источника", to: `/sources/${source.id}/edit` },
    };
  }

  if (frame.modelStatus === "error" || frame.modelStatus === "unavailable") {
    return {
      tone: "danger",
      title: "Анализ недоступен",
      advice: frame.error ?? "Видео идёт, но модель не работает — счётчики стоят.",
      action: { label: "Настройки", to: "/settings" },
    };
  }

  if (frame.modelStatus === "warming_up") {
    const percent = frame.warmupPercent === null ? "" : ` (${Math.round(frame.warmupPercent)} %)`;
    return {
      tone: "warn",
      title: `Модель прогревается${percent}`,
      advice: "Видео уже идёт, счётчики обновятся, как только анализ будет готов.",
    };
  }

  if (source.readiness.state === "no_markup") {
    return {
      tone: "warn",
      title: "Нет разметки",
      advice: "Люди в кадре видны, но входы, выходы и очередь не считаются: нет линии и зон.",
      action: { label: "Разметить", to: `/sources/${source.id}/markup` },
    };
  }

  if (frame.status === "degraded") {
    return {
      tone: "warn",
      title: "Анализ отстаёт от видео",
      advice: `Задержка ${Math.round(frame.technical.latencyMs)} мс, частота ${frame.technical.fps.toFixed(1)} кадр/с — счётчики могут запаздывать.`,
    };
  }

  if (source.readiness.state === "partial") {
    return {
      tone: "ok",
      title: isStream ? "В эфире: поток идёт, анализ работает" : "В эфире: файл воспроизводится, анализ идёт",
      advice: `Размечено не всё: ${source.readiness.missing.join(", ")}.`,
      action: { label: "Дополнить разметку", to: `/sources/${source.id}/markup` },
    };
  }

  return {
    tone: "ok",
    title: isStream ? "В эфире: поток идёт, анализ работает" : "В эфире: файл воспроизводится, анализ идёт",
    advice: "Кадры приходят, счётчики обновляются.",
  };
}

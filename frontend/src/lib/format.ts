/**
 * Форматирование чисел, длительностей, дат и прочерков.
 *
 * Правила — из ТЗ, раздел 3.7. Модуль один на всё приложение: иначе одно и то же
 * число в разных разделах выглядит по-разному.
 */

const NUMBER = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const NUMBER_WHOLE = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

/** Прочерк вместо значения: «нет данных», а не «ноль». */
export const DASH = "—";

export function isMissing(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined || Number.isNaN(value);
}

/** Число с разделителями разрядов и дробной частью до одного знака. */
export function formatNumber(value: number | null | undefined, whole = false): string {
  if (isMissing(value)) return DASH;
  return (whole ? NUMBER_WHOLE : NUMBER).format(value);
}

/** Значение с единицей измерения: у каждого числа она должна быть. */
export function formatValue(value: number | null | undefined, unit?: string, whole = false): string {
  if (isMissing(value)) return DASH;
  const number = formatNumber(value, whole);
  return unit ? `${number} ${unit}` : number;
}

/** Длительность: минуты, а свыше часа — «Ч ч ММ мин». */
export function formatDurationMinutes(minutes: number | null | undefined): string {
  if (isMissing(minutes)) return DASH;
  if (minutes < 60) return `${formatNumber(minutes)} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return `${hours} ч ${String(rest).padStart(2, "0")} мин`;
}

export function formatDurationSeconds(seconds: number | null | undefined): string {
  if (isMissing(seconds)) return DASH;
  if (seconds < 60) return `${Math.round(seconds)} с`;
  return formatDurationMinutes(seconds / 60);
}

/** Позиция в файле: «5:41 из 8 мин 10 с» показывается по частям. */
export function formatClock(seconds: number | null | undefined): string {
  if (isMissing(seconds)) return DASH;
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

/** Процент изменения со знаком. Ноль показывается как «без изменений». */
export function formatDelta(percent: number | null | undefined): string {
  if (isMissing(percent)) return "нет данных для сравнения";
  const rounded = Math.round(percent);
  if (rounded === 0) return "без изменений";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)} %`;
}

export function formatPercent(value: number | null | undefined): string {
  if (isMissing(value)) return DASH;
  return `${Math.round(value)} %`;
}

/** Доля 0..1 в процентах: уверенность распознавания приходит именно так. */
export function formatShare(value: number | null | undefined): string {
  if (isMissing(value)) return DASH;
  return `${Math.round(value * 100)} %`;
}

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  // Сервер отдаёт время в UTC без указания пояса — дополняем его явно.
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Дата и время для журналов: день, месяц, год и время. */
export function formatDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return DASH;
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Время с секундами: этого достаточно в оперативных блоках. */
export function formatTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return DASH;
  return date.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Свежесть данных: «обновлено 5 с назад». Точное время доступно отдельно. */
export function formatFreshness(value: string | null | undefined, now = Date.now()): string {
  const date = parseDate(value);
  if (!date) return DASH;
  const seconds = Math.max(0, Math.round((now - date.getTime()) / 1000));
  if (seconds < 5) return "только что";
  if (seconds < 60) return `${seconds} с назад`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;
  return formatDateTime(value);
}

export function formatFileSize(bytes: number | null | undefined): string {
  if (isMissing(bytes)) return DASH;
  const mb = bytes / (1024 * 1024);
  if (mb < 1) return `${formatNumber(bytes / 1024, true)} КБ`;
  return `${formatNumber(mb)} МБ`;
}

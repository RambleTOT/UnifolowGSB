/**
 * Словарь перечислений.
 *
 * Сырые значения вроде `online` или `high` не выводятся нигде (ТЗ, раздел 4.2
 * и ошибка прежнего прототипа № 11). Неизвестное значение показывается как
 * «Неизвестно» и пишется в консоль — так его заметят на отладке, а не в бою.
 */

type Dictionary = Record<string, string>;

const SOURCE_STATUS: Dictionary = {
  online: "В норме",
  degraded: "Нестабильно",
  offline: "Нет сигнала",
  disabled: "Выключен",
  no_video: "Видео не назначено",
};

const CONNECTION_STATUS: Dictionary = {
  connecting: "Подключение",
  live: "В эфире",
  degraded: "Деградация",
  offline: "Оффлайн",
  error: "Ошибка",
};

const MODEL_STATUS: Dictionary = {
  ready: "Готова",
  warming_up: "Прогревается",
  error: "Ошибка",
  unavailable: "Недоступна",
};

const READINESS: Dictionary = {
  no_video: "Видео не назначено",
  file_missing: "Файл не найден",
  no_markup: "Нет разметки",
  partial: "Размечен частично",
  ready: "Размечен",
};

const ANALYSIS_MODE: Dictionary = {
  realtime: "В реальном времени",
  precomputed: "По предрасчёту",
  auto: "Определяется автоматически",
};

const SCOPE: Dictionary = {
  all: "Все контуры",
  canteen: "Столовая",
  gate: "КПП",
};

const PERIOD: Dictionary = {
  hour: "Час",
  day: "День",
  week: "Неделя",
  month: "Месяц",
  custom: "Свой диапазон",
};

const SEVERITY: Dictionary = {
  low: "Низкий",
  medium: "Средний",
  high: "Высокий",
  critical: "Критический",
};

const EVENT_TYPE: Dictionary = {
  queue_spike: "Рост очереди",
  slow_movement: "Длительное ожидание",
  checkpoint_overload: "Перегрузка КПП",
  abnormal_traffic: "Нетипичный трафик",
  camera_drop: "Проблема с источником",
};

const EVENT_STATUS: Dictionary = {
  open: "Открыт",
  investigating: "В работе",
  resolved: "Решён",
};

const OBJECT_STATE: Dictionary = {
  moving: "В движении",
  queue: "Стоит в очереди",
  crossing: "Пересекает линию",
};

const ZONE_KIND: Dictionary = {
  queue: "Очередь",
  occupancy: "Заполненность",
};

const LINE_COUNTS: Dictionary = {
  in: "Только входы",
  out: "Только выходы",
  both: "Входы и выходы",
};

const PROFILE: Dictionary = {
  ops: "Операционный центр",
  security: "Пост охраны",
  manager: "Менеджер объекта",
  admin: "Технический администратор",
};

const MODEL_PROFILE: Dictionary = {
  fast: "Быстрый",
  standard: "Стандартный",
  accurate: "Точный",
  far: "Дальний план",
};

const CONNECTION_TYPE: Dictionary = {
  video_loop: "Видеофайл по кругу",
  stream: "Прямой поток",
};

const DATA_STATUS: Dictionary = {
  ok: "Данные поступают",
  partial: "Данные поступают частично",
  no_data: "Данные не поступают",
  no_sources: "Нет источников с видео",
  disconnected: "Нет связи с сервером",
  paused: "Автообновление выключено",
};

const DATASET: Dictionary = {
  real: "Реальные данные",
  demo: "Демо-данные",
};

const DICTIONARIES: Record<string, Dictionary> = {
  sourceStatus: SOURCE_STATUS,
  connectionStatus: CONNECTION_STATUS,
  modelStatus: MODEL_STATUS,
  readiness: READINESS,
  analysisMode: ANALYSIS_MODE,
  scope: SCOPE,
  period: PERIOD,
  severity: SEVERITY,
  eventType: EVENT_TYPE,
  eventStatus: EVENT_STATUS,
  objectState: OBJECT_STATE,
  zoneKind: ZONE_KIND,
  lineCounts: LINE_COUNTS,
  profile: PROFILE,
  modelProfile: MODEL_PROFILE,
  connectionType: CONNECTION_TYPE,
  dataStatus: DATA_STATUS,
  dataset: DATASET,
};

export type DictionaryName = keyof typeof DICTIONARIES;

const reported = new Set<string>();

/** Подпись значения перечисления на русском. */
export function label(dictionary: DictionaryName, value: string | null | undefined): string {
  if (!value) return "Неизвестно";
  const found = DICTIONARIES[dictionary]?.[value];
  if (found) return found;

  const key = `${dictionary}:${value}`;
  if (!reported.has(key)) {
    reported.add(key);
    console.warn(`Не переведено значение «${value}» из словаря «${dictionary}»`);
  }
  return "Неизвестно";
}

/** Варианты словаря — для выпадающих списков и переключателей. */
export function options(dictionary: DictionaryName): Array<{ value: string; label: string }> {
  return Object.entries(DICTIONARIES[dictionary] ?? {}).map(([value, title]) => ({
    value,
    label: title,
  }));
}

/** Тон, которым показывается статус источника: цветом и не только. */
export function statusTone(status: string | null | undefined): "ok" | "warn" | "danger" | "muted" {
  switch (status) {
    case "online":
      return "ok";
    case "degraded":
      return "warn";
    case "offline":
      return "danger";
    default:
      return "muted";
  }
}

export function severityTone(severity: string | null | undefined): "ok" | "warn" | "danger" | "muted" {
  switch (severity) {
    case "critical":
    case "high":
      return "danger";
    case "medium":
      return "warn";
    case "low":
      return "muted";
    default:
      return "muted";
  }
}

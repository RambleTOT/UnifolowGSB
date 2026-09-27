import { describe, expect, it } from "vitest";

import {
  DASH,
  formatDelta,
  formatDurationMinutes,
  formatDurationSeconds,
  formatFreshness,
  formatNumber,
  formatShare,
  formatValue,
} from "../format";

/** Разделитель разрядов в русской локали — узкий неразрывный пробел. */
const plain = (value: string) => value.replace(/[\u00a0\u202f]/g, " ");

describe("форматирование чисел", () => {
  it("округляет до одного знака и ставит разделители разрядов", () => {
    expect(plain(formatNumber(1284))).toBe("1 284");
    expect(formatNumber(7.44)).toBe("7,4");
  });

  it("отсутствующее значение показывает прочерком, а не нулём", () => {
    expect(formatNumber(null)).toBe(DASH);
    expect(formatValue(undefined, "чел")).toBe(DASH);
  });

  it("всегда добавляет единицу измерения", () => {
    expect(plain(formatValue(12, "чел", true))).toBe("12 чел");
  });
});

describe("длительности", () => {
  it("до часа показывает минуты", () => {
    expect(formatDurationMinutes(6.2)).toBe("6,2 мин");
  });

  it("свыше часа — часы и минуты", () => {
    expect(formatDurationMinutes(95)).toBe("1 ч 35 мин");
  });

  it("секунды переводит в минуты после порога в минуту", () => {
    expect(formatDurationSeconds(45)).toBe("45 с");
    expect(formatDurationSeconds(150)).toBe("2,5 мин");
  });
});

describe("изменение к предыдущему периоду", () => {
  it("без данных для сравнения не показывает ноль или сто процентов", () => {
    expect(formatDelta(null)).toBe("нет данных для сравнения");
  });

  it("нулевое изменение называет своими словами", () => {
    expect(formatDelta(0.4)).toBe("без изменений");
  });

  it("знак показывает направление", () => {
    expect(formatDelta(12)).toBe("+12 %");
    expect(formatDelta(-24)).toBe("−24 %");
  });
});

describe("свежесть и доли", () => {
  it("считает возраст значения относительно текущего момента", () => {
    const now = Date.parse("2026-09-21T12:00:30Z");
    expect(formatFreshness("2026-09-21T12:00:28", now)).toBe("только что");
    expect(formatFreshness("2026-09-21T12:00:00", now)).toBe("30 с назад");
    expect(formatFreshness("2026-09-21T11:50:00", now)).toBe("10 мин назад");
  });

  it("уверенность приходит долей, а показывается процентами", () => {
    expect(formatShare(0.884)).toBe("88 %");
    expect(formatShare(null)).toBe(DASH);
  });
});

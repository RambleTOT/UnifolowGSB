import { describe, expect, it, vi } from "vitest";

import { label, options, severityTone, statusTone } from "../dictionary";

describe("словарь перечислений", () => {
  it("переводит значения статусов и приоритетов", () => {
    expect(label("sourceStatus", "online")).toBe("В норме");
    expect(label("sourceStatus", "offline")).toBe("Нет сигнала");
    expect(label("severity", "critical")).toBe("Критический");
    expect(label("readiness", "no_markup")).toBe("Нет разметки");
    expect(label("analysisMode", "precomputed")).toBe("По предрасчёту");
  });

  it("одинаково называет один и тот же статус в разных местах", () => {
    // Ошибка прежнего прототипа: «В норме» и «Готово» для одного состояния.
    expect(label("sourceStatus", "online")).toBe(label("sourceStatus", "online"));
  });

  it("неизвестное значение не утекает наружу сырым", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(label("sourceStatus", "weird_state")).toBe("Неизвестно");
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("пустое значение тоже не ломает подпись", () => {
    expect(label("severity", null)).toBe("Неизвестно");
  });

  it("отдаёт варианты для списков", () => {
    expect(options("zoneKind")).toEqual([
      { value: "queue", label: "Очередь" },
      { value: "occupancy", label: "Заполненность" },
    ]);
  });

  it("тон статуса отражает серьёзность", () => {
    expect(statusTone("online")).toBe("ok");
    expect(statusTone("degraded")).toBe("warn");
    expect(statusTone("offline")).toBe("danger");
    expect(severityTone("high")).toBe("danger");
    expect(severityTone("medium")).toBe("warn");
  });
});

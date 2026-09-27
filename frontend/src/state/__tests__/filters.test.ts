import { describe, expect, it } from "vitest";

import { validateRange } from "../filters";

describe("произвольный диапазон дат", () => {
  it("требует обе даты", () => {
    expect(validateRange(null, "2026-09-21")).toBe("Укажите обе даты диапазона.");
  });

  it("не пускает «до» раньше «от»", () => {
    expect(validateRange("2026-09-21", "2026-09-01")).toBe(
      "Дата «до» не может быть раньше даты «от».",
    );
  });

  it("не пускает будущее", () => {
    const future = new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString().slice(0, 10);
    expect(validateRange("2026-09-01", future)).toBe("Дата «до» не может быть в будущем.");
  });

  it("корректный диапазон проходит", () => {
    expect(validateRange("2026-09-01", "2026-09-10")).toBeNull();
  });
});

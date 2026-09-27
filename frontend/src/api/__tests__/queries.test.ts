import { describe, expect, it } from "vitest";

import { eventsParams } from "../queries";

describe("параметры журнала событий", () => {
  it("кладёт в адрес только заданные фильтры", () => {
    const params = new URLSearchParams(
      eventsParams({ period: "day", scope: "all", severity: "all", status: "open", page: 2 }),
    );

    expect(params.get("period")).toBe("day");
    expect(params.get("status")).toBe("open");
    expect(params.get("page")).toBe("2");
    // «Любой приоритет» — это отсутствие фильтра, а не значение фильтра.
    expect(params.get("severity")).toBeNull();
  });

  it("передаёт диапазон только для произвольного периода", () => {
    const withoutRange = new URLSearchParams(
      eventsParams({ period: "week", scope: "gate", from: "2026-09-01", to: "2026-09-07" }),
    );
    expect(withoutRange.get("from")).toBeNull();

    const withRange = new URLSearchParams(
      eventsParams({ period: "custom", scope: "gate", from: "2026-09-01", to: "2026-09-07" }),
    );
    expect(withRange.get("from")).toBe("2026-09-01");
    expect(withRange.get("to")).toBe("2026-09-07");
  });
});

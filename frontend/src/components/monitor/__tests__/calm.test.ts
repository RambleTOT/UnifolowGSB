import { describe, expect, it } from "vitest";

import type { LiveMessage } from "../../../api/types";
import { median, summarize } from "../calm";

function frame(people: number, zone: number, fps: number): LiveMessage {
  return {
    frameIndex: 1,
    metrics: { peopleInFrame: people, peopleInZone: zone, queue: 0, entriesToday: 3, exitsToday: 1, insideNow: 2, avgWaitSeconds: null },
    technical: { fps, latencyMs: 100, confidence: 0.5 },
    zones: [{ id: "z", name: "Зал", kind: "occupancy", polygon: [], people: zone, capacity: null }],
    updatedAt: "2026-09-27T12:00:00",
  } as unknown as LiveMessage;
}

describe("спокойные цифры", () => {
  it("медиана не даёт одному кадру-выбросу сдвинуть показание", () => {
    expect(median([28, 29, 41, 28, 30])).toBe(29);
    expect(median([])).toBeNull();
  });

  it("люди в кадре и в зонах — медиана за окно, частота — среднее", () => {
    const calm = summarize([frame(28, 20, 3), frame(35, 26, 3.4), frame(29, 21, 2.9)]);
    expect(calm.peopleInFrame).toBe(29);
    expect(calm.zones.z).toBe(21);
    expect(calm.fps).toBeCloseTo(3.1, 1);
  });
});

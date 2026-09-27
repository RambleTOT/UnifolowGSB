/** Вспомогательная геометрия редактора разметки (координаты нормированы 0..1). */

import type { Markup, MarkupLine, MarkupZone } from "../../api/types";

export type Draft = Markup;

export function emptyMarkup(): Draft {
  return { anchor: "bottom_center", lines: [], zones: [] };
}

export function cloneMarkup(markup: Draft): Draft {
  return JSON.parse(JSON.stringify(markup)) as Draft;
}

export function nextId(prefix: string, existing: string[]): string {
  let index = existing.length + 1;
  let candidate = `${prefix}-${index}`;
  while (existing.includes(candidate)) {
    index += 1;
    candidate = `${prefix}-${index}`;
  }
  return candidate;
}

export function defaultZone(kind: "queue" | "occupancy", existing: string[]): MarkupZone {
  const shift = kind === "queue" ? 0 : 0.08;
  return {
    id: nextId(kind === "queue" ? "zone-queue" : "zone-occupancy", existing),
    name: kind === "queue" ? "Зона очереди" : "Зона заполненности",
    kind,
    min_dwell_seconds: 5,
    capacity: null,
    polygon: [
      [0.25 + shift, 0.45 + shift],
      [0.6 + shift, 0.45 + shift],
      [0.6 + shift, 0.8 + shift],
      [0.25 + shift, 0.8 + shift],
    ],
  };
}

export function defaultLine(existing: string[]): MarkupLine {
  return {
    id: nextId("line", existing),
    name: "Контрольная линия",
    a: [0.2, 0.55],
    b: [0.8, 0.55],
    entry_side: -1,
    counts: "both",
  };
}

export function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** Куда смотрит сторона «вход»: нормаль к линии, умноженная на знак стороны. */
export function entryArrow(line: MarkupLine): { x: number; y: number; dx: number; dy: number } {
  const midX = (line.a[0] + line.b[0]) / 2;
  const midY = (line.a[1] + line.b[1]) / 2;
  const vx = line.b[0] - line.a[0];
  const vy = line.b[1] - line.a[1];
  const length = Math.max(1e-6, Math.hypot(vx, vy));
  const sign = line.entry_side > 0 ? 1 : -1;
  return { x: midX, y: midY, dx: (-vy / length) * sign, dy: (vx / length) * sign };
}

export function polygonCentroid(points: Array<[number, number]>): [number, number] {
  const sum = points.reduce(
    (accumulator, [x, y]) => [accumulator[0] + x, accumulator[1] + y] as [number, number],
    [0, 0] as [number, number],
  );
  return [sum[0] / points.length, sum[1] / points.length];
}

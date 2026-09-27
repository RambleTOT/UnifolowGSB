import { useEffect, useRef, useState } from "react";

import type { LiveMessage } from "../../api/types";

/**
 * Спокойные цифры для живой части.
 *
 * Метаданные приходят с каждым обработанным кадром — до 25 раз в секунду, —
 * а человек читает показания раз в секунду. К тому же модель на соседних
 * кадрах находит на одного-двух человек больше или меньше, и «людей в кадре»
 * дрожало бы без остановки. Поэтому числа «сейчас» — это медиана за последние
 * две секунды, пересчитанная раз в секунду. Счётчики входов и выходов сюда не
 * входят: они меняются только при засчитанном проходе и должны отзываться сразу.
 */
export interface CalmLive {
  peopleInFrame: number | null;
  peopleInZone: number | null;
  queue: number | null;
  avgWaitSeconds: number | null;
  /** Люди в каждой зоне, по её id. */
  zones: Record<string, number>;
  fps: number | null;
  latencyMs: number | null;
  confidence: number | null;
  updatedAt: string | null;
}

const WINDOW_MS = 2000;
const TICK_MS = 1000;

const EMPTY: CalmLive = {
  peopleInFrame: null,
  peopleInZone: null,
  queue: null,
  avgWaitSeconds: null,
  zones: {},
  fps: null,
  latencyMs: null,
  confidence: null,
  updatedAt: null,
};

export function useCalmLive(frame: LiveMessage | null): CalmLive {
  const samples = useRef<Array<{ at: number; frame: LiveMessage }>>([]);
  const [calm, setCalm] = useState<CalmLive>(EMPTY);

  useEffect(() => {
    if (!frame || frame.frameIndex < 0 || !frame.metrics) return;
    const now = Date.now();
    samples.current.push({ at: now, frame });
    samples.current = samples.current.filter((sample) => now - sample.at <= WINDOW_MS);
  }, [frame]);

  useEffect(() => {
    const compute = () => {
      const now = Date.now();
      const recent = samples.current.filter((sample) => now - sample.at <= WINDOW_MS);
      // Кадров за окно нет (связь просела) — оставляем последние показания:
      // пропажу сигнала объясняет диагностика, цифры не должны прыгать в ноль.
      if (recent.length === 0) return;
      setCalm(summarize(recent.map((sample) => sample.frame)));
    };
    compute();
    const timer = window.setInterval(compute, TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  return calm;
}

export function summarize(frames: LiveMessage[]): CalmLive {
  const last = frames[frames.length - 1];
  const zoneIds = new Set(frames.flatMap((frame) => frame.zones.map((zone) => zone.id)));
  const zones: Record<string, number> = {};
  for (const id of zoneIds) {
    const counts = frames
      .map((frame) => frame.zones.find((zone) => zone.id === id)?.people)
      .filter((value): value is number => typeof value === "number");
    const value = median(counts);
    if (value !== null) zones[id] = value;
  }

  return {
    peopleInFrame: median(frames.map((frame) => frame.metrics.peopleInFrame)),
    peopleInZone: median(frames.map((frame) => frame.metrics.peopleInZone)),
    queue: median(frames.map((frame) => frame.metrics.queue)),
    avgWaitSeconds: last.metrics.avgWaitSeconds,
    zones,
    fps: mean(frames.map((frame) => frame.technical.fps)),
    latencyMs: mean(frames.map((frame) => frame.technical.latencyMs)),
    confidence: mean(
      frames
        .map((frame) => frame.technical.confidence)
        .filter((value): value is number => value !== null),
    ),
    updatedAt: last.updatedAt,
  };
}

/** Медиана, округлённая до целого человека. */
export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  const value = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  return Math.round(value);
}

function mean(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

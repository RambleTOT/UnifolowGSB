import { useEffect, useRef } from "react";

import type { LiveMessage } from "../../api/types";

export interface OverlayToggles {
  boxes: boolean;
  trackIds: boolean;
  geometry: boolean;
}

interface FrameOverlayProps {
  frame: LiveMessage | null;
  toggles: OverlayToggles;
  /** Вспышки засчитанных проходов: главный признак, что система считает верно. */
  flashes: Array<{ id: number; x: number; y: number; direction: "in" | "out"; line: string; at: number }>;
  /** Число людей в зонах для подписей — спокойное, раз в секунду. */
  zoneCounts?: Record<string, number>;
  /**
   * Плавное движение рамок. В режиме «Точный анализ» выключено: там рамки
   * должны совпадать с кадром, который обработала модель, до пикселя.
   */
  smooth?: boolean;
}

const COLORS: Record<string, string> = {
  moving: "#1b5fcb",
  queue: "#1b6b4e",
  crossing: "#f5a623",
};

const FLASH_MS = 1200;
// За сколько рамка проходит путь до нового положения: при 3–8 кадрах в секунду
// от модели этого хватает, чтобы движение выглядело непрерывным.
const FOLLOW_MS = 140;
const FADE_IN_MS = 180;
const FADE_OUT_MS = 320;
// Скачок больше этой доли кадра — это не движение, а новая сцена или сбой
// сопровождения: такую рамку ставим сразу, без проезда через весь кадр.
const SNAP_DISTANCE = 0.2;

type Box = [number, number, number, number];

interface Shown {
  bbox: Box;
  anchor: [number, number];
  alpha: number;
  state: string;
  confidence: number;
  present: boolean;
}

/**
 * Наложение аналитики рисуется поверх изображения на клиенте.
 *
 * Поэтому переключатели рамок, номеров и геометрии работают мгновенно и
 * одинаково в обоих режимах просмотра (задание, раздел 8). Рисование идёт
 * своим циклом кадров браузера, а не по каждому сообщению сервера: рамки
 * подтягиваются к новому положению плавно, появляются и исчезают с коротким
 * затуханием, а не перескакивают.
 */
export function FrameOverlay({ frame, toggles, flashes, zoneCounts, smooth = true }: FrameOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const props = useRef({ frame, toggles, flashes, zoneCounts, smooth });
  props.current = { frame, toggles, flashes, zoneCounts, smooth };
  const shown = useRef(new Map<number, Shown>());

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;

    let raf = 0;
    let previous = performance.now();

    const tick = (now: number) => {
      const elapsed = Math.min(now - previous, 250);
      previous = now;
      follow(shown.current, props.current.frame, props.current.smooth, elapsed);
      draw(canvas, parent, props.current, shown.current);
      raf = window.requestAnimationFrame(tick);
    };

    raf = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(raf);
  }, []);

  return <canvas ref={canvasRef} className="overlay" aria-hidden="true" />;
}

/** Подтянуть показанные рамки к последнему кадру. */
function follow(tracks: Map<number, Shown>, frame: LiveMessage | null, smooth: boolean, elapsed: number) {
  const objects = frame?.objects ?? [];
  const step = smooth ? 1 - Math.exp(-elapsed / FOLLOW_MS) : 1;
  const seen = new Set<number>();

  for (const object of objects) {
    seen.add(object.trackId);
    const target = object.bbox as Box;
    const current = tracks.get(object.trackId);
    if (!current || !smooth || distance(current.bbox, target) > SNAP_DISTANCE) {
      tracks.set(object.trackId, {
        bbox: [...target] as Box,
        anchor: [...object.anchor] as [number, number],
        alpha: current && smooth ? current.alpha : smooth ? 0 : 1,
        state: object.state,
        confidence: object.confidence,
        present: true,
      });
      continue;
    }
    current.bbox = current.bbox.map((value, index) => value + (target[index] - value) * step) as Box;
    current.anchor = [
      current.anchor[0] + (object.anchor[0] - current.anchor[0]) * step,
      current.anchor[1] + (object.anchor[1] - current.anchor[1]) * step,
    ];
    current.state = object.state;
    current.confidence = object.confidence;
    current.present = true;
  }

  for (const [trackId, track] of tracks) {
    if (seen.has(trackId)) {
      track.alpha = smooth ? Math.min(1, track.alpha + elapsed / FADE_IN_MS) : 1;
      continue;
    }
    track.present = false;
    track.alpha = smooth ? track.alpha - elapsed / FADE_OUT_MS : 0;
    if (track.alpha <= 0) tracks.delete(trackId);
  }
}

function distance(left: Box, right: Box): number {
  const leftX = (left[0] + left[2]) / 2;
  const leftY = (left[1] + left[3]) / 2;
  const rightX = (right[0] + right[2]) / 2;
  const rightY = (right[1] + right[3]) / 2;
  return Math.hypot(leftX - rightX, leftY - rightY);
}

function draw(
  canvas: HTMLCanvasElement,
  parent: HTMLElement,
  props: FrameOverlayProps,
  tracks: Map<number, Shown>,
) {
  const width = parent.clientWidth;
  const height = parent.clientHeight;
  const ratio = window.devicePixelRatio || 1;

  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
  }

  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);

  const { frame, toggles, flashes, zoneCounts } = props;
  if (!frame) return;

  const px = (value: number) => value * width;
  const py = (value: number) => value * height;
  // На узком экране подписи мельче, иначе они закрывают половину кадра.
  const compact = width < 520;

  if (toggles.geometry) {
    for (const zone of frame.zones) {
      if (zone.polygon.length < 3) continue;
      context.beginPath();
      zone.polygon.forEach(([x, y], index) => {
        if (index === 0) context.moveTo(px(x), py(y));
        else context.lineTo(px(x), py(y));
      });
      context.closePath();
      context.fillStyle = zone.kind === "queue" ? "rgba(75,132,255,0.16)" : "rgba(90,192,138,0.16)";
      context.fill();
      context.lineWidth = 2;
      context.setLineDash([6, 4]);
      context.strokeStyle = zone.kind === "queue" ? "#4b84ff" : "#5ac08a";
      context.stroke();
      context.setLineDash([]);

      const people = zoneCounts?.[zone.id] ?? zone.people;
      const [ax, ay] = zone.polygon[0];
      drawLabel(
        context,
        compact ? `${people} чел` : `${zone.name} · ${people} чел`,
        px(ax) + 6,
        py(ay) + 18,
        zone.kind === "queue" ? "#4b84ff" : "#5ac08a",
        1,
        compact,
        width,
      );
    }

    for (const line of frame.lines) {
      const [ax, ay] = line.a;
      const [bx, by] = line.b;
      context.beginPath();
      context.moveTo(px(ax), py(ay));
      context.lineTo(px(bx), py(by));
      context.lineWidth = 3;
      context.strokeStyle = "#f5a623";
      context.stroke();

      // Стрелка показывает сторону «вход» — самое частое место ошибки.
      const midX = (px(ax) + px(bx)) / 2;
      const midY = (py(ay) + py(by)) / 2;
      const dx = px(bx) - px(ax);
      const dy = py(by) - py(ay);
      const length = Math.max(1, Math.hypot(dx, dy));
      const normalX = (-dy / length) * (line.entrySide > 0 ? 1 : -1);
      const normalY = (dx / length) * (line.entrySide > 0 ? 1 : -1);
      const arrow = compact ? 24 : 42;
      const tipX = midX + normalX * arrow;
      const tipY = midY + normalY * arrow;

      context.beginPath();
      context.moveTo(midX, midY);
      context.lineTo(tipX, tipY);
      context.stroke();
      context.beginPath();
      context.arc(tipX, tipY, 5, 0, Math.PI * 2);
      context.fillStyle = "#f5a623";
      context.fill();

      drawLabel(
        context,
        compact ? `↑${line.entered} / ↓${line.exited}` : `${line.name} · вход ↑${line.entered} / ↓${line.exited}`,
        Math.min(px(ax), px(bx)),
        Math.min(py(ay), py(by)) - 10,
        "#f5a623",
        1,
        compact,
        width,
      );
    }
  }

  if (toggles.boxes) {
    for (const track of tracks.values()) {
      const [x1, y1, x2, y2] = track.bbox;
      const color = COLORS[track.state] ?? COLORS.moving;
      context.save();
      context.globalAlpha = Math.max(0, Math.min(1, track.alpha));
      context.lineWidth = track.state === "crossing" ? 3 : 2;
      context.strokeStyle = color;
      context.strokeRect(px(x1), py(y1), px(x2 - x1), py(y2 - y1));

      const [anchorX, anchorY] = track.anchor;
      context.beginPath();
      context.arc(px(anchorX), py(anchorY), compact ? 2.5 : 3.5, 0, Math.PI * 2);
      context.fillStyle = "#ffffff";
      context.fill();
      context.lineWidth = 1;
      context.strokeStyle = color;
      context.stroke();
      context.restore();
    }

    if (toggles.trackIds) {
      for (const [trackId, track] of tracks) {
        if (!track.present) continue;
        const [x1, y1] = track.bbox;
        drawLabel(
          context,
          compact ? `#${trackId}` : `#${trackId} · ${Math.round(track.confidence * 100)} %`,
          px(x1),
          py(y1) - 6,
          COLORS[track.state] ?? COLORS.moving,
          track.alpha,
          compact,
          width,
        );
      }
    }
  }

  const now = Date.now();
  for (const flash of flashes) {
    const age = now - flash.at;
    if (age > FLASH_MS) continue;
    const progress = age / FLASH_MS;
    context.beginPath();
    context.arc(px(flash.x), py(flash.y), 18 + progress * 26, 0, Math.PI * 2);
    context.lineWidth = 3;
    context.strokeStyle = `rgba(245,166,35,${1 - progress})`;
    context.stroke();
    drawLabel(
      context,
      compact
        ? flash.direction === "in" ? "ВХОД" : "ВЫХОД"
        : flash.direction === "in" ? `ВХОД · ${flash.line}` : `ВЫХОД · ${flash.line}`,
      px(flash.x) + 26,
      py(flash.y) - 10,
      "#f5a623",
      1 - progress,
      compact,
      width,
    );
  }
}

function drawLabel(
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  background: string,
  alpha = 1,
  compact = false,
  limit = Infinity,
): void {
  context.save();
  context.globalAlpha = Math.max(0, Math.min(1, alpha));
  context.font = `600 ${compact ? 10 : 12}px 'Source Sans 3', system-ui, sans-serif`;
  const width = context.measureText(text).width;
  const boxWidth = width + (compact ? 8 : 12);
  const boxHeight = compact ? 15 : 18;
  // Подпись у правого края не уезжает за пределы кадра.
  const left = Math.max(0, Math.min(x, limit - boxWidth));
  const top = Math.max(boxHeight, y);
  context.fillStyle = background;
  context.fillRect(left, top - boxHeight + 4, boxWidth, boxHeight);
  context.fillStyle = "#ffffff";
  context.fillText(text, left + (compact ? 4 : 6), top - 1);
  context.restore();
}

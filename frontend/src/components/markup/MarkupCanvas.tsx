import { useCallback, useEffect, useRef, useState } from "react";

import type { Draft } from "./geometry";
import { clamp01, entryArrow, polygonCentroid } from "./geometry";

interface MarkupCanvasProps {
  image: string | null;
  /** Опорные точки людей: по ним считается пересечение и попадание в зону. */
  anchors: Array<[number, number]>;
  draft: Draft;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onChange: (draft: Draft, options?: { commit?: boolean }) => void;
  problems: Record<string, string>;
}

type DragTarget =
  | { kind: "zone-point"; id: string; index: number }
  | { kind: "zone-body"; id: string; start: [number, number] }
  | { kind: "line-point"; id: string; end: "a" | "b" }
  | { kind: "line-body"; id: string; start: [number, number] };

export function MarkupCanvas({
  image,
  anchors,
  draft,
  selectedId,
  onSelect,
  onChange,
  problems,
}: MarkupCanvasProps) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 960, height: 540 });
  const dragRef = useRef<DragTarget | null>(null);

  useEffect(() => {
    const element = surfaceRef.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      setSize({ width: element.clientWidth, height: element.clientHeight });
    });
    observer.observe(element);
    setSize({ width: element.clientWidth, height: element.clientHeight });
    return () => observer.disconnect();
  }, []);

  const toNormalized = useCallback(
    (event: React.PointerEvent): [number, number] => {
      const element = surfaceRef.current;
      if (!element) return [0, 0];
      const rect = element.getBoundingClientRect();
      return [
        clamp01((event.clientX - rect.left) / rect.width),
        clamp01((event.clientY - rect.top) / rect.height),
      ];
    },
    [],
  );

  const px = (value: number) => value * size.width;
  const py = (value: number) => value * size.height;

  const onPointerMove = (event: React.PointerEvent) => {
    const target = dragRef.current;
    if (!target) return;
    const [x, y] = toNormalized(event);
    const next = { ...draft, zones: [...draft.zones], lines: [...draft.lines] };

    if (target.kind === "zone-point") {
      next.zones = next.zones.map((zone) =>
        zone.id === target.id
          ? {
              ...zone,
              polygon: zone.polygon.map((point, index) =>
                index === target.index ? ([x, y] as [number, number]) : point,
              ),
            }
          : zone,
      );
    } else if (target.kind === "zone-body") {
      const dx = x - target.start[0];
      const dy = y - target.start[1];
      next.zones = next.zones.map((zone) =>
        zone.id === target.id
          ? {
              ...zone,
              polygon: zone.polygon.map(
                ([pointX, pointY]) => [clamp01(pointX + dx), clamp01(pointY + dy)] as [number, number],
              ),
            }
          : zone,
      );
      dragRef.current = { ...target, start: [x, y] };
    } else if (target.kind === "line-point") {
      next.lines = next.lines.map((line) =>
        line.id === target.id ? { ...line, [target.end]: [x, y] as [number, number] } : line,
      );
    } else {
      const dx = x - target.start[0];
      const dy = y - target.start[1];
      next.lines = next.lines.map((line) =>
        line.id === target.id
          ? {
              ...line,
              a: [clamp01(line.a[0] + dx), clamp01(line.a[1] + dy)] as [number, number],
              b: [clamp01(line.b[0] + dx), clamp01(line.b[1] + dy)] as [number, number],
            }
          : line,
      );
      dragRef.current = { ...target, start: [x, y] };
    }

    onChange(next);
  };

  const endDrag = (event: React.PointerEvent) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    (event.target as Element).releasePointerCapture?.(event.pointerId);
    // Перетаскивание — одно действие для отмены, а не сотня микрошагов.
    onChange(draft, { commit: true });
  };

  const startDrag = (event: React.PointerEvent, target: DragTarget) => {
    event.stopPropagation();
    (event.target as Element).setPointerCapture?.(event.pointerId);
    dragRef.current = target;
  };

  return (
    <div
      ref={surfaceRef}
      className="markup-surface"
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
      onClick={() => onSelect(null)}
    >
      {image ? (
        <img className="markup-surface__image" src={image} alt="Кадр для разметки" />
      ) : (
        <div className="markup-surface__empty">Кадр загружается…</div>
      )}

      <svg className="markup-surface__svg" width={size.width} height={size.height}>
        {anchors.map(([x, y], index) => (
          <g key={`anchor-${index}`}>
            <circle cx={px(x)} cy={py(y)} r={5} className="anchor" />
            <circle cx={px(x)} cy={py(y)} r={9} className="anchor anchor--halo" />
          </g>
        ))}

        {draft.zones.map((zone) => {
          const selected = zone.id === selectedId;
          const [cx, cy] = polygonCentroid(zone.polygon);
          return (
            <g key={zone.id} className={`shape ${selected ? "shape--selected" : ""}`}>
              <polygon
                points={zone.polygon.map(([x, y]) => `${px(x)},${py(y)}`).join(" ")}
                className={`zone zone--${zone.kind} ${problems[zone.id] ? "zone--invalid" : ""}`}
                onPointerDown={(event) => {
                  onSelect(zone.id);
                  startDrag(event, { kind: "zone-body", id: zone.id, start: toNormalized(event) });
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(zone.id);
                }}
              />
              <text x={px(cx)} y={py(cy)} className="shape__label" textAnchor="middle">
                {zone.name}
              </text>
              {selected &&
                zone.polygon.map(([x, y], index) => (
                  <circle
                    key={`${zone.id}-${index}`}
                    cx={px(x)}
                    cy={py(y)}
                    r={7}
                    className="handle"
                    onPointerDown={(event) =>
                      startDrag(event, { kind: "zone-point", id: zone.id, index })
                    }
                  />
                ))}
            </g>
          );
        })}

        {draft.lines.map((line) => {
          const selected = line.id === selectedId;
          const arrow = entryArrow(line);
          const tipX = px(arrow.x) + arrow.dx * 54;
          const tipY = py(arrow.y) + arrow.dy * 54;
          return (
            <g key={line.id} className={`shape ${selected ? "shape--selected" : ""}`}>
              <line
                x1={px(line.a[0])}
                y1={py(line.a[1])}
                x2={px(line.b[0])}
                y2={py(line.b[1])}
                className={`line ${problems[line.id] ? "line--invalid" : ""}`}
                onPointerDown={(event) => {
                  onSelect(line.id);
                  startDrag(event, { kind: "line-body", id: line.id, start: toNormalized(event) });
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(line.id);
                }}
              />
              <line
                x1={px(arrow.x)}
                y1={py(arrow.y)}
                x2={tipX}
                y2={tipY}
                className="line__arrow"
              />
              <circle cx={tipX} cy={tipY} r={6} className="line__arrow-tip" />
              <text x={tipX + 10} y={tipY} className="shape__label shape__label--line">
                вход
              </text>
              {selected && (
                <>
                  <circle
                    cx={px(line.a[0])}
                    cy={py(line.a[1])}
                    r={7}
                    className="handle"
                    onPointerDown={(event) => startDrag(event, { kind: "line-point", id: line.id, end: "a" })}
                  />
                  <circle
                    cx={px(line.b[0])}
                    cy={py(line.b[1])}
                    r={7}
                    className="handle"
                    onPointerDown={(event) => startDrag(event, { kind: "line-point", id: line.id, end: "b" })}
                  />
                </>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

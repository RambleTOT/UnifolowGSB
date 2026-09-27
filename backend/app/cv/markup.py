"""Разметка источника: зоны анализа и контрольные линии.

Одна и та же структура используется редактором разметки в интерфейсе
(ТЗ, раздел 5.7.2), хранением в базе и офлайн-проверкой scripts/evaluate.py.
Координаты нормированы к кадру (0..1), поэтому разметка переживает смену
разрешения видеофайла.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.cv.counting import CountingParams, LineSpec, ZoneSpec
from app.cv.geometry import (
    AnchorMode,
    Point,
    points_within_frame,
    polygon_area,
    polygon_self_intersects,
    segment_length,
)

# Минимальные размеры объектов разметки в долях кадра.
MIN_POLYGON_AREA = 0.002
MIN_LINE_LENGTH = 0.05


@dataclass(frozen=True, slots=True)
class Markup:
    lines: tuple[LineSpec, ...] = ()
    zones: tuple[ZoneSpec, ...] = ()
    anchor: AnchorMode = "bottom_center"

    @property
    def is_empty(self) -> bool:
        return not self.lines and not self.zones

    def counting_params(self, base: CountingParams | None = None) -> CountingParams:
        params = base or CountingParams()
        if params.anchor == self.anchor:
            return params
        return CountingParams(
            anchor=self.anchor,
            min_track_age_frames=params.min_track_age_frames,
            dead_zone=params.dead_zone,
            crossing_debounce_seconds=params.crossing_debounce_seconds,
            crossing_state_seconds=params.crossing_state_seconds,
            lost_track_seconds=params.lost_track_seconds,
            inherit_max_gap_seconds=params.inherit_max_gap_seconds,
            inherit_max_distance=params.inherit_max_distance,
        )


def _point(raw: Any) -> Point:
    if isinstance(raw, dict):
        return Point(float(raw["x"]), float(raw["y"]))
    x, y = raw
    return Point(float(x), float(y))


def markup_from_dict(payload: dict[str, Any]) -> Markup:
    lines = tuple(
        LineSpec(
            id=str(item["id"]),
            name=str(item.get("name", "Контрольная линия")),
            a=_point(item["a"]),
            b=_point(item["b"]),
            entry_side=int(item.get("entry_side", 1)),
            counts=item.get("counts", "both"),
        )
        for item in payload.get("lines", [])
    )
    zones = tuple(
        ZoneSpec(
            id=str(item["id"]),
            name=str(item.get("name", "Зона")),
            polygon=tuple(_point(point) for point in item["polygon"]),
            kind=item.get("kind", "queue"),
            min_dwell_seconds=float(item.get("min_dwell_seconds", 5.0)),
            capacity=item.get("capacity"),
        )
        for item in payload.get("zones", [])
    )
    return Markup(lines=lines, zones=zones, anchor=payload.get("anchor", "bottom_center"))


def markup_to_dict(markup: Markup) -> dict[str, Any]:
    return {
        "anchor": markup.anchor,
        "lines": [
            {
                "id": line.id,
                "name": line.name,
                "a": [line.a.x, line.a.y],
                "b": [line.b.x, line.b.y],
                "entry_side": line.entry_side,
                "counts": line.counts,
            }
            for line in markup.lines
        ],
        "zones": [
            {
                "id": zone.id,
                "name": zone.name,
                "kind": zone.kind,
                "min_dwell_seconds": zone.min_dwell_seconds,
                "capacity": zone.capacity,
                "polygon": [[point.x, point.y] for point in zone.polygon],
            }
            for zone in markup.zones
        ],
    }


@dataclass(frozen=True, slots=True)
class MarkupProblem:
    """Замечание валидации: адресуется конкретному объекту разметки."""

    object_id: str
    code: str
    message: str


def validate_markup(markup: Markup) -> list[MarkupProblem]:
    """Проверки из ТЗ, раздел 5.7.2. Пустой список — разметку можно сохранять."""
    problems: list[MarkupProblem] = []
    seen_names: dict[str, str] = {}

    def check_name(object_id: str, name: str) -> None:
        key = name.strip().lower()
        if not key:
            problems.append(MarkupProblem(object_id, "empty_name", "Название не заполнено."))
            return
        if key in seen_names:
            problems.append(
                MarkupProblem(object_id, "duplicate_name", f"Название «{name}» уже занято.")
            )
        seen_names[key] = object_id

    for line in markup.lines:
        check_name(line.id, line.name)
        if not points_within_frame([line.a, line.b]):
            problems.append(
                MarkupProblem(line.id, "outside_frame", "Линия выходит за пределы кадра.")
            )
        if segment_length(line.a, line.b) < MIN_LINE_LENGTH:
            problems.append(
                MarkupProblem(
                    line.id,
                    "line_too_short",
                    "Линия слишком короткая: люди будут проходить мимо неё.",
                )
            )
        if line.entry_side not in (-1, 1):
            problems.append(
                MarkupProblem(line.id, "bad_entry_side", "Не задана сторона «вход».")
            )

    for zone in markup.zones:
        check_name(zone.id, zone.name)
        if len(zone.polygon) < 3:
            problems.append(
                MarkupProblem(zone.id, "too_few_points", "У зоны меньше трёх точек.")
            )
            continue
        if not points_within_frame(zone.polygon):
            problems.append(
                MarkupProblem(zone.id, "outside_frame", "Зона выходит за пределы кадра.")
            )
        if polygon_self_intersects(zone.polygon):
            problems.append(
                MarkupProblem(zone.id, "self_intersection", "Контур зоны сам себя пересекает.")
            )
        if polygon_area(zone.polygon) < MIN_POLYGON_AREA:
            problems.append(
                MarkupProblem(zone.id, "zone_too_small", "Площадь зоны слишком мала.")
            )
        if zone.kind == "queue" and zone.min_dwell_seconds <= 0:
            problems.append(
                MarkupProblem(
                    zone.id,
                    "bad_min_dwell",
                    "Минимальное время в зоне должно быть больше нуля.",
                )
            )

    return problems


def readiness(markup: Markup) -> str:
    """Готовность источника к подсчёту (ТЗ, раздел 3.3) по одной разметке."""
    if markup.is_empty:
        return "no_markup"
    has_line = bool(markup.lines)
    has_queue = any(zone.kind == "queue" for zone in markup.zones)
    has_occupancy = any(zone.kind == "occupancy" for zone in markup.zones)
    if has_line and (has_queue or has_occupancy):
        return "ready"
    return "partial"


def describe_missing(markup: Markup) -> list[str]:
    """Чего не хватает, чтобы считались все метрики — текстом для интерфейса."""
    missing: list[str] = []
    if not markup.lines:
        missing.append("не задана контрольная линия")
    if not any(zone.kind == "queue" for zone in markup.zones):
        missing.append("не задана зона очереди")
    if not any(zone.kind == "occupancy" for zone in markup.zones):
        missing.append("не задана зона заполненности")
    return missing


def default_markup_for_frame() -> Markup:
    """Черновая разметка «поперёк кадра»: отправная точка для калибровки."""
    return Markup(
        lines=(
            LineSpec(
                id="line-main",
                name="Основной проход",
                a=Point(0.15, 0.55),
                b=Point(0.85, 0.55),
                entry_side=-1,
            ),
        ),
        zones=(),
    )


def markup_from_specs(lines: Sequence[LineSpec], zones: Sequence[ZoneSpec]) -> Markup:
    return Markup(lines=tuple(lines), zones=tuple(zones))

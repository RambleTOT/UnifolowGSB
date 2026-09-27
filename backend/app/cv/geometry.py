"""Геометрия подсчёта в нормированных координатах кадра.

Все точки нормированы к кадру: x и y лежат в диапазоне 0..1, где (0, 0) — левый
верхний угол. Благодаря этому разметка не зависит от разрешения видеофайла
(ТЗ, раздел 5.7.2) и переживает замену файла на другое разрешение.

Модуль намеренно не зависит ни от OpenCV, ни от numpy: это чистые функции,
которые легко покрыть тестами (задание на разработку, раздел 12).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

AnchorMode = Literal["bottom_center", "center"]

# Порог, ниже которого координаты считаются совпадающими.
EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def __iter__(self):
        yield self.x
        yield self.y


def bbox_anchor(bbox: Sequence[float], mode: AnchorMode = "bottom_center") -> Point:
    """Опорная точка человека по рамке (x1, y1, x2, y2).

    По умолчанию — середина нижней границы рамки («ноги»): именно по ней
    засчитываются пересечения линии и попадание в зону. Для съёмки строго
    сверху опорной точкой служит центр рамки.
    """
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) / 2.0
    if mode == "center":
        return Point(cx, (y1 + y2) / 2.0)
    return Point(cx, max(y1, y2))


def cross(a: Point, b: Point, p: Point) -> float:
    """Векторное произведение (b - a) × (p - a).

    Знак показывает, с какой стороны от направленной прямой a→b лежит точка p.
    """
    return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)


def side_of_line(a: Point, b: Point, p: Point) -> int:
    """Сторона точки относительно линии: +1, -1 или 0 (точно на прямой)."""
    value = cross(a, b, p)
    if value > EPS:
        return 1
    if value < -EPS:
        return -1
    return 0


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    """Лежит ли точка p на отрезке ab при условии, что она на прямой ab."""
    return (
        min(a.x, b.x) - EPS <= p.x <= max(a.x, b.x) + EPS
        and min(a.y, b.y) - EPS <= p.y <= max(a.y, b.y) + EPS
    )


def segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """Пересекаются ли отрезки p1p2 и p3p4.

    Проверяется пересечение именно отрезков, а не их продолжений: человек,
    прошедший в стороне от линии, не должен давать проход (задание, раздел 5.2).
    """
    d1 = side_of_line(p3, p4, p1)
    d2 = side_of_line(p3, p4, p2)
    d3 = side_of_line(p1, p2, p3)
    d4 = side_of_line(p1, p2, p4)

    if d1 * d2 < 0 and d3 * d4 < 0:
        return True

    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):
        return True
    return False


def distance_point_to_segment(p: Point, a: Point, b: Point) -> float:
    """Расстояние от точки до отрезка в нормированных единицах."""
    dx = b.x - a.x
    dy = b.y - a.y
    if abs(dx) < EPS and abs(dy) < EPS:
        return ((p.x - a.x) ** 2 + (p.y - a.y) ** 2) ** 0.5

    t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    nearest_x = a.x + t * dx
    nearest_y = a.y + t * dy
    return ((p.x - nearest_x) ** 2 + (p.y - nearest_y) ** 2) ** 0.5


def point_in_polygon(polygon: Sequence[Point], p: Point) -> bool:
    """Точка внутри многоугольника (алгоритм трассировки луча).

    Точка на границе считается внутри: человек, стоящий на краю зоны очереди,
    не должен то попадать в неё, то выпадать из-за дрожания рамки.
    """
    if len(polygon) < 3:
        return False

    for index in range(len(polygon)):
        a = polygon[index]
        b = polygon[(index + 1) % len(polygon)]
        if side_of_line(a, b, p) == 0 and _on_segment(a, b, p):
            return True

    inside = False
    for index in range(len(polygon)):
        a = polygon[index]
        b = polygon[(index + 1) % len(polygon)]
        if (a.y > p.y) != (b.y > p.y):
            x_at_p = (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x
            if p.x < x_at_p:
                inside = not inside
    return inside


def polygon_area(polygon: Sequence[Point]) -> float:
    """Площадь многоугольника в долях кадра (формула шнурков)."""
    if len(polygon) < 3:
        return 0.0
    total = 0.0
    for index in range(len(polygon)):
        a = polygon[index]
        b = polygon[(index + 1) % len(polygon)]
        total += a.x * b.y - b.x * a.y
    return abs(total) / 2.0


def polygon_self_intersects(polygon: Sequence[Point]) -> bool:
    """Есть ли у многоугольника самопересечение (валидация разметки)."""
    count = len(polygon)
    if count < 4:
        return False

    for i in range(count):
        a1, a2 = polygon[i], polygon[(i + 1) % count]
        for j in range(i + 1, count):
            # Соседние рёбра имеют общую вершину — их не сравниваем.
            if j == i or (j + 1) % count == i or j == (i + 1) % count:
                continue
            b1, b2 = polygon[j], polygon[(j + 1) % count]
            if segments_intersect(a1, a2, b1, b2):
                return True
    return False


def segment_length(a: Point, b: Point) -> float:
    return ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5


def points_within_frame(points: Iterable[Point]) -> bool:
    return all(-EPS <= p.x <= 1 + EPS and -EPS <= p.y <= 1 + EPS for p in points)


def distance(a: Point, b: Point) -> float:
    return segment_length(a, b)

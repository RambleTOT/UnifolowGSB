"""Тесты геометрии разметки."""

import pytest

from app.cv.geometry import (
    Point,
    bbox_anchor,
    distance_point_to_segment,
    point_in_polygon,
    polygon_area,
    polygon_self_intersects,
    segments_intersect,
    side_of_line,
)

SQUARE = (Point(0.2, 0.2), Point(0.6, 0.2), Point(0.6, 0.6), Point(0.2, 0.6))


def test_anchor_is_bottom_center_by_default():
    anchor = bbox_anchor((0.40, 0.10, 0.50, 0.70))
    assert anchor == Point(0.45, 0.70)


def test_anchor_center_for_top_down_view():
    anchor = bbox_anchor((0.40, 0.10, 0.50, 0.70), "center")
    assert anchor.x == pytest.approx(0.45)
    assert anchor.y == pytest.approx(0.40)


def test_side_of_line_distinguishes_sides():
    a, b = Point(0.2, 0.5), Point(0.8, 0.5)
    assert side_of_line(a, b, Point(0.5, 0.7)) == 1
    assert side_of_line(a, b, Point(0.5, 0.3)) == -1
    assert side_of_line(a, b, Point(0.5, 0.5)) == 0


def test_segments_intersect_only_when_segments_really_cross():
    line_a, line_b = Point(0.2, 0.5), Point(0.8, 0.5)
    assert segments_intersect(Point(0.5, 0.4), Point(0.5, 0.6), line_a, line_b)
    # Продолжение линии не считается: человек прошёл в стороне.
    assert not segments_intersect(Point(0.95, 0.4), Point(0.95, 0.6), line_a, line_b)
    # Движение вдоль одной стороны линии.
    assert not segments_intersect(Point(0.3, 0.6), Point(0.7, 0.6), line_a, line_b)


def test_point_in_polygon_includes_border():
    assert point_in_polygon(SQUARE, Point(0.4, 0.4))
    assert point_in_polygon(SQUARE, Point(0.2, 0.4))  # на границе
    assert not point_in_polygon(SQUARE, Point(0.1, 0.4))
    assert not point_in_polygon(SQUARE, Point(0.4, 0.9))


def test_polygon_area_and_self_intersection():
    assert polygon_area(SQUARE) == pytest.approx(0.16)
    assert not polygon_self_intersects(SQUARE)
    bowtie = (Point(0.2, 0.2), Point(0.6, 0.6), Point(0.6, 0.2), Point(0.2, 0.6))
    assert polygon_self_intersects(bowtie)


def test_distance_to_segment_uses_nearest_point():
    a, b = Point(0.2, 0.5), Point(0.8, 0.5)
    assert abs(distance_point_to_segment(Point(0.5, 0.52), a, b) - 0.02) < 1e-9
    # За концом отрезка расстояние считается до самого конца, а не до прямой.
    assert abs(distance_point_to_segment(Point(1.0, 0.5), a, b) - 0.2) < 1e-9

"""Тесты разметки: разбор, валидация и готовность источника к подсчёту."""

from app.cv.geometry import Point
from app.cv.markup import (
    Markup,
    describe_missing,
    markup_from_dict,
    markup_to_dict,
    readiness,
    validate_markup,
)

PAYLOAD = {
    "anchor": "bottom_center",
    "lines": [
        {
            "id": "line-main",
            "name": "Основной проход",
            "a": [0.15, 0.55],
            "b": [0.85, 0.55],
            "entry_side": -1,
            "counts": "both",
        }
    ],
    "zones": [
        {
            "id": "zone-queue",
            "name": "Очередь раздачи",
            "kind": "queue",
            "min_dwell_seconds": 5,
            "polygon": [[0.1, 0.6], [0.6, 0.6], [0.6, 0.95], [0.1, 0.95]],
        }
    ],
}


def test_markup_round_trip_keeps_values():
    markup = markup_from_dict(PAYLOAD)
    again = markup_from_dict(markup_to_dict(markup))

    assert again.lines[0].name == "Основной проход"
    assert again.lines[0].entry_side == -1
    assert again.zones[0].min_dwell_seconds == 5
    assert again.zones[0].polygon[0] == Point(0.1, 0.6)


def test_valid_markup_has_no_problems():
    assert validate_markup(markup_from_dict(PAYLOAD)) == []


def test_validation_catches_short_line_and_bad_polygon():
    payload = {
        "lines": [
            {"id": "short", "name": "Коротышка", "a": [0.5, 0.5], "b": [0.52, 0.5], "entry_side": -1}
        ],
        "zones": [
            {
                "id": "bowtie",
                "name": "Бабочка",
                "kind": "queue",
                "polygon": [[0.2, 0.2], [0.6, 0.6], [0.6, 0.2], [0.2, 0.6]],
            }
        ],
    }
    codes = {problem.code for problem in validate_markup(markup_from_dict(payload))}
    assert "line_too_short" in codes
    assert "self_intersection" in codes


def test_validation_catches_duplicate_names_and_frame_bounds():
    payload = {
        "lines": [
            {"id": "a", "name": "Проход", "a": [0.1, 0.5], "b": [0.9, 0.5], "entry_side": 1},
            {"id": "b", "name": "проход", "a": [0.1, 0.7], "b": [1.4, 0.7], "entry_side": 1},
        ]
    }
    problems = validate_markup(markup_from_dict(payload))
    codes = {problem.code for problem in problems}
    assert "duplicate_name" in codes
    assert "outside_frame" in codes


def test_readiness_reflects_what_is_marked_up():
    assert readiness(Markup()) == "no_markup"

    only_line = markup_from_dict({"lines": PAYLOAD["lines"]})
    assert readiness(only_line) == "partial"
    assert "не задана зона очереди" in describe_missing(only_line)

    full = markup_from_dict(
        {
            "lines": PAYLOAD["lines"],
            "zones": PAYLOAD["zones"]
            + [
                {
                    "id": "zone-hall",
                    "name": "Зал",
                    "kind": "occupancy",
                    "polygon": [[0.05, 0.3], [0.95, 0.3], [0.95, 0.98], [0.05, 0.98]],
                }
            ],
        }
    )
    assert readiness(full) == "ready"
    assert describe_missing(full) == []

"""Тесты ядра подсчёта: проходы через линию и время в зонах.

Кадр считается по опорной точке «ноги», поэтому в тестах прямоугольник строится
так, что его нижняя грань проходит через заданную точку.
"""

import pytest

from app.cv.counting import (
    CountingEngine,
    CountingParams,
    LineSpec,
    TrackObservation,
    ZoneSpec,
)
from app.cv.geometry import Point

# Горизонтальная линия поперёк кадра. Сторона «вход» — верхняя (меньшие y).
LINE = LineSpec(
    id="line-main",
    name="Основной проход",
    a=Point(0.2, 0.5),
    b=Point(0.8, 0.5),
    entry_side=-1,
)

QUEUE_ZONE = ZoneSpec(
    id="zone-queue",
    name="Очередь раздачи",
    polygon=(Point(0.1, 0.6), Point(0.6, 0.6), Point(0.6, 0.95), Point(0.1, 0.95)),
    kind="queue",
    min_dwell_seconds=5.0,
)


def bbox_at(x: float, y: float, width: float = 0.08, height: float = 0.25):
    """Рамка человека, у которого «ноги» находятся в точке (x, y)."""
    return (x - width / 2, y - height, x + width / 2, y)


def walk(engine: CountingEngine, track_id: int, path, start: float = 1000.0, step: float = 0.2):
    """Провести трек по точкам пути, по кадру на точку."""
    results = []
    moment = start
    for x, y in path:
        results.append(
            engine.process_frame([TrackObservation(track_id, bbox_at(x, y))], moment)
        )
        moment += step
    return results


@pytest.fixture
def engine() -> CountingEngine:
    return CountingEngine(lines=[LINE], zones=[QUEUE_ZONE])


def test_walk_across_line_counts_one_entry(engine):
    walk(engine, 1, [(0.5, 0.75), (0.5, 0.68), (0.5, 0.60), (0.5, 0.40), (0.5, 0.30)])
    assert engine.entries_today == 1
    assert engine.exits_today == 0


def test_walk_back_counts_one_exit(engine):
    walk(engine, 1, [(0.5, 0.30), (0.5, 0.38), (0.5, 0.45), (0.5, 0.60), (0.5, 0.70)])
    assert engine.entries_today == 0
    assert engine.exits_today == 1


def test_person_who_turns_around_gives_one_entry_and_one_exit(engine):
    path = [
        (0.5, 0.75), (0.5, 0.68), (0.5, 0.60),
        (0.5, 0.40), (0.5, 0.35),   # вошёл
        (0.5, 0.42), (0.5, 0.60), (0.5, 0.72),  # развернулся и вышел
    ]
    walk(engine, 1, path, step=0.6)
    assert engine.entries_today == 1
    assert engine.exits_today == 1


def test_jitter_on_the_line_does_not_produce_crossings(engine):
    # Дрожание рамки в мёртвой зоне вокруг линии: проходов быть не должно.
    path = [
        (0.5, 0.75), (0.5, 0.65), (0.5, 0.55),
        (0.5, 0.5005), (0.5, 0.4995), (0.5, 0.5008), (0.5, 0.4992), (0.5, 0.5002),
    ]
    walk(engine, 1, path)
    assert engine.entries_today == 0
    assert engine.exits_today == 0


def test_crossing_beyond_the_segment_is_not_counted(engine):
    # Человек прошёл правее конца линии: пересечена продолжающая прямая, а не отрезок.
    walk(engine, 1, [(0.95, 0.75), (0.95, 0.68), (0.95, 0.60), (0.95, 0.40), (0.95, 0.30)])
    assert engine.entries_today == 0
    assert engine.exits_today == 0


def test_track_that_appears_behind_the_line_is_not_counted(engine):
    # Трек появился уже за линией и стоит на месте: прохода не было.
    walk(engine, 1, [(0.5, 0.35), (0.5, 0.34), (0.5, 0.33), (0.5, 0.32)])
    assert engine.entries_today == 0
    assert engine.exits_today == 0
    # Но его последующий выход через линию засчитывается: стороны видны обе.
    walk(engine, 1, [(0.5, 0.45), (0.5, 0.60), (0.5, 0.70)], start=1001.0)
    assert engine.exits_today == 1


def test_unconfirmed_track_is_ignored():
    engine = CountingEngine(lines=[LINE], params=CountingParams(min_track_age_frames=5))
    walk(engine, 1, [(0.5, 0.60), (0.5, 0.40), (0.5, 0.30)])
    assert engine.entries_today == 0


def test_line_counts_parameter_limits_directions():
    line = LineSpec(
        id="line-in-only",
        name="Только входы",
        a=Point(0.2, 0.5),
        b=Point(0.8, 0.5),
        entry_side=-1,
        counts="in",
    )
    engine = CountingEngine(lines=[line])
    path = [
        (0.5, 0.75), (0.5, 0.68), (0.5, 0.60),
        (0.5, 0.40), (0.5, 0.35),
        (0.5, 0.45), (0.5, 0.60), (0.5, 0.72),
    ]
    walk(engine, 1, path, step=0.6)
    assert engine.entries_today == 1
    assert engine.exits_today == 0


def test_loop_boundary_resets_tracks_without_counting_exits(engine):
    walk(engine, 1, [(0.5, 0.75), (0.5, 0.68), (0.5, 0.60), (0.5, 0.40), (0.5, 0.30)])
    engine.start_new_loop()

    assert engine.previous_loop_entries == 1
    assert engine.previous_loop_exits == 0
    assert engine.loop_entries == 0
    assert engine.loop_number == 2
    assert engine.exits_today == 0

    # Новый круг: тот же номер трека появляется по другую сторону линии — это
    # не проход, а начало файла заново.
    walk(engine, 1, [(0.5, 0.70), (0.5, 0.72), (0.5, 0.74)], start=1100.0)
    assert engine.exits_today == 0
    assert engine.entries_today == 1  # с прошлого круга, счётчик суток не сбрасывается


def test_inside_now_never_goes_below_zero(engine):
    walk(engine, 1, [(0.5, 0.30), (0.5, 0.38), (0.5, 0.45), (0.5, 0.60), (0.5, 0.70)])
    result = walk(engine, 1, [(0.5, 0.75)], start=1002.0)[0]
    assert engine.exits_today == 1
    assert result.inside_now == 0


def test_queue_counts_only_after_minimum_dwell(engine):
    result_at_start = walk(engine, 7, [(0.3, 0.8)], start=2000.0)[0]
    assert result_at_start.queue_size == 0

    result_after_2s = walk(engine, 7, [(0.3, 0.8)], start=2002.0)[0]
    assert result_after_2s.queue_size == 0

    result_after_6s = walk(engine, 7, [(0.3, 0.8)], start=2006.0)[0]
    assert result_after_6s.queue_size == 1
    assert result_after_6s.avg_wait_seconds == pytest.approx(6.0)
    assert result_after_6s.objects[0].state == "queue"


def test_completed_wait_is_recorded_when_person_leaves_zone(engine):
    walk(engine, 7, [(0.3, 0.8)], start=2000.0)
    walk(engine, 7, [(0.3, 0.8)], start=2008.0)
    result = walk(engine, 7, [(0.3, 0.30)], start=2010.0)[0]

    assert len(result.completed_waits) == 1
    wait = result.completed_waits[0]
    assert wait.zone_id == "zone-queue"
    assert wait.seconds == pytest.approx(10.0)


def test_wait_survives_track_id_change_inside_zone(engine):
    walk(engine, 7, [(0.3, 0.8)], start=2000.0)
    walk(engine, 7, [(0.3, 0.8)], start=2004.0)

    # Трек потерян (трекер выдал новый номер), человек остался на месте.
    engine.process_frame([], 2007.0)
    result = engine.process_frame([TrackObservation(8, bbox_at(0.31, 0.8))], 2008.0)

    # Ожидание продолжилось с прежнего момента, а не началось заново.
    assert result.queue_size == 1
    assert result.avg_wait_seconds == pytest.approx(8.0)


def test_far_away_new_track_does_not_inherit_wait(engine):
    walk(engine, 7, [(0.3, 0.8)], start=2000.0)
    engine.process_frame([], 2007.0)
    result = engine.process_frame([TrackObservation(9, bbox_at(0.55, 0.92))], 2008.0)
    assert result.queue_size == 0


def test_reset_tracks_forgets_wait_in_progress(engine):
    # Человек стоит в очереди, потом компьютер «спит» 20 минут.
    walk(engine, 7, [(0.3, 0.8)], start=2000.0)
    walk(engine, 7, [(0.3, 0.8)], start=2004.0)
    engine.reset_tracks()

    # После перерыва тот же номер трека — это уже начало нового наблюдения.
    walk(engine, 7, [(0.3, 0.8)], start=3200.0)
    result = walk(engine, 7, [(0.3, 0.30)], start=3207.0)[0]

    # Ожидание — 7 секунд после перерыва, а не 20 минут вместе со сном.
    assert [wait.seconds for wait in result.completed_waits] == [pytest.approx(7.0)]


def test_reset_tracks_keeps_counters_and_prevents_false_crossing(engine):
    walk(engine, 1, [(0.5, 0.75), (0.5, 0.68), (0.5, 0.60), (0.5, 0.40), (0.5, 0.30)])
    assert engine.entries_today == 1
    engine.reset_tracks()

    # Трекер после сброса снова выдаёт номер 1, но это другой человек по другую
    # сторону линии: прохода не было.
    walk(engine, 1, [(0.5, 0.70), (0.5, 0.72), (0.5, 0.74)], start=1100.0)
    assert engine.entries_today == 1
    assert engine.exits_today == 0
    assert engine.loop_number == 1  # в отличие от границы круга, круг не меняется


def test_inside_now_for_looped_file_is_counted_per_loop():
    engine = CountingEngine(lines=[LINE], zones=[QUEUE_ZONE], inside_per_loop=True)
    walk(engine, 1, [(0.5, 0.75), (0.5, 0.68), (0.5, 0.60), (0.5, 0.40), (0.5, 0.30)])
    assert engine.entries_today == 1
    engine.start_new_loop()

    # Новый круг: вошедший в прошлом круге уже не «внутри», а за сутки он учтён.
    result = walk(engine, 2, [(0.5, 0.70)], start=1100.0)[0]
    assert result.inside_now == 0
    assert result.entries_today == 1


def test_inside_now_for_live_camera_is_counted_per_day(engine):
    walk(engine, 1, [(0.5, 0.75), (0.5, 0.68), (0.5, 0.60), (0.5, 0.40), (0.5, 0.30)])
    result = walk(engine, 2, [(0.5, 0.70)], start=1100.0)[0]
    assert result.inside_now == 1

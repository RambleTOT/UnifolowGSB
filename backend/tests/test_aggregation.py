"""Тесты агрегации: интервалы, свёртки и срок хранения."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.cv.counting import CountingEngine, LineSpec, TrackObservation, ZoneSpec
from app.cv.geometry import Point
from app.models import Base, Bucket, BucketHour, BucketMinute, LineBucket, Wait, ZoneBucket
from app.services.aggregation import Aggregator, apply_retention, persist_bucket, rebuild_rollups

LINE = LineSpec(id="line-1", name="Проход", a=Point(0.2, 0.5), b=Point(0.8, 0.5), entry_side=-1)
ZONE = ZoneSpec(
    id="zone-1",
    name="Очередь",
    polygon=(Point(0.1, 0.6), Point(0.6, 0.6), Point(0.6, 0.95), Point(0.1, 0.95)),
    kind="queue",
    min_dwell_seconds=2.0,
)

BASE = datetime(2026, 9, 21, 12, 0, 0)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as active:
        yield active


def bbox_at(x: float, y: float):
    return (x - 0.04, y - 0.25, x + 0.04, y)


def test_aggregator_closes_interval_on_the_grid():
    engine = CountingEngine(lines=[LINE])
    aggregator = Aggregator(source_id=1, interval_seconds=5)

    finished = None
    for step in range(12):
        moment = BASE + timedelta(seconds=step)
        result = engine.process_frame(
            [TrackObservation(1, bbox_at(0.5, 0.7 - step * 0.05))], moment.timestamp()
        )
        payload = aggregator.add(result, moment, fps=12.0, latency_ms=30.0)
        if payload is not None and finished is None:
            finished = payload

    assert finished is not None
    # Первый интервал закрывается ровно на границе сетки в пять секунд.
    assert finished.started_at == BASE
    assert finished.samples == 5
    assert finished.fps_avg == pytest.approx(12.0)
    assert finished.people_in_frame_avg == pytest.approx(1.0)


def test_aggregator_counts_crossings_and_zones():
    engine = CountingEngine(lines=[LINE], zones=[ZONE])
    aggregator = Aggregator(source_id=1, interval_seconds=60)

    for step in range(8):
        moment = BASE + timedelta(seconds=step)
        result = engine.process_frame(
            [TrackObservation(1, bbox_at(0.3, 0.8)), TrackObservation(2, bbox_at(0.5, 0.75 - step * 0.08))],
            moment.timestamp(),
        )
        aggregator.add(
            result,
            moment,
            zone_names={"zone-1": ("Очередь", "queue")},
            line_names={"line-1": "Проход"},
        )

    payload = aggregator.flush()
    assert payload is not None
    assert payload.entered == 1
    assert payload.lines[0]["entered"] == 1
    assert payload.zones[0]["zone_name"] == "Очередь"
    assert payload.zones[0]["people_max"] >= 1


def test_persist_bucket_writes_all_levels(session):
    engine = CountingEngine(lines=[LINE], zones=[ZONE])
    aggregator = Aggregator(source_id=1, interval_seconds=60)

    for step in range(10):
        moment = BASE + timedelta(seconds=step)
        result = engine.process_frame(
            [TrackObservation(1, bbox_at(0.3, 0.8)), TrackObservation(2, bbox_at(0.5, 0.78 - step * 0.07))],
            moment.timestamp(),
        )
        aggregator.add(result, moment, zone_names={"zone-1": ("Очередь", "queue")})

    # Человек ушёл из зоны: ожидание завершилось и должно попасть в базу.
    late = BASE + timedelta(seconds=11)
    result = engine.process_frame([TrackObservation(1, bbox_at(0.3, 0.2))], late.timestamp())
    aggregator.add(result, late, zone_names={"zone-1": ("Очередь", "queue")})

    persist_bucket(session, aggregator.flush())
    session.commit()

    assert session.scalar(select(func.count()).select_from(Bucket)) == 1
    assert session.scalar(select(func.count()).select_from(ZoneBucket)) == 1
    assert session.scalar(select(func.count()).select_from(LineBucket)) == 1
    # Ожиданий два: один человек стоял в зоне, второй прошёл через неё дольше
    # минимального порога в две секунды — оба ожидания завершились.
    assert session.scalar(select(func.count()).select_from(Wait)) == 2


def _add_bucket(session, minute: int, second: int, entered: int = 1, people: float = 2.0):
    session.add(
        Bucket(
            source_id=1,
            dataset="real",
            started_at=BASE + timedelta(minutes=minute, seconds=second),
            samples=60,
            people_in_frame_avg=people,
            people_in_frame_max=people + 1,
            people_in_zone_avg=people / 2,
            queue_avg=1.0,
            queue_max=3.0,
            entered=entered,
            exited=0,
            wait_sum_seconds=120.0,
            wait_count=2,
            fps_avg=12.0,
            latency_ms_avg=30.0,
            confidence_avg=0.8,
            health="online",
        )
    )


def test_rollup_builds_minutes_and_hours(session):
    for minute in range(3):
        for second in (0, 5, 10):
            _add_bucket(session, minute, second)
    session.commit()

    result = rebuild_rollups(session, now=BASE + timedelta(hours=2))
    session.commit()

    assert result["minutes"] == 3
    minutes = session.scalars(select(BucketMinute).order_by(BucketMinute.started_at)).all()
    assert [row.entered for row in minutes] == [3, 3, 3]
    # Средние взвешиваются по числу кадров, а не усредняются повторно.
    assert minutes[0].people_in_frame_avg == pytest.approx(2.0)
    assert minutes[0].samples == 180

    hours = session.scalars(select(BucketHour)).all()
    assert len(hours) == 1
    assert hours[0].entered == 9


def test_retention_removes_old_rows(session):
    session.add(
        Bucket(source_id=1, dataset="real", started_at=BASE - timedelta(days=40), samples=1)
    )
    _add_bucket(session, 0, 0)
    session.commit()

    removed = apply_retention(session, retention_days=30, now=BASE)
    session.commit()

    assert removed == 1
    remaining = session.scalars(select(Bucket)).all()
    assert len(remaining) == 1
    assert remaining[0].started_at == BASE

"""Тесты аналитики: периоды, сведение по источникам и показатели."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.timeutil import now_utc, start_of_day
from app.models import Base, BucketMinute, Source, Wait
from app.services import analytics
from app.services.analytics import build_metric, resolve_window


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as active:
        yield active


def test_period_windows_and_steps():
    moment = datetime(2026, 9, 21, 15, 30, 0)

    hour = resolve_window("hour", moment=moment)
    assert hour.start == moment - timedelta(hours=1)
    assert hour.step_seconds == 60
    # Сравнение — с тем же отрезком часом раньше.
    assert hour.previous_start == moment - timedelta(hours=2)
    assert hour.previous_end == moment - timedelta(hours=1)

    day = resolve_window("day", moment=moment)
    assert day.start == start_of_day(moment)
    assert day.step_seconds == 15 * 60
    # День сравнивается со вчерашним днём до того же часа, а не с вечером вчера.
    assert day.previous_start == day.start - timedelta(days=1)
    assert day.previous_end == day.end - timedelta(days=1)

    week = resolve_window("week", moment=moment)
    assert week.step_seconds == 3600

    month = resolve_window("month", moment=moment)
    assert month.step_seconds == 24 * 3600


def test_custom_range_picks_step_by_length():
    short = resolve_window("custom", "2026-09-21", "2026-09-21")
    assert short.step_seconds == 15 * 60  # одни сутки

    long = resolve_window("custom", "2026-08-01", "2026-09-21")
    assert long.step_seconds == 24 * 3600


def test_metric_separates_direction_and_meaning():
    # Рост очереди — это ухудшение, даже если стрелка вверх.
    queue = build_metric("queue_avg", "Очередь", 12.0, previous=8.0, unit="чел")
    assert queue["direction"] == "up"
    assert queue["meaning"] == "worse"

    # Рост пропускной способности — улучшение.
    throughput = build_metric("throughput", "Пропускная способность", 30.0, previous=20.0, unit="чел/мин")
    assert throughput["direction"] == "up"
    assert throughput["meaning"] == "better"

    # Рост числа входов сам по себе ничего не означает.
    entered = build_metric("entered", "Входы", 120.0, previous=90.0, unit="чел")
    assert entered["direction"] == "up"
    assert entered["meaning"] == "neutral"


def test_metric_without_previous_period_says_so():
    metric = build_metric("entered", "Входы", 10.0, unit="чел")
    assert metric["deltaPercent"] is None
    assert metric["direction"] == "flat"


def test_metric_keeps_missing_value_as_none_with_reason():
    metric = build_metric(
        "queue_avg", "Очередь", None, unit="чел", missing_reason="не задана зона очереди"
    )
    assert metric["value"] is None
    assert metric["missingReason"] == "не задана зона очереди"


def _add_minute(session, source_id, minute, *, entered=0, exited=0, queue=0.0, samples=720):
    session.add(
        BucketMinute(
            source_id=source_id,
            dataset="real",
            started_at=now_utc().replace(second=0, microsecond=0) - timedelta(minutes=minute),
            samples=samples,
            people_in_frame_avg=queue + 1,
            people_in_frame_max=queue + 2,
            people_in_zone_avg=queue,
            queue_avg=queue,
            queue_max=queue + 1,
            entered=entered,
            exited=exited,
            fps_avg=12.0,
            latency_ms_avg=30.0,
            confidence_avg=0.9,
            health="online",
        )
    )


def test_totals_sum_across_sources_and_average_waits_by_records(session):
    session.add(Source(id=1, name="Раздача", scope="canteen"))
    session.add(Source(id=2, name="КПП 1", scope="gate"))
    for minute in range(1, 10):
        _add_minute(session, 1, minute, entered=3, exited=1, queue=8.0)
        _add_minute(session, 2, minute, entered=5, exited=4, queue=2.0)

    # Ожидания сводятся по всем записям выборки, а не как среднее средних.
    for seconds in (60.0, 120.0, 600.0):
        session.add(
            Wait(source_id=1, dataset="real", zone_id="z", ended_at=now_utc() - timedelta(minutes=2), seconds=seconds)
        )
    session.commit()

    window = resolve_window("hour")
    sources = analytics.scope_sources(session, "all")
    totals = analytics.collect_totals(session, window, "real", sources)

    assert totals.entered == 72  # (3 + 5) × 9 интервалов
    assert totals.exited == 45
    assert round(totals.queue_avg, 1) == 5.0  # среднее по двум источникам
    assert round(totals.wait_avg, 1) == 4.3  # (60 + 120 + 600) / 3 секунд в минутах
    assert totals.sources_with_data == 2


def test_series_keeps_empty_slots(session):
    session.add(Source(id=1, name="Раздача", scope="canteen"))
    _add_minute(session, 1, 2, entered=4)
    session.commit()

    window = resolve_window("hour")
    series = analytics.build_series(
        session,
        window,
        "real",
        analytics.scope_sources(session, "all"),
        {"entered": lambda m: __import__("sqlalchemy").func.sum(m.entered)},
    )

    # Час по минутам: 60 точек плюс неполный интервал на границе периода.
    assert len(series) in (60, 61)
    # Провал в данных остаётся провалом: точки не сдвигаются и не выдумываются.
    filled = [point for point in series if point["entered"] is not None]
    assert len(filled) == 1
    assert filled[0]["entered"] == 4


def test_series_keeps_missing_aggregate_as_none(session):
    session.add(Source(id=1, name="Раздача", scope="canteen"))
    _add_minute(session, 1, 2, entered=4)
    session.commit()

    window = resolve_window("hour")
    from sqlalchemy import func

    series = analytics.build_series(
        session,
        window,
        "real",
        analytics.scope_sources(session, "all"),
        {
            "entered": lambda m: func.sum(m.entered),
            "waitMinutes": lambda m: func.sum(m.wait_sum_seconds)
            / func.nullif(func.sum(m.wait_count), 0)
            / 60.0,
        },
    )
    filled = [point for point in series if point["entered"] is not None]

    assert filled[0]["entered"] == 4
    # Завершённых ожиданий не было — это прочерк, а не ноль минут.
    assert filled[0]["waitMinutes"] is None


def test_peak_flow_finds_busiest_window(session):
    session.add(Source(id=1, name="КПП 1", scope="gate"))
    for minute in range(1, 30):
        _add_minute(session, 1, minute, entered=2, exited=1)
    _add_minute(session, 1, 5, entered=30, exited=10)
    session.commit()

    window = resolve_window("hour")
    peak = analytics.peak_flow(session, window, "real", [1], seconds=60)
    assert peak == 43.0  # самый загруженный минутный интервал


def test_incompleteness_counts_only_sources_that_can_give_data(session):
    from app.services.analytics import Totals, incompleteness

    working = Source(id=1, name="Столовая", scope="canteen", enabled=True, video_id=1)
    without_video = Source(id=2, name="Раздача", scope="canteen", enabled=True)
    disabled = Source(id=3, name="КПП 1", scope="gate", enabled=False, video_id=1)
    sources = [working, without_video, disabled]

    # Один источник с видео дал данные — помечать нечего.
    assert incompleteness(sources, Totals(sources_with_data=1)) is None

    # Данных нет вообще — это «нет данных», а не «неполные данные».
    assert incompleteness(sources, Totals(sources_with_data=0)) is None

    # Два источника с видео, данные дал один — вот это неполнота.
    second = Source(id=4, name="КПП 2", scope="gate", enabled=True, video_id=2)
    mark = incompleteness([working, second, without_video], Totals(sources_with_data=1))
    assert mark == {"counted": 1, "total": 2, "names": ["КПП 2"]}

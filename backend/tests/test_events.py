"""Тесты правил событий: эпизод, а не череда срабатываний."""

from datetime import datetime, timedelta

from app.services.aggregation import BucketPayload
from app.services.events import CloseEvent, EventEngine, OpenEvent, UpdateEvent
from app.services.settings import SystemSettings

BASE = datetime(2026, 9, 21, 12, 0, 0)


def settings(**overrides) -> SystemSettings:
    values = {
        "queue_threshold": 10,
        "wait_threshold_minutes": 5.0,
        "checkpoint_threshold_per_minute": 25,
        "event_min_duration_seconds": 15,
        "aggregation_seconds": 5,
    }
    values.update(overrides)
    base = SystemSettings()
    for key, value in values.items():
        setattr(base, key, value)
    return base


def bucket(step: int, *, queue: float = 0.0, entered: int = 0, waits: tuple[float, int] = (0.0, 0),
           health: str = "online") -> BucketPayload:
    return BucketPayload(
        source_id=1,
        dataset="real",
        started_at=BASE + timedelta(seconds=5 * step),
        samples=60,
        people_in_frame_avg=queue,
        people_in_frame_max=queue,
        people_in_zone_avg=queue,
        queue_avg=queue,
        queue_max=queue,
        entered=entered,
        exited=0,
        wait_sum_seconds=waits[0],
        wait_count=waits[1],
        fps_avg=12.0,
        latency_ms_avg=30.0,
        confidence_avg=0.8,
        health=health,
        loop_boundary=False,
    )


def run(engine: EventEngine, payloads):
    actions = []
    for payload in payloads:
        actions.extend(engine.observe(payload, "Раздача"))
    return actions


def test_event_opens_only_after_minimum_duration():
    engine = EventEngine(source_id=1, scope="canteen", settings=settings())

    # Порог превышен, но всего пять секунд — событие ещё не создаётся.
    early = run(engine, [bucket(0, queue=14), bucket(1, queue=14)])
    assert not any(isinstance(action, OpenEvent) for action in early)

    later = run(engine, [bucket(2, queue=14), bucket(3, queue=14)])
    opened = [action for action in later if isinstance(action, OpenEvent)]
    assert len(opened) == 1
    assert opened[0].type == "queue_spike"
    # Ровно 1,4 × порога — это ещё средний приоритет, выше — высокий.
    assert opened[0].severity == "medium"
    assert opened[0].started_at == BASE  # время начала — момент первого превышения


def test_severity_depends_on_how_far_the_threshold_is_exceeded():
    engine = EventEngine(source_id=1, scope="canteen", settings=settings())
    opened = [
        action
        for action in run(engine, [bucket(step, queue=15) for step in range(4)])
        if isinstance(action, OpenEvent)
    ]
    assert opened[0].severity == "high"


def test_single_event_per_episode():
    engine = EventEngine(source_id=1, scope="canteen", settings=settings())
    actions = run(engine, [bucket(step, queue=12) for step in range(12)])

    assert len([action for action in actions if isinstance(action, OpenEvent)]) == 1
    assert len([action for action in actions if isinstance(action, UpdateEvent)]) > 0
    assert not any(isinstance(action, CloseEvent) for action in actions)


def test_severity_grows_but_never_falls_back():
    engine = EventEngine(source_id=1, scope="canteen", settings=settings())
    run(engine, [bucket(step, queue=12) for step in range(5)])

    escalated = run(engine, [bucket(5, queue=25)])
    assert escalated[-1].severity == "critical"

    calmer = run(engine, [bucket(6, queue=11)])
    # Приоритет уже не понижается: эпизод всё ещё тот же.
    assert calmer[-1].severity == "critical"


def test_event_closes_with_hysteresis():
    engine = EventEngine(source_id=1, scope="canteen", settings=settings())
    run(engine, [bucket(step, queue=14) for step in range(5)])

    # Ровно у порога событие не закрывается: значение должно уйти ниже с запасом.
    at_threshold = run(engine, [bucket(step, queue=9.5) for step in range(5, 10)])
    assert not any(isinstance(action, CloseEvent) for action in at_threshold)

    below = run(engine, [bucket(step, queue=6) for step in range(10, 15)])
    assert any(isinstance(action, CloseEvent) for action in below)


def test_checkpoint_rule_counts_people_per_minute():
    engine = EventEngine(source_id=2, scope="gate", settings=settings())
    # Три человека за пятисекундный интервал — это 36 человек в минуту.
    actions = run(engine, [bucket(step, entered=3) for step in range(5)])
    opened = [action for action in actions if isinstance(action, OpenEvent)]

    assert len(opened) == 1
    assert opened[0].type == "checkpoint_overload"
    assert opened[0].metric_value == 36.0


def test_queue_rule_does_not_fire_on_gates():
    engine = EventEngine(source_id=2, scope="gate", settings=settings())
    actions = run(engine, [bucket(step, entered=1) for step in range(6)])
    # Поток 12 чел/мин порога не превышает, других событий на КПП нет.
    assert actions == []


def test_source_problem_opens_and_closes_itself():
    engine = EventEngine(source_id=1, scope="canteen", settings=settings())
    opened = run(engine, [bucket(0, health="offline")])
    assert isinstance(opened[0], OpenEvent)
    assert opened[0].severity == "critical"

    restored = run(engine, [bucket(1, health="online")])
    assert any(isinstance(action, CloseEvent) for action in restored)


def test_wait_rule_uses_completed_waits():
    engine = EventEngine(source_id=1, scope="canteen", settings=settings())
    # Два завершённых ожидания по семь минут.
    actions = run(engine, [bucket(step, waits=(840.0, 2)) for step in range(5)])
    opened = [action for action in actions if isinstance(action, OpenEvent)]

    assert len(opened) == 1
    assert opened[0].type == "slow_movement"
    assert round(opened[0].metric_value, 1) == 7.0


def test_source_problem_is_not_raised_while_the_source_warms_up():
    from dataclasses import replace

    engine = EventEngine(source_id=1, scope="gate", settings=settings())
    # Первые минуты после запуска модели грузятся и скорость проседает — это не сбой.
    warming = [replace(bucket(step, health="degraded"), warming=True) for step in range(20)]
    assert not any(isinstance(action, OpenEvent) for action in run(engine, warming))

    # После прогрева та же просадка — уже проблема источника.
    after = run(engine, [bucket(step, health="degraded") for step in range(20, 40)])
    assert any(isinstance(action, OpenEvent) and action.type == "camera_drop" for action in after)

"""Демо-данные.

Синтетическая история нужна, чтобы графики, журнал и отчёты можно было
показать и проверить, пока реальной истории мало (ТЗ, раздел 3.8). Демо-набор
живёт отдельным признаком на каждой записи и никогда не смешивается с реальным.

События демо-набора создаёт тот же `EventEngine` по тем же правилам: отдельной
логики «для демо» нет, иначе демонстрация показывала бы не тот продукт.
"""

from __future__ import annotations

import logging
import random
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.timeutil import floor_to, now_utc, to_site
from app.models import (
    DATASET_DEMO,
    Bucket,
    BucketHour,
    BucketMinute,
    Event,
    EventHistory,
    LineBucket,
    Source,
    Wait,
    ZoneBucket,
)
from app.services.aggregation import BucketPayload
from app.services.events import CloseEvent, EventEngine, OpenEvent, UpdateEvent
from app.services.settings import SystemSettings, load_settings

LOGGER = logging.getLogger(__name__)

SEED = 20260921
HISTORY_DAYS = 30
# Поминутная история нужна для часа и дня; для недели и месяца хватает часовой.
MINUTE_DAYS = 3
FRAMES_PER_MINUTE = 720


def _canteen_shape(local: datetime) -> tuple[float, float, float]:
    """Столовая: завтрак, обеденный пик 11:30–14:00, тихий вечер."""
    minutes = local.hour * 60 + local.minute
    weekend = local.weekday() >= 5

    def bell(center: int, width: int, height: float) -> float:
        return height * pow(2.718281828, -((minutes - center) ** 2) / (2.0 * width * width))

    flow = bell(9 * 60, 45, 5) + bell(12 * 60 + 45, 70, 14) + bell(17 * 60, 60, 4)
    queue = bell(9 * 60, 40, 4) + bell(12 * 60 + 45, 65, 13) + bell(17 * 60, 55, 3)
    wait = bell(12 * 60 + 45, 60, 6.5) + bell(9 * 60, 40, 1.8)

    if weekend:
        flow, queue, wait = flow * 0.35, queue * 0.3, wait * 0.4
    return flow, queue, wait


def _gate_shape(local: datetime, reserve: bool) -> tuple[float, float, float]:
    """КПП: утренний вход, вечерний выход, ночью почти пусто."""
    minutes = local.hour * 60 + local.minute
    weekend = local.weekday() >= 5

    def bell(center: int, width: int, height: float) -> float:
        return height * pow(2.718281828, -((minutes - center) ** 2) / (2.0 * width * width))

    inbound = bell(9 * 60, 55, 16) + bell(13 * 60, 90, 5)
    outbound = bell(18 * 60, 70, 14) + bell(13 * 60, 90, 4)
    queue = bell(9 * 60, 50, 4) + bell(18 * 60, 60, 3)

    if reserve:
        inbound, outbound, queue = inbound * 0.55, outbound * 0.55, queue * 0.5
    if weekend:
        inbound, outbound, queue = inbound * 0.25, outbound * 0.25, queue * 0.2
    return inbound, outbound, queue


def _day_factor(local: datetime) -> float:
    """Ровный день на день не похож: небольшой разброс по суткам."""
    seed = local.toordinal() * 7919
    return 0.86 + ((seed % 29) / 29.0) * 0.28


def _minute_payload(
    source: Source, moment: datetime, rng: random.Random, anomaly: str | None
) -> BucketPayload:
    local = to_site(moment)
    factor = _day_factor(local)
    health = "online"

    if source.scope == "canteen":
        flow, queue, wait = _canteen_shape(local)
        flow, queue, wait = flow * factor, queue * factor, wait * factor
        entered = max(0, int(rng.gauss(flow / 2.2, 1.2)))
        exited = max(0, int(rng.gauss(flow / 2.4, 1.2)))
    else:
        inbound, outbound, queue = _gate_shape(local, source.name.endswith("2"))
        inbound, outbound, queue = inbound * factor, outbound * factor, queue * factor
        wait = 0.0
        entered = max(0, int(rng.gauss(inbound / 2.0, 1.4)))
        exited = max(0, int(rng.gauss(outbound / 2.0, 1.4)))

    queue_avg = max(0.0, rng.gauss(queue, 0.8))

    if anomaly == "queue" and source.scope == "canteen":
        queue_avg *= 2.1
        wait *= 2.2
    elif anomaly == "flow" and source.scope == "gate":
        entered = int(entered * 2.4)
    elif anomaly == "degraded":
        health = "degraded"
    elif anomaly == "offline":
        health = "offline"
        entered = exited = 0
        queue_avg = 0.0

    people = queue_avg + max(0.0, rng.gauss(2.0, 1.0)) + (entered + exited) * 0.4
    wait_count = int(queue_avg / 2) if wait > 0 else 0
    wait_sum = wait * 60.0 * wait_count * rng.uniform(0.85, 1.15)

    return BucketPayload(
        source_id=source.id,
        dataset=DATASET_DEMO,
        started_at=moment,
        samples=FRAMES_PER_MINUTE,
        people_in_frame_avg=round(people, 2),
        people_in_frame_max=round(people * 1.3, 2),
        people_in_zone_avg=round(people * 0.7, 2),
        queue_avg=round(queue_avg, 2),
        queue_max=round(queue_avg * rng.uniform(1.05, 1.35), 2),
        entered=entered,
        exited=exited,
        wait_sum_seconds=round(wait_sum, 1),
        wait_count=wait_count,
        fps_avg=12.0 if health == "online" else 6.0,
        latency_ms_avg=35.0 if health == "online" else 1800.0,
        confidence_avg=0.86,
        health=health,
        loop_boundary=False,
        zones=[
            {
                "zone_id": f"demo-queue-{source.id}",
                "zone_name": "Зона очереди",
                "zone_kind": "queue",
                "people_avg": round(queue_avg, 2),
                "people_max": round(queue_avg * 1.3, 2),
                "wait_sum_seconds": round(wait_sum, 1),
                "wait_count": wait_count,
            }
        ]
        if source.scope == "canteen"
        else [],
        lines=[
            {
                "line_id": f"demo-line-{source.id}",
                "line_name": "Основной проход",
                "entered": entered,
                "exited": exited,
            }
        ],
        waits=[],
    )


def _anomaly_plan(rng: random.Random, days: int) -> dict[str, list[tuple[datetime, str]]]:
    """Редкие, но заметные эпизоды: перегрузка, всплеск потока, потеря сигнала."""
    plan: dict[str, list[tuple[datetime, str]]] = {"queue": [], "flow": [], "degraded": [], "offline": []}
    start = floor_to(now_utc(), 3600) - timedelta(days=days)

    for day in range(days):
        day_start = start + timedelta(days=day)
        if rng.random() < 0.35:
            plan["queue"].append((day_start + timedelta(hours=12, minutes=rng.randint(0, 50)), "queue"))
        if rng.random() < 0.3:
            plan["flow"].append((day_start + timedelta(hours=9, minutes=rng.randint(0, 40)), "flow"))
        if rng.random() < 0.2:
            plan["degraded"].append((day_start + timedelta(hours=rng.randint(7, 20)), "degraded"))
        if rng.random() < 0.12:
            plan["offline"].append((day_start + timedelta(hours=rng.randint(7, 20)), "offline"))
    return plan


def _anomaly_at(plan: dict[str, list[tuple[datetime, str]]], moment: datetime) -> str | None:
    for kind, episodes in plan.items():
        for started, _ in episodes:
            length = timedelta(minutes=40 if kind in ("queue", "flow") else 25)
            if started <= moment < started + length:
                return kind
    return None


def _persist_minute(session: Session, payload: BucketPayload) -> None:
    session.add(
        BucketMinute(
            source_id=payload.source_id,
            dataset=payload.dataset,
            started_at=payload.started_at,
            samples=payload.samples,
            people_in_frame_avg=payload.people_in_frame_avg,
            people_in_frame_max=payload.people_in_frame_max,
            people_in_zone_avg=payload.people_in_zone_avg,
            queue_avg=payload.queue_avg,
            queue_max=payload.queue_max,
            entered=payload.entered,
            exited=payload.exited,
            wait_sum_seconds=payload.wait_sum_seconds,
            wait_count=payload.wait_count,
            fps_avg=payload.fps_avg,
            latency_ms_avg=payload.latency_ms_avg,
            confidence_avg=payload.confidence_avg,
            health=payload.health,
            loop_boundary=False,
        )
    )
    for zone in payload.zones:
        session.add(
            ZoneBucket(
                source_id=payload.source_id,
                dataset=payload.dataset,
                started_at=payload.started_at,
                zone_id=zone["zone_id"],
                zone_name=zone["zone_name"],
                zone_kind=zone["zone_kind"],
                people_avg=zone["people_avg"],
                people_max=zone["people_max"],
                wait_sum_seconds=zone["wait_sum_seconds"],
                wait_count=zone["wait_count"],
            )
        )
    for line in payload.lines:
        session.add(
            LineBucket(
                source_id=payload.source_id,
                dataset=payload.dataset,
                started_at=payload.started_at,
                line_id=line["line_id"],
                line_name=line["line_name"],
                entered=line["entered"],
                exited=line["exited"],
            )
        )


def _persist_hour(session: Session, payloads: list[BucketPayload], with_details: bool = True) -> None:
    """Часовая свёртка демо-набора: по ней строятся неделя и месяц.

    Интервалы по зонам и линиям пишутся только там, где нет поминутных: иначе
    один и тот же поток посчитался бы дважды.
    """
    if not payloads:
        return
    first = payloads[0]
    samples = sum(item.samples for item in payloads)
    session.add(
        BucketHour(
            source_id=first.source_id,
            dataset=first.dataset,
            started_at=floor_to(first.started_at, 3600),
            samples=samples,
            people_in_frame_avg=sum(i.people_in_frame_avg * i.samples for i in payloads) / samples,
            people_in_frame_max=max(i.people_in_frame_max for i in payloads),
            people_in_zone_avg=sum(i.people_in_zone_avg * i.samples for i in payloads) / samples,
            queue_avg=sum(i.queue_avg * i.samples for i in payloads) / samples,
            queue_max=max(i.queue_max for i in payloads),
            entered=sum(i.entered for i in payloads),
            exited=sum(i.exited for i in payloads),
            wait_sum_seconds=sum(i.wait_sum_seconds for i in payloads),
            wait_count=sum(i.wait_count for i in payloads),
            fps_avg=sum(i.fps_avg * i.samples for i in payloads) / samples,
            latency_ms_avg=sum(i.latency_ms_avg * i.samples for i in payloads) / samples,
            confidence_avg=sum(i.confidence_avg * i.samples for i in payloads) / samples,
            health=min((i.health for i in payloads), key=lambda value: {"online": 0, "degraded": 1, "offline": 2}[value])
            if payloads
            else "online",
            loop_boundary=False,
        )
    )
    if not with_details:
        return

    for zone_id in {zone["zone_id"] for item in payloads for zone in item.zones}:
        parts = [zone for item in payloads for zone in item.zones if zone["zone_id"] == zone_id]
        session.add(
            ZoneBucket(
                source_id=first.source_id,
                dataset=first.dataset,
                started_at=floor_to(first.started_at, 3600),
                zone_id=zone_id,
                zone_name=parts[0]["zone_name"],
                zone_kind=parts[0]["zone_kind"],
                people_avg=sum(part["people_avg"] for part in parts) / len(parts),
                people_max=max(part["people_max"] for part in parts),
                wait_sum_seconds=sum(part["wait_sum_seconds"] for part in parts),
                wait_count=sum(part["wait_count"] for part in parts),
            )
        )
    for line_id in {line["line_id"] for item in payloads for line in item.lines}:
        parts = [line for item in payloads for line in item.lines if line["line_id"] == line_id]
        session.add(
            LineBucket(
                source_id=first.source_id,
                dataset=first.dataset,
                started_at=floor_to(first.started_at, 3600),
                line_id=line_id,
                line_name=parts[0]["line_name"],
                entered=sum(part["entered"] for part in parts),
                exited=sum(part["exited"] for part in parts),
            )
        )


def _record_events(
    session: Session, source: Source, payloads: list[BucketPayload], settings: SystemSettings,
    bucket_seconds: int,
) -> None:
    """Прогнать синтетический ряд через те же правила событий."""
    engine = EventEngine(
        source_id=source.id,
        scope=source.scope,
        # Правила считают поток «в минуту» по длине интервала — подставляем её.
        settings=replace(settings, aggregation_seconds=bucket_seconds),
    )
    active: dict[str, Event] = {}

    for payload in payloads:
        for action in engine.observe(payload, source.name):
            if isinstance(action, OpenEvent):
                event = Event(
                    source_id=source.id,
                    dataset=DATASET_DEMO,
                    type=action.type,
                    severity=action.severity,
                    title=action.title,
                    description=action.description,
                    started_at=action.started_at,
                    ongoing=True,
                    status="open",
                    metric_value=action.metric_value,
                    peak_value=action.metric_value,
                    threshold=action.threshold,
                )
                session.add(event)
                active[action.type] = event
            elif isinstance(action, UpdateEvent):
                event = active.get(action.type)
                if event is not None:
                    event.peak_value = max(event.peak_value, action.peak_value)
                    event.metric_value = action.metric_value
                    event.severity = action.severity
            elif isinstance(action, CloseEvent):
                event = active.pop(action.type, None)
                if event is not None:
                    event.ongoing = False
                    event.ended_at = action.ended_at


def clear(session: Session) -> None:
    """Убрать демо-набор целиком: реальные данные не трогаются."""
    for model in (BucketMinute, BucketHour, Bucket, ZoneBucket, LineBucket):
        session.execute(delete(model).where(model.dataset == DATASET_DEMO))
    session.execute(delete(Wait).where(Wait.dataset == DATASET_DEMO))
    demo_events = session.scalars(select(Event.id).where(Event.dataset == DATASET_DEMO)).all()
    if demo_events:
        session.execute(delete(EventHistory).where(EventHistory.event_id.in_(demo_events)))
    session.execute(delete(Event).where(Event.dataset == DATASET_DEMO))


def has_demo_data(session: Session) -> bool:
    return bool(
        session.scalar(
            select(func.count()).select_from(BucketHour).where(BucketHour.dataset == DATASET_DEMO)
        )
    )


def generate(session: Session, days: int = HISTORY_DAYS) -> dict[str, int]:
    """Собрать демо-историю за последние 30 суток по всем источникам."""
    clear(session)

    settings = load_settings(session)
    sources = list(session.scalars(select(Source).where(Source.deleted_at.is_(None))))
    if not sources:
        return {"sources": 0, "minutes": 0, "hours": 0}

    rng = random.Random(SEED)
    end = floor_to(now_utc(), 60)
    start = end - timedelta(days=days)
    minute_start = end - timedelta(days=MINUTE_DAYS)

    minutes = hours = 0
    for source in sources:
        plan = _anomaly_plan(rng, days)
        hour_events: list[BucketPayload] = []
        minute_events: list[BucketPayload] = []

        cursor = start
        hour_bucket: list[BucketPayload] = []
        while cursor < end:
            payload = _minute_payload(source, cursor, rng, _anomaly_at(plan, cursor))
            hour_bucket.append(payload)

            if cursor >= minute_start:
                _persist_minute(session, payload)
                minute_events.append(payload)
                minutes += 1

            cursor += timedelta(minutes=1)

            if cursor.minute == 0 and hour_bucket:
                _persist_hour(
                    session, hour_bucket, with_details=hour_bucket[0].started_at < minute_start
                )
                hour_events.append(_hour_summary(hour_bucket))
                hour_bucket = []
                hours += 1

        if hour_bucket:
            _persist_hour(
                session, hour_bucket, with_details=hour_bucket[0].started_at < minute_start
            )
            hour_events.append(_hour_summary(hour_bucket))
            hours += 1

        # За старую историю события собираем по часовым интервалам, за свежие
        # трое суток — по минутным: так эпизоды ближе к правде.
        old_hours = [item for item in hour_events if item.started_at < minute_start]
        _record_events(session, source, old_hours, settings, 3600)
        _record_events(session, source, minute_events, settings, 60)
        _generate_waits(session, source, minute_events, rng)

    LOGGER.info(
        "Демо-данные собраны: источников %s, минутных интервалов %s, часовых %s",
        len(sources), minutes, hours,
    )
    return {"sources": len(sources), "minutes": minutes, "hours": hours}


def _hour_summary(payloads: list[BucketPayload]) -> BucketPayload:
    first = payloads[0]
    samples = sum(item.samples for item in payloads)
    return BucketPayload(
        source_id=first.source_id,
        dataset=DATASET_DEMO,
        started_at=floor_to(first.started_at, 3600),
        samples=samples,
        people_in_frame_avg=sum(i.people_in_frame_avg * i.samples for i in payloads) / samples,
        people_in_frame_max=max(i.people_in_frame_max for i in payloads),
        people_in_zone_avg=sum(i.people_in_zone_avg * i.samples for i in payloads) / samples,
        queue_avg=sum(i.queue_avg * i.samples for i in payloads) / samples,
        queue_max=max(i.queue_max for i in payloads),
        entered=sum(i.entered for i in payloads),
        exited=sum(i.exited for i in payloads),
        wait_sum_seconds=sum(i.wait_sum_seconds for i in payloads),
        wait_count=sum(i.wait_count for i in payloads),
        fps_avg=sum(i.fps_avg * i.samples for i in payloads) / samples,
        latency_ms_avg=sum(i.latency_ms_avg * i.samples for i in payloads) / samples,
        confidence_avg=sum(i.confidence_avg * i.samples for i in payloads) / samples,
        health=max((i.health for i in payloads), key=lambda value: {"online": 0, "degraded": 1, "offline": 2}[value]),
        loop_boundary=False,
        zones=[zone for item in payloads for zone in item.zones][:1],
        lines=[line for item in payloads for line in item.lines][:1],
    )


def _generate_waits(
    session: Session, source: Source, payloads: list[BucketPayload], rng: random.Random
) -> None:
    """Отдельные записи ожиданий: по ним считается 95-й процентиль."""
    for payload in payloads:
        if payload.wait_count <= 0:
            continue
        average = payload.wait_sum_seconds / payload.wait_count
        for _ in range(min(payload.wait_count, 6)):
            session.add(
                Wait(
                    source_id=source.id,
                    dataset=DATASET_DEMO,
                    zone_id=f"demo-queue-{source.id}",
                    ended_at=payload.started_at,
                    seconds=max(5.0, rng.gauss(average, average * 0.35)),
                )
            )


def top_up(session: Session) -> int:
    """Дописать демо-набор до текущей минуты, чтобы значения «сейчас» жили."""
    if not has_demo_data(session):
        return 0

    settings = load_settings(session)
    rng = random.Random(SEED + 1)
    now = floor_to(now_utc(), 60)
    added = 0

    for source in session.scalars(select(Source).where(Source.deleted_at.is_(None))):
        last = session.scalar(
            select(func.max(BucketMinute.started_at)).where(
                BucketMinute.source_id == source.id, BucketMinute.dataset == DATASET_DEMO
            )
        )
        if last is None:
            continue

        cursor = last + timedelta(minutes=1)
        fresh: list[BucketPayload] = []
        while cursor <= now:
            payload = _minute_payload(source, cursor, rng, None)
            _persist_minute(session, payload)
            fresh.append(payload)
            cursor += timedelta(minutes=1)
            added += 1

        if fresh:
            _record_events(session, source, fresh, settings, 60)

    return added

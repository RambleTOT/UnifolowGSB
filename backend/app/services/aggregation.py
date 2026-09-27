"""Накопление метрик в интервалы и свёртки.

Кадры приходят десятками в секунду, а аналитике нужны ряды за месяц. Поэтому
кадры складываются в короткие интервалы (по умолчанию 5 секунд), а из них
фоновая задача собирает минутные и часовые свёртки (задание, раздел 6.1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Integer, cast, delete, func, select
from sqlalchemy.orm import Session

from app.core.timeutil import floor_to, now_utc
from app.cv.counting import FrameResult
from app.models import (
    DATASET_REAL,
    Bucket,
    BucketHour,
    BucketMinute,
    LineBucket,
    Wait,
    ZoneBucket,
)

LOGGER = logging.getLogger(__name__)

HEALTH_ORDER = {"online": 0, "degraded": 1, "offline": 2}


@dataclass
class _ZoneAccumulator:
    name: str
    kind: str
    people_sum: float = 0.0
    people_max: float = 0.0
    wait_sum: float = 0.0
    wait_count: int = 0
    samples: int = 0


@dataclass
class _LineAccumulator:
    name: str
    entered: int = 0
    exited: int = 0


@dataclass
class BucketPayload:
    """Готовый интервал, который остаётся записать в базу."""

    source_id: int
    dataset: str
    started_at: datetime
    samples: int
    people_in_frame_avg: float
    people_in_frame_max: float
    people_in_zone_avg: float
    queue_avg: float
    queue_max: float
    entered: int
    exited: int
    wait_sum_seconds: float
    wait_count: int
    fps_avg: float
    latency_ms_avg: float
    confidence_avg: float
    health: str
    loop_boundary: bool
    zones: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)
    # Интервал из первых минут после запуска источника: модели грузятся, эфир
    # набирает буфер, скорость проседает. Это не проблема источника.
    warming: bool = False
    waits: list[dict] = field(default_factory=list)


class Aggregator:
    """Складывает кадры одного источника в интервалы."""

    def __init__(self, source_id: int, interval_seconds: int = 5, dataset: str = DATASET_REAL):
        self.source_id = source_id
        self.interval_seconds = max(1, interval_seconds)
        self.dataset = dataset
        self._started_at: datetime | None = None
        self._reset()

    def _reset(self, started_at: datetime | None = None) -> None:
        self._started_at = started_at
        self._samples = 0
        self._people_sum = 0.0
        self._people_max = 0.0
        self._zone_people_sum = 0.0
        self._queue_sum = 0.0
        self._queue_max = 0.0
        self._entered = 0
        self._exited = 0
        self._wait_sum = 0.0
        self._wait_count = 0
        self._fps_sum = 0.0
        self._latency_sum = 0.0
        self._confidence_sum = 0.0
        self._confidence_count = 0
        self._health = "online"
        self._warming = False
        self._loop_boundary = False
        self._zones: dict[str, _ZoneAccumulator] = {}
        self._lines: dict[str, _LineAccumulator] = {}
        self._waits: list[dict] = []

    def add(
        self,
        result: FrameResult,
        at: datetime,
        *,
        fps: float = 0.0,
        latency_ms: float = 0.0,
        health: str = "online",
        loop_boundary: bool = False,
        warming: bool = False,
        zone_names: dict[str, tuple[str, str]] | None = None,
        line_names: dict[str, str] | None = None,
    ) -> BucketPayload | None:
        """Добавить кадр. Если интервал закончился, вернуть его готовым."""
        slot = floor_to(at, self.interval_seconds)
        finished: BucketPayload | None = None

        if self._started_at is None:
            self._reset(slot)
        elif slot != self._started_at:
            finished = self.flush()
            self._reset(slot)

        self._samples += 1
        self._people_sum += result.people_in_frame
        self._people_max = max(self._people_max, result.people_in_frame)
        self._zone_people_sum += result.people_in_zone
        self._queue_sum += result.queue_size
        self._queue_max = max(self._queue_max, result.queue_size)
        self._fps_sum += fps
        self._latency_sum += latency_ms
        if HEALTH_ORDER.get(health, 0) > HEALTH_ORDER.get(self._health, 0):
            self._health = health
        self._loop_boundary = self._loop_boundary or loop_boundary
        self._warming = self._warming or warming

        confidences = [obj.confidence for obj in result.objects]
        if confidences:
            self._confidence_sum += sum(confidences) / len(confidences)
            self._confidence_count += 1

        for crossing in result.crossings:
            line = self._lines.setdefault(
                crossing.line_id,
                _LineAccumulator(name=(line_names or {}).get(crossing.line_id, crossing.line_name)),
            )
            if crossing.direction == "in":
                self._entered += 1
                line.entered += 1
            else:
                self._exited += 1
                line.exited += 1

        for zone_id, count in result.zone_counts.items():
            name, kind = (zone_names or {}).get(zone_id, (zone_id, "queue"))
            zone = self._zones.setdefault(zone_id, _ZoneAccumulator(name=name, kind=kind))
            zone.people_sum += count
            zone.people_max = max(zone.people_max, count)
            zone.samples += 1

        for wait in result.completed_waits:
            self._wait_sum += wait.seconds
            self._wait_count += 1
            zone = self._zones.get(wait.zone_id)
            if zone is None:
                name, kind = (zone_names or {}).get(wait.zone_id, (wait.zone_id, "queue"))
                zone = self._zones.setdefault(wait.zone_id, _ZoneAccumulator(name=name, kind=kind))
            zone.wait_sum += wait.seconds
            zone.wait_count += 1
            self._waits.append({"zone_id": wait.zone_id, "seconds": wait.seconds, "ended_at": at})

        return finished

    def flush(self) -> BucketPayload | None:
        """Закрыть текущий интервал: вызывается на границе и при остановке."""
        if self._started_at is None or self._samples == 0:
            return None

        samples = self._samples
        payload = BucketPayload(
            source_id=self.source_id,
            dataset=self.dataset,
            started_at=self._started_at,
            samples=samples,
            people_in_frame_avg=self._people_sum / samples,
            people_in_frame_max=self._people_max,
            people_in_zone_avg=self._zone_people_sum / samples,
            queue_avg=self._queue_sum / samples,
            queue_max=self._queue_max,
            entered=self._entered,
            exited=self._exited,
            wait_sum_seconds=self._wait_sum,
            wait_count=self._wait_count,
            fps_avg=self._fps_sum / samples,
            latency_ms_avg=self._latency_sum / samples,
            confidence_avg=(
                self._confidence_sum / self._confidence_count if self._confidence_count else 0.0
            ),
            health=self._health,
            loop_boundary=self._loop_boundary,
            warming=self._warming,
            zones=[
                {
                    "zone_id": zone_id,
                    "zone_name": zone.name,
                    "zone_kind": zone.kind,
                    "people_avg": zone.people_sum / zone.samples if zone.samples else 0.0,
                    "people_max": zone.people_max,
                    "wait_sum_seconds": zone.wait_sum,
                    "wait_count": zone.wait_count,
                }
                for zone_id, zone in self._zones.items()
            ],
            lines=[
                {
                    "line_id": line_id,
                    "line_name": line.name,
                    "entered": line.entered,
                    "exited": line.exited,
                }
                for line_id, line in self._lines.items()
            ],
            waits=list(self._waits),
        )
        self._reset()
        return payload


def persist_bucket(session: Session, payload: BucketPayload) -> None:
    """Записать готовый интервал: источник, его зоны, линии и ожидания."""
    session.add(
        Bucket(
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
            loop_boundary=payload.loop_boundary,
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

    for wait in payload.waits:
        session.add(
            Wait(
                source_id=payload.source_id,
                dataset=payload.dataset,
                zone_id=wait["zone_id"],
                ended_at=wait["ended_at"],
                seconds=wait["seconds"],
            )
        )


def _rollup(session: Session, source_model, target_model, step: timedelta, until: datetime) -> int:
    """Собрать свёртку из более мелких интервалов за завершённые периоды."""
    seconds = int(step.total_seconds())
    # Группируем по началу периода: в SQLite это арифметика над epoch. Приведение
    # к целому обязательно — иначе деление останется дробным и каждый интервал
    # попадёт в свою группу.
    epoch = cast(func.strftime("%s", source_model.started_at), Integer)
    bucket_start = func.datetime(cast(epoch / seconds, Integer) * seconds, "unixepoch")

    latest = session.scalar(select(func.max(target_model.started_at)))
    query = (
        select(
            source_model.source_id,
            source_model.dataset,
            bucket_start.label("started_at"),
            func.sum(source_model.samples).label("samples"),
            func.sum(source_model.people_in_frame_avg * source_model.samples).label("people_sum"),
            func.max(source_model.people_in_frame_max).label("people_max"),
            func.sum(source_model.people_in_zone_avg * source_model.samples).label("zone_sum"),
            func.sum(source_model.queue_avg * source_model.samples).label("queue_sum"),
            func.max(source_model.queue_max).label("queue_max"),
            func.sum(source_model.entered).label("entered"),
            func.sum(source_model.exited).label("exited"),
            func.sum(source_model.wait_sum_seconds).label("wait_sum"),
            func.sum(source_model.wait_count).label("wait_count"),
            func.sum(source_model.fps_avg * source_model.samples).label("fps_sum"),
            func.sum(source_model.latency_ms_avg * source_model.samples).label("latency_sum"),
            func.sum(source_model.confidence_avg * source_model.samples).label("confidence_sum"),
            func.max(source_model.loop_boundary).label("loop_boundary"),
        )
        .where(source_model.started_at < until)
        .group_by(source_model.source_id, source_model.dataset, bucket_start)
    )
    if latest is not None:
        query = query.where(source_model.started_at >= latest)

    rows = session.execute(query).all()
    if not rows:
        return 0

    starts = [datetime.fromisoformat(row.started_at) for row in rows]
    session.execute(
        delete(target_model).where(
            target_model.started_at.in_(starts),
        )
    )

    for row, started_at in zip(rows, starts):
        samples = row.samples or 1
        session.add(
            target_model(
                source_id=row.source_id,
                dataset=row.dataset,
                started_at=started_at,
                samples=row.samples or 0,
                people_in_frame_avg=(row.people_sum or 0) / samples,
                people_in_frame_max=row.people_max or 0,
                people_in_zone_avg=(row.zone_sum or 0) / samples,
                queue_avg=(row.queue_sum or 0) / samples,
                queue_max=row.queue_max or 0,
                entered=row.entered or 0,
                exited=row.exited or 0,
                wait_sum_seconds=row.wait_sum or 0,
                wait_count=row.wait_count or 0,
                fps_avg=(row.fps_sum or 0) / samples,
                latency_ms_avg=(row.latency_sum or 0) / samples,
                confidence_avg=(row.confidence_sum or 0) / samples,
                health="online",
                loop_boundary=bool(row.loop_boundary),
            )
        )
    return len(rows)


def rebuild_rollups(session: Session, now: datetime | None = None) -> dict[str, int]:
    """Обновить минутные и часовые свёртки за завершённые периоды."""
    moment = now or now_utc()
    minutes = _rollup(session, Bucket, BucketMinute, timedelta(minutes=1), floor_to(moment, 60))
    hours = _rollup(session, BucketMinute, BucketHour, timedelta(hours=1), floor_to(moment, 3600))
    return {"minutes": minutes, "hours": hours}


def apply_retention(session: Session, retention_days: int, now: datetime | None = None) -> int:
    """Удалить данные старше срока хранения из Настроек."""
    limit = (now or now_utc()) - timedelta(days=retention_days)
    removed = 0
    for model in (Bucket, BucketMinute, BucketHour, ZoneBucket, LineBucket):
        removed += session.execute(delete(model).where(model.started_at < limit)).rowcount or 0
    removed += session.execute(delete(Wait).where(Wait.ended_at < limit)).rowcount or 0
    if removed:
        LOGGER.info("Хранение: удалено %s записей старше %s", removed, limit)
    return removed

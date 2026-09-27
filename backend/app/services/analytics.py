"""Аналитика: периоды, ряды, сведение по источникам и показатели.

Показатель отдаётся готовым (задание, раздел 6.1): значение, единица,
изменение, направление, оценка изменения и уровень считаются здесь, а не в
интерфейсе. Таблица «рост означает…» из ТЗ (раздел 3.5) живёт в одном месте —
в `MEANINGS` ниже.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Literal, Sequence

from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.orm import Session

from app.core.timeutil import floor_to, now_utc, start_of_day, to_site
from app.models import (
    DATASET_REAL,
    Bucket,
    BucketHour,
    BucketMinute,
    Event,
    LineBucket,
    Source,
    Wait,
    ZoneBucket,
)

LOGGER = logging.getLogger(__name__)

Period = Literal["hour", "day", "week", "month", "custom"]

MINUTE = 60
QUARTER = 15 * 60
HOUR = 3600
DAY = 24 * 3600

# Рост метрики: это лучше, хуже или само по себе ничего не значит.
MEANINGS: dict[str, str] = {
    "queue_avg": "worse",
    "queue_max": "worse",
    "wait_avg": "worse",
    "wait_p95": "worse",
    "latency": "worse",
    "events": "worse",
    "throughput": "better",
    "fps": "better",
    "confidence": "better",
    "people_in_frame": "neutral",
    "people_in_zone": "neutral",
    "entered": "neutral",
    "exited": "neutral",
    "inside_now": "neutral",
    "intensity": "neutral",
    "peak_load": "neutral",
}


@dataclass(frozen=True, slots=True)
class Window:
    """Период, с чем он сравнивается и с каким шагом строятся ряды."""

    period: Period
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    step_seconds: int

    @property
    def step_title(self) -> str:
        if self.step_seconds >= DAY:
            return "1 сутки"
        if self.step_seconds >= HOUR:
            return "1 час"
        if self.step_seconds >= QUARTER:
            return "15 минут"
        return "1 минута"


def resolve_window(
    period: str, start: str | None = None, end: str | None = None, moment: datetime | None = None
) -> Window:
    """Границы периода и шаг ряда по правилам ТЗ, раздел 3.6."""
    now = moment or now_utc()

    if period == "hour":
        begin, finish, step, shift = now - timedelta(hours=1), now, MINUTE, timedelta(hours=1)
    elif period == "week":
        begin, finish, step, shift = now - timedelta(days=7), now, HOUR, timedelta(days=7)
    elif period == "month":
        begin, finish, step, shift = now - timedelta(days=30), now, DAY, timedelta(days=30)
    elif period == "custom" and start and end:
        begin = datetime.fromisoformat(start)
        finish = datetime.fromisoformat(end) + timedelta(days=1)
        length = (finish - begin).total_seconds()
        step = MINUTE if length <= 3 * HOUR else QUARTER if length <= 2 * DAY else HOUR if length <= 14 * DAY else DAY
        shift = finish - begin
    else:
        # День: текущие сутки объекта с полуночи до сейчас.
        begin, finish, step, shift = start_of_day(now), now, QUARTER, timedelta(days=1)

    # Сравниваем с тем же отрезком прошлого периода: день — со вчерашним днём
    # до того же часа, неделя — с прошлой неделей (ТЗ, раздел 3.6). Сдвигать на
    # длину прошедшей части суток было бы сравнением с вечером вчера.
    return Window(
        period=period if period in ("hour", "day", "week", "month", "custom") else "day",
        start=begin,
        end=finish,
        previous_start=begin - shift,
        previous_end=finish - shift,
        step_seconds=step,
    )


def _model_for(step_seconds: int):
    """Из какого уровня свёрток брать данные для заданного шага."""
    if step_seconds >= HOUR:
        return BucketHour
    if step_seconds >= MINUTE:
        return BucketMinute
    return Bucket


def scope_sources(session: Session, scope: str, source_ids: Sequence[int] | None = None) -> list[Source]:
    query = select(Source).order_by(Source.id)
    if scope in ("canteen", "gate"):
        query = query.where(Source.scope == scope)
    if source_ids:
        query = query.where(Source.id.in_(source_ids))
    return list(session.scalars(query))


def _bucket_key(column, step_seconds: int):
    epoch = cast(func.strftime("%s", column), Integer)
    return func.datetime(cast(epoch / step_seconds, Integer) * step_seconds, "unixepoch")


@dataclass(frozen=True, slots=True)
class Totals:
    """Сводные значения за период по выбранным источникам."""

    entered: int = 0
    exited: int = 0
    people_in_frame: float | None = None
    people_in_zone: float | None = None
    queue_avg: float | None = None
    queue_max: float | None = None
    wait_avg: float | None = None
    wait_p95: float | None = None
    intensity: float | None = None
    throughput_max: float | None = None
    samples: int = 0
    sources_with_data: int = 0


def collect_totals(
    session: Session, window: Window, dataset: str, sources: Sequence[Source]
) -> Totals:
    if not sources:
        return Totals()

    ids = [source.id for source in sources]
    model = _model_for(window.step_seconds)

    row = session.execute(
        select(
            func.sum(model.entered),
            func.sum(model.exited),
            func.sum(model.people_in_frame_avg * model.samples),
            func.sum(model.people_in_zone_avg * model.samples),
            func.sum(model.queue_avg * model.samples),
            func.max(model.queue_max),
            func.sum(model.samples),
            func.count(func.distinct(model.source_id)),
        ).where(
            model.source_id.in_(ids),
            model.dataset == dataset,
            model.started_at >= window.start,
            model.started_at < window.end,
        )
    ).one()

    samples = int(row[6] or 0)
    if samples == 0:
        return Totals(sources_with_data=int(row[7] or 0))

    waits = list(
        session.scalars(
            select(Wait.seconds).where(
                Wait.source_id.in_(ids),
                Wait.dataset == dataset,
                Wait.ended_at >= window.start,
                Wait.ended_at < window.end,
            )
        )
    )

    minutes = max(1.0, (window.end - window.start).total_seconds() / 60.0)
    entered = int(row[0] or 0)
    exited = int(row[1] or 0)

    return Totals(
        entered=entered,
        exited=exited,
        people_in_frame=(row[2] or 0) / samples,
        people_in_zone=(row[3] or 0) / samples,
        queue_avg=(row[4] or 0) / samples,
        queue_max=row[5],
        # Ожидание сводится по всем ожиданиям выборки, а не как среднее средних.
        wait_avg=(sum(waits) / len(waits) / 60.0) if waits else None,
        wait_p95=(percentile(waits, 95) / 60.0) if waits else None,
        intensity=(entered + exited) / minutes,
        throughput_max=_peak_per_minute(session, window, dataset, ids),
        samples=samples,
        sources_with_data=int(row[7] or 0),
    )


def percentile(values: Iterable[float], share: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(round((share / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def peak_flow(
    session: Session, window: Window, dataset: str, ids: Sequence[int], seconds: int = MINUTE
) -> float | None:
    """Наибольший поток за окно заданной длины внутри периода.

    Пиковая нагрузка считается «за любые N минут подряд» (ТЗ, раздел 3.2),
    поэтому окна нарезаются по сетке и берётся самое загруженное.
    """
    if not ids:
        return None
    key = _bucket_key(BucketMinute.started_at, seconds)
    total = func.sum(BucketMinute.entered + BucketMinute.exited)
    row = session.execute(
        select(total)
        .where(
            BucketMinute.source_id.in_(ids),
            BucketMinute.dataset == dataset,
            BucketMinute.started_at >= window.start,
            BucketMinute.started_at < window.end,
        )
        .group_by(key)
        .order_by(total.desc())
        .limit(1)
    ).first()
    return float(row[0]) if row and row[0] is not None else None


def _peak_per_minute(
    session: Session, window: Window, dataset: str, ids: Sequence[int]
) -> float | None:
    return peak_flow(session, window, dataset, ids, MINUTE)


def build_metric(
    key: str,
    label: str,
    value: float | None,
    *,
    unit: str,
    previous: float | None = None,
    whole: bool = False,
    hint: str | None = None,
    level: str = "normal",
    missing_reason: str | None = None,
    incomplete: dict | None = None,
) -> dict[str, Any]:
    """Собрать показатель в едином формате (ТЗ, раздел 3.5)."""
    meaning = MEANINGS.get(key, "neutral")
    delta: float | None = None
    direction = "flat"
    change_meaning = "neutral"

    if value is not None and previous is not None and previous != 0:
        delta = (value - previous) / abs(previous) * 100.0
        if abs(delta) < 0.5:
            direction, change_meaning = "flat", "neutral"
        else:
            direction = "up" if delta > 0 else "down"
            if meaning == "neutral":
                change_meaning = "neutral"
            elif meaning == "worse":
                change_meaning = "worse" if delta > 0 else "better"
            else:
                change_meaning = "better" if delta > 0 else "worse"

    return {
        "key": key,
        "label": label,
        "value": None if value is None else (round(value) if whole else round(value, 1)),
        "unit": unit,
        "deltaPercent": None if delta is None else round(delta, 1),
        "direction": direction,
        "meaning": change_meaning,
        "level": level,
        "hint": hint,
        "missingReason": missing_reason,
        "incomplete": incomplete,
    }


def build_series(
    session: Session,
    window: Window,
    dataset: str,
    sources: Sequence[Source],
    fields: dict[str, Any],
) -> list[dict[str, Any]]:
    """Ряд по времени: точки идут ровно по сетке шага, без пропусков."""
    if not sources:
        return []

    model = _model_for(window.step_seconds)
    key = _bucket_key(model.started_at, window.step_seconds)
    columns = [key.label("slot"), func.sum(model.samples).label("samples")]
    names = list(fields)
    columns.extend(expression(model).label(name) for name, expression in fields.items())

    rows = session.execute(
        select(*columns)
        .where(
            model.source_id.in_([source.id for source in sources]),
            model.dataset == dataset,
            model.started_at >= window.start,
            model.started_at < window.end,
        )
        .group_by(key)
        .order_by(key)
    ).all()

    points: dict[str, dict[str, Any]] = {}
    for row in rows:
        mapping = row._mapping
        samples = int(mapping["samples"] or 0) or 1
        point: dict[str, Any] = {"at": mapping["slot"], "samples": samples}
        for name in names:
            raw = mapping[name]
            # Ноль означает «посчитали, ничего не было», поэтому отсутствующее
            # значение остаётся пустым: например, ожидание там, где никто не
            # достоял до порога (ТЗ, раздел 3.7).
            point[name] = float(raw) if raw is not None else None
        points[mapping["slot"]] = point

    # Пустые интервалы тоже должны быть на графике: провал в данных — это факт,
    # а не повод сдвинуть точки.
    result: list[dict[str, Any]] = []
    cursor = floor_to(window.start, window.step_seconds)
    while cursor < window.end:
        stamp = cursor.strftime("%Y-%m-%d %H:%M:%S")
        point = points.get(stamp)
        if point is None:
            point = {"at": stamp, "samples": 0}
            for name in names:
                point[name] = None
        result.append(point)
        cursor += timedelta(seconds=window.step_seconds)
    return result


def weighted(column, model):
    """Среднее, взвешенное по числу кадров: иначе редкие интервалы перевесят."""
    return func.sum(column * model.samples) / func.nullif(func.sum(model.samples), 0)


def zone_comparison(
    session: Session, window: Window, dataset: str, sources: Sequence[Source]
) -> list[dict[str, Any]]:
    """Сравнение зон очереди всех источников выборки."""
    if not sources:
        return []

    rows = session.execute(
        select(
            ZoneBucket.source_id,
            ZoneBucket.zone_id,
            func.max(ZoneBucket.zone_name),
            func.avg(ZoneBucket.people_avg),
            func.max(ZoneBucket.people_max),
            func.sum(ZoneBucket.wait_sum_seconds),
            func.sum(ZoneBucket.wait_count),
        )
        .where(
            ZoneBucket.source_id.in_([source.id for source in sources]),
            ZoneBucket.dataset == dataset,
            ZoneBucket.zone_kind == "queue",
            ZoneBucket.started_at >= window.start,
            ZoneBucket.started_at < window.end,
        )
        .group_by(ZoneBucket.source_id, ZoneBucket.zone_id)
    ).all()

    names = {source.id: source.name for source in sources}
    result = []
    for source_id, zone_id, zone_name, people_avg, people_max, wait_sum, wait_count in rows:
        result.append(
            {
                "sourceId": source_id,
                "sourceName": names.get(source_id, ""),
                "zoneId": zone_id,
                "name": zone_name or zone_id,
                "queueAvg": round(float(people_avg or 0), 1),
                "queueMax": round(float(people_max or 0), 1),
                "waitAvgMinutes": round(float(wait_sum or 0) / float(wait_count) / 60.0, 1)
                if wait_count
                else None,
            }
        )
    return sorted(result, key=lambda item: item["waitAvgMinutes"] or 0, reverse=True)


def line_comparison(
    session: Session, window: Window, dataset: str, sources: Sequence[Source]
) -> list[dict[str, Any]]:
    """Сравнение контрольных линий: какой проход берёт на себя поток."""
    if not sources:
        return []

    rows = session.execute(
        select(
            LineBucket.source_id,
            LineBucket.line_id,
            func.max(LineBucket.line_name),
            func.sum(LineBucket.entered),
            func.sum(LineBucket.exited),
        )
        .where(
            LineBucket.source_id.in_([source.id for source in sources]),
            LineBucket.dataset == dataset,
            LineBucket.started_at >= window.start,
            LineBucket.started_at < window.end,
        )
        .group_by(LineBucket.source_id, LineBucket.line_id)
    ).all()

    names = {source.id: source.name for source in sources}
    result = [
        {
            "sourceId": source_id,
            "sourceName": names.get(source_id, ""),
            "lineId": line_id,
            "name": line_name or line_id,
            "entered": int(entered or 0),
            "exited": int(exited or 0),
            "total": int(entered or 0) + int(exited or 0),
        }
        for source_id, line_id, line_name, entered, exited in rows
    ]
    return sorted(result, key=lambda item: item["total"], reverse=True)


def source_load(
    session: Session, window: Window, dataset: str, sources: Sequence[Source]
) -> list[dict[str, Any]]:
    """Нагрузка по источникам: кто из них загружен сильнее."""
    if not sources:
        return []

    model = _model_for(window.step_seconds)
    rows = session.execute(
        select(
            model.source_id,
            func.sum(model.entered + model.exited),
            weighted(model.queue_avg, model),
            weighted(model.people_in_frame_avg, model),
        )
        .where(
            model.source_id.in_([source.id for source in sources]),
            model.dataset == dataset,
            model.started_at >= window.start,
            model.started_at < window.end,
        )
        .group_by(model.source_id)
    ).all()

    names = {source.id: source for source in sources}
    result = []
    for source_id, flow, queue_avg, people_avg in rows:
        source = names.get(source_id)
        result.append(
            {
                "sourceId": source_id,
                "name": source.name if source else "",
                "scope": source.scope if source else None,
                "flow": int(flow or 0),
                "queueAvg": round(float(queue_avg or 0), 1),
                "peopleAvg": round(float(people_avg or 0), 1),
            }
        )
    return sorted(result, key=lambda item: item["flow"], reverse=True)


def heatmap(
    session: Session, dataset: str, sources: Sequence[Source], days: int = 28
) -> dict[str, Any]:
    """Тепловая карта нагрузки по дням недели и часам."""
    if not sources:
        return {"cells": [], "daysCollected": 0, "daysRequired": 7}

    since = now_utc() - timedelta(days=days)
    rows = session.execute(
        select(
            BucketHour.started_at,
            func.sum(BucketHour.entered + BucketHour.exited),
            weighted(BucketHour.queue_avg, BucketHour),
        )
        .where(
            BucketHour.source_id.in_([source.id for source in sources]),
            BucketHour.dataset == dataset,
            BucketHour.started_at >= since,
        )
        .group_by(BucketHour.started_at)
    ).all()

    cells: dict[tuple[int, int], dict[str, float]] = {}
    seen_days: set[str] = set()
    for started_at, flow, queue_avg in rows:
        local = to_site(started_at)
        seen_days.add(local.strftime("%Y-%m-%d"))
        key = (local.weekday(), local.hour)
        cell = cells.setdefault(key, {"flow": 0.0, "queue": 0.0, "count": 0.0})
        cell["flow"] += float(flow or 0)
        cell["queue"] += float(queue_avg or 0)
        cell["count"] += 1

    payload = [
        {
            "weekday": weekday,
            "hour": hour,
            "flow": round(values["flow"] / max(1.0, values["count"]), 1),
            "queue": round(values["queue"] / max(1.0, values["count"]), 1),
        }
        for (weekday, hour), values in sorted(cells.items())
    ]
    return {"cells": payload, "daysCollected": len(seen_days), "daysRequired": 7}


def hourly_profile(
    session: Session, dataset: str, sources: Sequence[Source], days: int = 28
) -> dict[str, Any]:
    """Типовая кривая дня: по ней планируют смены."""
    if not sources:
        return {"points": [], "daysCollected": 0, "daysRequired": 7}

    since = now_utc() - timedelta(days=days)
    rows = session.execute(
        select(BucketHour.started_at, func.sum(BucketHour.entered + BucketHour.exited))
        .where(
            BucketHour.source_id.in_([source.id for source in sources]),
            BucketHour.dataset == dataset,
            BucketHour.started_at >= since,
        )
        .group_by(BucketHour.started_at)
    ).all()

    buckets: dict[int, list[float]] = {hour: [] for hour in range(24)}
    seen_days: set[str] = set()
    for started_at, flow in rows:
        local = to_site(started_at)
        seen_days.add(local.strftime("%Y-%m-%d"))
        buckets[local.hour].append(float(flow or 0))

    points = [
        {
            "hour": hour,
            "flow": round(sum(values) / len(values), 1) if values else None,
        }
        for hour, values in buckets.items()
    ]
    return {"points": points, "daysCollected": len(seen_days), "daysRequired": 7}


def weekday_comparison(
    session: Session, dataset: str, sources: Sequence[Source]
) -> list[dict[str, Any]]:
    """Текущая неделя против типового профиля тех же дней недели."""
    if not sources:
        return []

    now = now_utc()
    week_start = start_of_day(now) - timedelta(days=now.weekday())
    baseline_start = week_start - timedelta(days=28)

    rows = session.execute(
        select(BucketHour.started_at, func.sum(BucketHour.entered + BucketHour.exited))
        .where(
            BucketHour.source_id.in_([source.id for source in sources]),
            BucketHour.dataset == dataset,
            BucketHour.started_at >= baseline_start,
        )
        .group_by(BucketHour.started_at)
    ).all()

    current: dict[int, float] = {}
    baseline: dict[int, list[float]] = {}
    for started_at, flow in rows:
        local = to_site(started_at)
        weekday = local.weekday()
        value = float(flow or 0)
        if started_at >= week_start:
            current[weekday] = current.get(weekday, 0.0) + value
        else:
            baseline.setdefault(weekday, []).append(value)

    titles = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    result = []
    for weekday in range(7):
        history = baseline.get(weekday, [])
        # Базовый профиль — сумма за сутки, усреднённая по неделям истории.
        weeks = max(1, len(history) // 24) if history else 0
        result.append(
            {
                "weekday": weekday,
                "title": titles[weekday],
                "current": round(current.get(weekday, 0.0), 1) if weekday in current else None,
                "baseline": round(sum(history) / weeks, 1) if weeks else None,
            }
        )
    return result


def count_events(
    session: Session,
    window: Window,
    dataset: str,
    sources: Sequence[Source],
    types: Sequence[str] | None = None,
) -> int:
    if not sources:
        return 0
    query = select(func.count()).select_from(Event).where(
        Event.source_id.in_([source.id for source in sources]),
        Event.dataset == dataset,
        Event.started_at >= window.start,
        Event.started_at < window.end,
    )
    if types:
        query = query.where(Event.type.in_(types))
    return int(session.scalar(query) or 0)


def incompleteness(sources: Sequence[Source], totals: Totals) -> dict[str, Any] | None:
    """Если часть источников не дала данных, показатель помечается неполным.

    Когда данных нет вообще, помечать нечего: это не «неполные данные», а
    «данных за период нет», и об этом говорит сам показатель.
    """
    # В расчёт идут только те, кто вообще может дать данные: выключенный
    # источник и источник без видео или ссылки — это не «неполные данные» (ТЗ, 4.3).
    expected = [
        source
        for source in sources
        if source.enabled and (source.video_id is not None or (source.connection_type == "stream" and source.stream_url))
    ]
    if not expected or totals.sources_with_data == 0:
        return None
    if totals.sources_with_data >= len(expected):
        return None
    missing = [source.name for source in expected][totals.sources_with_data :]
    return {
        "counted": totals.sources_with_data,
        "total": len(expected),
        "names": missing,
    }


def level_for_queue(value: float | None, threshold: float) -> str:
    if value is None:
        return "normal"
    if value >= threshold:
        return "critical"
    if value >= threshold * 0.7:
        return "attention"
    return "normal"


def window_payload(window: Window) -> dict[str, Any]:
    return {
        "period": window.period,
        "from": window.start.isoformat(),
        "to": window.end.isoformat(),
        "previousFrom": window.previous_start.isoformat(),
        "previousTo": window.previous_end.isoformat(),
        "stepSeconds": window.step_seconds,
        "stepTitle": window.step_title,
    }

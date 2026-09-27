"""Аналитические разделы: Главная, Анализ очередей, Анализ КПП."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_session
from app.models import DATASET_REAL, Event, LineBucket, Source, User, ZoneBucket
from app.services import analytics
from app.services import sources as sources_service
from app.services.analytics import Window, build_metric, resolve_window, window_payload
from app.services.manager import runtime_manager
from app.services.settings import load_settings

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["analytics"])


def _dataset(user: User) -> str:
    """Реальные и демо-данные никогда не смешиваются (ТЗ, раздел 3.8)."""
    return user.dataset or DATASET_REAL


def _live_now(
    dataset: str, sources: list[Source], session: Session | None = None
) -> dict[str, float | None]:
    """Значения «сейчас».

    Для реальных данных это живая часть, для демо — последний интервал набора:
    иначе демонстрация встречала бы прочерками половину показателей.
    """
    if dataset != DATASET_REAL:
        return _demo_now(session, sources) if session is not None else {
            "peopleInZone": None,
            "queue": None,
            "insideNow": None,
        }

    people = queue = inside = 0
    seen = False
    for source in sources:
        snapshot = runtime_manager.snapshot(source.id)
        if snapshot is None:
            continue
        seen = True
        people += snapshot.people_in_zone
        queue += snapshot.queue_size
        inside += snapshot.inside_now
    if not seen:
        return {"peopleInZone": None, "queue": None, "insideNow": None}
    return {"peopleInZone": float(people), "queue": float(queue), "insideNow": float(inside)}


def _demo_now(session: Session, sources: list[Source]) -> dict[str, float | None]:
    from app.models import BucketMinute
    from app.core.timeutil import now_utc, start_of_day

    if not sources:
        return {"peopleInZone": None, "queue": None, "insideNow": None}

    ids = [source.id for source in sources]
    latest = session.scalar(
        select(func.max(BucketMinute.started_at)).where(
            BucketMinute.source_id.in_(ids), BucketMinute.dataset != DATASET_REAL
        )
    )
    if latest is None:
        return {"peopleInZone": None, "queue": None, "insideNow": None}

    row = session.execute(
        select(
            func.sum(BucketMinute.people_in_zone_avg),
            func.sum(BucketMinute.queue_avg),
        ).where(
            BucketMinute.source_id.in_(ids),
            BucketMinute.dataset != DATASET_REAL,
            BucketMinute.started_at == latest,
        )
    ).one()

    today = session.execute(
        select(func.sum(BucketMinute.entered), func.sum(BucketMinute.exited)).where(
            BucketMinute.source_id.in_(ids),
            BucketMinute.dataset != DATASET_REAL,
            BucketMinute.started_at >= start_of_day(now_utc()),
        )
    ).one()

    inside = max(0, int(today[0] or 0) - int(today[1] or 0))
    return {
        "peopleInZone": round(float(row[0] or 0), 1),
        "queue": round(float(row[1] or 0), 1),
        "insideNow": float(inside),
    }


def _has_queue_zones(session: Session, dataset: str, sources: list[Source], window: Window) -> bool:
    if any(
        zone.kind == "queue"
        for source in sources
        for zone in sources_service.get_markup(session, source.id).zones
    ):
        return True
    return bool(
        session.scalar(
            select(func.count())
            .select_from(ZoneBucket)
            .where(
                ZoneBucket.source_id.in_([source.id for source in sources]),
                ZoneBucket.dataset == dataset,
                ZoneBucket.zone_kind == "queue",
                ZoneBucket.started_at >= window.start,
            )
        )
    )


def _has_lines(session: Session, dataset: str, sources: list[Source], window: Window) -> bool:
    if any(sources_service.get_markup(session, source.id).lines for source in sources):
        return True
    return bool(
        session.scalar(
            select(func.count())
            .select_from(LineBucket)
            .where(
                LineBucket.source_id.in_([source.id for source in sources]),
                LineBucket.dataset == dataset,
                LineBucket.started_at >= window.start,
            )
        )
    )


def _event_cards(
    session: Session, dataset: str, sources: list[Source], window: Window, types=None, limit=8
) -> list[dict[str, Any]]:
    """События периода: сначала продолжающиеся, затем необработанные."""
    if not sources:
        return []
    query = (
        select(Event)
        .where(
            Event.source_id.in_([source.id for source in sources]),
            Event.dataset == dataset,
            Event.started_at >= window.start,
        )
        .order_by(Event.ongoing.desc(), Event.started_at.desc())
        .limit(limit)
    )
    if types:
        query = query.where(Event.type.in_(types))

    from app.schemas.views import event_view

    return [event_view(session, event) for event in session.scalars(query)]


@router.get("/dashboard")
def dashboard(
    period: str = Query(default="day"),
    scope: str = Query(default="all"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    dataset = _dataset(user)
    window = resolve_window(period, date_from, date_to)
    sources = analytics.scope_sources(session, scope)
    settings = load_settings(session)

    totals = analytics.collect_totals(session, window, dataset, sources)
    previous_window = Window(
        period=window.period,
        start=window.previous_start,
        end=window.previous_end,
        previous_start=window.previous_start,
        previous_end=window.previous_end,
        step_seconds=window.step_seconds,
    )
    previous = analytics.collect_totals(session, previous_window, dataset, sources)
    incomplete = analytics.incompleteness(sources, totals)
    live = _live_now(dataset, sources, session)

    model = analytics._model_for(window.step_seconds)
    flow_series = analytics.build_series(
        session,
        window,
        dataset,
        sources,
        {
            "peopleInZone": lambda m: analytics.weighted(m.people_in_zone_avg, m),
            "entered": lambda m: func.sum(m.entered),
            "exited": lambda m: func.sum(m.exited),
        },
    )
    queue_series = analytics.build_series(
        session,
        window,
        dataset,
        sources,
        {
            "queue": lambda m: analytics.weighted(m.queue_avg, m),
            "queueMax": lambda m: func.max(m.queue_max),
            "waitMinutes": lambda m: func.sum(m.wait_sum_seconds)
            / func.nullif(func.sum(m.wait_count), 0)
            / 60.0,
        },
    )

    load = analytics.source_load(session, window, dataset, sources)
    total_flow = sum(item["flow"] for item in load) or 1
    distribution = [
        {**item, "share": round(item["flow"] / total_flow * 100, 1)} for item in load
    ]

    queue_level = analytics.level_for_queue(totals.queue_avg, settings.queue_threshold)
    problems = [
        {
            "sourceId": source.id,
            "name": source.name,
            # Источник без видео — это «видео не назначено», а не «нет сигнала»:
            # разные состояния и разные действия пользователя.
            "status": sources_service.status_of(source),
            "readiness": sources_service.readiness_of(session, source),
            "error": source.last_error,
        }
        for source in sources
        if source.enabled
        and (source.status != "online" or not sources_service.has_signal_source(source))
    ]

    return {
        "window": window_payload(window),
        "dataset": dataset,
        "attention": {
            "events": _event_cards(session, dataset, sources, window),
            "sources": problems,
        },
        "metrics": [
            build_metric(
                "people_in_zone",
                "Людей в зоне сейчас",
                live["peopleInZone"],
                unit="чел",
                whole=True,
                hint="Люди внутри зон заполненности прямо сейчас",
                missing_reason=None if live["peopleInZone"] is not None else
                "живые данные доступны только в режиме реальных данных",
                incomplete=incomplete,
            ),
            build_metric(
                "entered",
                "Входы за период",
                float(totals.entered),
                previous=float(previous.entered),
                unit="чел",
                whole=True,
                hint="Пересечения контрольных линий в сторону входа",
                incomplete=incomplete,
            ),
            build_metric(
                "exited",
                "Выходы за период",
                float(totals.exited),
                previous=float(previous.exited),
                unit="чел",
                whole=True,
                incomplete=incomplete,
            ),
            build_metric(
                "queue_avg",
                "Средняя очередь",
                totals.queue_avg,
                previous=previous.queue_avg,
                unit="чел",
                level=queue_level,
                hint="Среднее число людей в зонах очереди за период",
                missing_reason=None if totals.queue_avg is not None else "не задана зона очереди",
                incomplete=incomplete,
            ),
            build_metric(
                "queue_max",
                "Максимальная очередь",
                totals.queue_max,
                previous=previous.queue_max,
                unit="чел",
                level=analytics.level_for_queue(totals.queue_max, settings.queue_threshold),
                missing_reason=None if totals.queue_max is not None else "не задана зона очереди",
                incomplete=incomplete,
            ),
            build_metric(
                "wait_avg",
                "Среднее ожидание",
                totals.wait_avg,
                previous=previous.wait_avg,
                unit="мин",
                level="critical"
                if (totals.wait_avg or 0) >= settings.wait_threshold_minutes
                else "normal",
                hint="Считается по завершённым ожиданиям в зонах очереди",
                missing_reason=None if totals.wait_avg is not None else "нет завершённых ожиданий",
                incomplete=incomplete,
            ),
        ],
        "flowSeries": flow_series,
        "queueSeries": queue_series,
        "thresholds": {
            "queue": settings.queue_threshold,
            "waitMinutes": settings.wait_threshold_minutes,
            "checkpointPerMinute": settings.checkpoint_threshold_per_minute,
        },
        "sourceLoad": load,
        "distribution": distribution,
        "heatmap": analytics.heatmap(session, dataset, sources),
        "hourlyProfile": analytics.hourly_profile(session, dataset, sources),
        "sourcesTotal": len(sources),
    }


@router.get("/analytics/queues")
def queues(
    period: str = Query(default="day"),
    scope: str = Query(default="all"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    dataset = _dataset(user)
    window = resolve_window(period, date_from, date_to)
    sources = analytics.scope_sources(session, scope)
    settings = load_settings(session)

    applicable = _has_queue_zones(session, dataset, sources, window)
    totals = analytics.collect_totals(session, window, dataset, sources)
    previous = analytics.collect_totals(
        session,
        Window(window.period, window.previous_start, window.previous_end, window.previous_start,
               window.previous_end, window.step_seconds),
        dataset,
        sources,
    )
    live = _live_now(dataset, sources, session)

    return {
        "window": window_payload(window),
        "dataset": dataset,
        "applicable": applicable,
        "notApplicableReason": None
        if applicable
        else (
            "В выбранном контуре нет зон очереди. Смените контур или разметьте зону очереди у источника."
        ),
        "metrics": [
            build_metric(
                "queue_now",
                "Очередь сейчас",
                live["queue"],
                unit="чел",
                whole=True,
                level=analytics.level_for_queue(live["queue"], settings.queue_threshold),
                missing_reason=None if live["queue"] is not None else "живые данные только для реальных данных",
            ),
            build_metric(
                "queue_max",
                "Пик очереди за период",
                totals.queue_max,
                previous=previous.queue_max,
                unit="чел",
                level=analytics.level_for_queue(totals.queue_max, settings.queue_threshold),
                missing_reason=None if totals.queue_max is not None else "не задана зона очереди",
            ),
            build_metric(
                "wait_avg",
                "Среднее ожидание",
                totals.wait_avg,
                previous=previous.wait_avg,
                unit="мин",
                level="critical"
                if (totals.wait_avg or 0) >= settings.wait_threshold_minutes
                else "normal",
                missing_reason=None if totals.wait_avg is not None else "нет завершённых ожиданий",
            ),
            build_metric(
                "wait_p95",
                "Ожидание, 95-й процентиль",
                totals.wait_p95,
                previous=previous.wait_p95,
                unit="мин",
                hint="Отсекает единичные выбросы: столько ждут самые неудачливые",
                missing_reason=None if totals.wait_p95 is not None else "нет завершённых ожиданий",
            ),
            build_metric(
                "events",
                "Событий очереди",
                float(
                    analytics.count_events(
                        session, window, dataset, sources, ["queue_spike", "slow_movement"]
                    )
                ),
                unit="шт",
                whole=True,
            ),
        ],
        "queueSeries": analytics.build_series(
            session,
            window,
            dataset,
            sources,
            {
                "queue": lambda m: analytics.weighted(m.queue_avg, m),
                "queueMax": lambda m: func.max(m.queue_max),
                "waitMinutes": lambda m: func.sum(m.wait_sum_seconds)
                / func.nullif(func.sum(m.wait_count), 0)
                / 60.0,
            },
        ),
        "zones": analytics.zone_comparison(session, window, dataset, sources),
        "heatmap": analytics.heatmap(session, dataset, sources),
        "events": _event_cards(
            session, dataset, sources, window, ["queue_spike", "slow_movement"], limit=50
        ),
        "thresholds": {
            "queue": settings.queue_threshold,
            "waitMinutes": settings.wait_threshold_minutes,
        },
    }


@router.get("/analytics/checkpoints")
def checkpoints(
    period: str = Query(default="day"),
    scope: str = Query(default="all"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    dataset = _dataset(user)
    window = resolve_window(period, date_from, date_to)
    # Раздел про проходные: если контур не выбран, показываем КПП.
    sources = analytics.scope_sources(session, scope if scope != "all" else "gate")
    settings = load_settings(session)

    applicable = _has_lines(session, dataset, sources, window)
    totals = analytics.collect_totals(session, window, dataset, sources)
    previous = analytics.collect_totals(
        session,
        Window(window.period, window.previous_start, window.previous_end, window.previous_start,
               window.previous_end, window.step_seconds),
        dataset,
        sources,
    )
    live = _live_now(dataset, sources, session)
    ids = [source.id for source in sources]
    peak_ten = analytics.peak_flow(session, window, dataset, ids, seconds=600)

    lines = analytics.line_comparison(session, window, dataset, sources)
    total_flow = sum(item["total"] for item in lines) or 1

    return {
        "window": window_payload(window),
        "dataset": dataset,
        "applicable": applicable,
        "notApplicableReason": None
        if applicable
        else "В выборке нет контрольных линий. Разметьте линию у источника или смените контур.",
        "singleCheckpoint": len(sources) < 2,
        "metrics": [
            build_metric(
                "people_in_zone",
                "Людей у КПП сейчас",
                live["peopleInZone"],
                unit="чел",
                whole=True,
                missing_reason=None if live["peopleInZone"] is not None else "живые данные только для реальных данных",
            ),
            build_metric(
                "entered", "Входов за период", float(totals.entered),
                previous=float(previous.entered), unit="чел", whole=True,
            ),
            build_metric(
                "exited", "Выходов за период", float(totals.exited),
                previous=float(previous.exited), unit="чел", whole=True,
            ),
            build_metric(
                "inside_now",
                "Внутри сейчас (оценка)",
                live["insideNow"],
                unit="чел",
                whole=True,
                hint="Входы минус выходы с начала суток. Ошибка накапливается, в полночь значение обнуляется",
                missing_reason=None if live["insideNow"] is not None else "живые данные только для реальных данных",
            ),
            build_metric(
                "peak_load",
                "Пиковая нагрузка за 10 минут",
                peak_ten,
                unit="чел",
                whole=True,
                hint="Наибольшее число проходов за любые десять минут подряд",
                missing_reason=None if peak_ten is not None else "нет данных за период",
            ),
            build_metric(
                "events",
                "Событий КПП",
                float(
                    analytics.count_events(
                        session, window, dataset, sources, ["checkpoint_overload", "abnormal_traffic"]
                    )
                ),
                unit="шт",
                whole=True,
            ),
        ],
        "flowSeries": analytics.build_series(
            session,
            window,
            dataset,
            sources,
            {
                "entered": lambda m: func.sum(m.entered),
                "exited": lambda m: func.sum(m.exited),
            },
        ),
        "direction": {
            "entered": totals.entered,
            "exited": totals.exited,
            "enteredShare": round(
                totals.entered / max(1, totals.entered + totals.exited) * 100, 1
            ),
        },
        "lines": [
            {**item, "share": round(item["total"] / total_flow * 100, 1)} for item in lines
        ],
        "weekdays": analytics.weekday_comparison(session, dataset, sources),
        "events": _event_cards(
            session, dataset, sources, window, ["checkpoint_overload", "abnormal_traffic", "camera_drop"], limit=50
        ),
        "thresholds": {"checkpointPerMinute": settings.checkpoint_threshold_per_minute},
    }


@router.get("/sources/{source_id}/summary")
def source_summary(
    source_id: int,
    period: str = Query(default="day"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Блоки «за период» в детальном просмотре источника (ТЗ, раздел 5.2)."""
    dataset = _dataset(user)
    window = resolve_window(period, date_from, date_to)
    source = sources_service.get_source(session, source_id, include_deleted=True)
    sources = [source]

    totals = analytics.collect_totals(session, window, dataset, sources)
    previous = analytics.collect_totals(
        session,
        Window(window.period, window.previous_start, window.previous_end, window.previous_start,
               window.previous_end, window.step_seconds),
        dataset,
        sources,
    )

    return {
        "window": window_payload(window),
        "dataset": dataset,
        "metrics": [
            build_metric("entered", "Входы", float(totals.entered),
                         previous=float(previous.entered), unit="чел", whole=True),
            build_metric("exited", "Выходы", float(totals.exited),
                         previous=float(previous.exited), unit="чел", whole=True),
            build_metric("queue_max", "Пик очереди", totals.queue_max,
                         previous=previous.queue_max, unit="чел",
                         missing_reason=None if totals.queue_max is not None else "не задана зона очереди"),
            build_metric("intensity", "Интенсивность", totals.intensity,
                         previous=previous.intensity, unit="чел/мин"),
        ],
        "flowSeries": analytics.build_series(
            session,
            window,
            dataset,
            sources,
            {
                "peopleInZone": lambda m: analytics.weighted(m.people_in_zone_avg, m),
                "entered": lambda m: func.sum(m.entered),
                "exited": lambda m: func.sum(m.exited),
            },
        ),
        "zones": analytics.zone_comparison(session, window, dataset, sources),
        "lines": analytics.line_comparison(session, window, dataset, sources),
    }

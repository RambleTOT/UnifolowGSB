"""Журнал событий, детали эпизода и обработка статусов."""

from __future__ import annotations

import csv
import io
import logging
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError, Conflict, NotFound
from app.core.timeutil import now_utc
from app.models import DATASET_REAL, Event, EventHistory, Source, User
from app.schemas.views import event_view
from app.services import analytics
from app.services.analytics import Window

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/events", tags=["events"])

STATUSES = ("open", "investigating", "resolved")
SORTS = {
    "started_at": Event.started_at,
    "severity": Event.severity,
    "status": Event.status,
    "type": Event.type,
}


class StatusChange(BaseModel):
    status: Literal["open", "investigating", "resolved"]
    comment: str = Field(default="", max_length=1000)
    # Если статус уже изменил кто-то другой, второй пользователь должен увидеть
    # понятный конфликт, а не молча затереть чужую работу (ТЗ, раздел 6.2).
    expected_status: str | None = None


class BulkStatusChange(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    status: Literal["open", "investigating", "resolved"]
    comment: str = Field(default="", max_length=1000)


def _dataset(user: User) -> str:
    return user.dataset or DATASET_REAL


def _filtered(
    session: Session,
    user: User,
    *,
    scope: str,
    period: str,
    date_from: str | None,
    date_to: str | None,
    severity: str | None,
    status: str | None,
    state: str | None,
    type_: str | None,
    source_id: int | None,
    query: str | None,
):
    window = analytics.resolve_window(period, date_from, date_to)
    sources = analytics.scope_sources(session, scope)
    ids = [source.id for source in sources]

    statement = select(Event).where(
        Event.dataset == _dataset(user),
        Event.started_at >= window.start,
        Event.started_at < window.end,
    )
    if ids:
        statement = statement.where(Event.source_id.in_(ids))
    if severity and severity != "all":
        statement = statement.where(Event.severity == severity)
    if status and status != "all":
        statement = statement.where(Event.status == status)
    if state == "ongoing":
        statement = statement.where(Event.ongoing.is_(True))
    elif state == "finished":
        statement = statement.where(Event.ongoing.is_(False))
    if type_ and type_ != "all":
        statement = statement.where(Event.type == type_)
    if source_id:
        statement = statement.where(Event.source_id == source_id)
    if query:
        # Поиск по-русски: приводим обе стороны к нижнему регистру сами.
        pattern = f"%{query.strip().lower().replace('ё', 'е')}%"
        statement = statement.where(
            or_(
                func.search_key(Event.title).like(pattern),
                func.search_key(Event.description).like(pattern),
            )
        )
    return statement, window


@router.get("")
def list_events(
    scope: str = Query(default="all"),
    period: str = Query(default="day"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    state: str | None = Query(default=None),
    type_: str | None = Query(default=None, alias="type"),
    source_id: int | None = Query(default=None, alias="sourceId"),
    query: str | None = Query(default=None, alias="q"),
    sort: str = Query(default="started_at"),
    order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=5, le=200, alias="pageSize"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    statement, window = _filtered(
        session,
        user,
        scope=scope,
        period=period,
        date_from=date_from,
        date_to=date_to,
        severity=severity,
        status=status,
        state=state,
        type_=type_,
        source_id=source_id,
        query=query,
    )

    total = session.scalar(
        select(func.count()).select_from(statement.subquery())
    ) or 0

    column = SORTS.get(sort, Event.started_at)
    statement = statement.order_by(column.desc() if order == "desc" else column.asc())
    statement = statement.offset((page - 1) * page_size).limit(page_size)

    events = [event_view(session, event) for event in session.scalars(statement)]

    # Счётчик необработанных высокого и критического приоритета — он же висит
    # у раздела в меню (ТЗ, раздел 4.2).
    attention = session.scalar(
        select(func.count())
        .select_from(Event)
        .where(
            Event.dataset == _dataset(user),
            Event.status != "resolved",
            Event.severity.in_(["high", "critical"]),
        )
    ) or 0

    return {
        "events": events,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "window": analytics.window_payload(window),
        "attentionCount": attention,
        "dataset": _dataset(user),
    }


@router.get("/export")
def export_events(
    fmt: str = Query(default="csv", alias="format"),
    scope: str = Query(default="all"),
    period: str = Query(default="day"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    state: str | None = Query(default=None),
    type_: str | None = Query(default=None, alias="type"),
    source_id: int | None = Query(default=None, alias="sourceId"),
    query: str | None = Query(default=None, alias="q"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    """Выгрузка отфильтрованного журнала (ТЗ, раздел 5.5)."""
    statement, _ = _filtered(
        session, user, scope=scope, period=period, date_from=date_from, date_to=date_to,
        severity=severity, status=status, state=state, type_=type_, source_id=source_id,
        query=query,
    )
    events = [event_view(session, event) for event in session.scalars(statement.order_by(Event.started_at.desc()))]
    demo = _dataset(user) != DATASET_REAL

    headers = [
        "Начало", "Окончание", "Длительность, мин", "Событие", "Тип", "Приоритет",
        "Состояние", "Статус обработки", "Источник", "Значение", "Порог",
    ]
    rows = [
        [
            event["startedAt"],
            event["endedAt"] or "",
            round((event["durationSeconds"] or 0) / 60, 1),
            event["title"],
            event["type"],
            event["severity"],
            "продолжается" if event["ongoing"] else "завершилось",
            event["status"],
            event["sourceName"],
            event["peakValue"],
            event["threshold"],
        ]
        for event in events
    ]

    if fmt == "xlsx":
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = "События"
        if demo:
            sheet.append(["Демо-данные"])
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        book.save(buffer)
        name = f"uniflow-events{'-demo' if demo else ''}.xlsx"
        return Response(
            content=buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    buffer = io.StringIO()
    # Разделитель «;» и запятая в дробях — иначе русский Excel прочитает файл неверно.
    writer = csv.writer(buffer, delimiter=";")
    if demo:
        writer.writerow(["Демо-данные"])
    writer.writerow(headers)
    for row in rows:
        writer.writerow([str(value).replace(".", ",") if isinstance(value, float) else value for value in row])

    name = f"uniflow-events{'-demo' if demo else ''}.csv"
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/{event_id}")
def get_event(
    event_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    event = session.get(Event, event_id)
    if event is None or event.dataset != _dataset(user):
        raise NotFound("Событие не найдено.", "event_not_found")

    # Динамика вокруг события: до, во время и после эпизода.
    margin = timedelta(minutes=30)
    end = (event.ended_at or now_utc()) + margin
    window = Window(
        period="custom",
        start=event.started_at - margin,
        end=end,
        previous_start=event.started_at - margin,
        previous_end=event.started_at,
        step_seconds=60,
    )
    source = session.get(Source, event.source_id)
    series = analytics.build_series(
        session,
        window,
        event.dataset,
        [source] if source else [],
        {
            "queue": lambda m: analytics.weighted(m.queue_avg, m),
            "entered": lambda m: func.sum(m.entered),
            "exited": lambda m: func.sum(m.exited),
            "waitMinutes": lambda m: func.sum(m.wait_sum_seconds)
            / func.nullif(func.sum(m.wait_count), 0)
            / 60.0,
        },
    )

    neighbours = session.scalars(
        select(Event)
        .where(
            Event.dataset == event.dataset,
            Event.source_id == event.source_id,
            Event.id != event.id,
            Event.started_at >= event.started_at - timedelta(hours=6),
            Event.started_at <= event.started_at + timedelta(hours=6),
        )
        .order_by(Event.started_at.desc())
        .limit(5)
    )

    return {
        "event": event_view(session, event, with_history=True),
        "series": series,
        "seriesWindow": analytics.window_payload(window),
        "nearby": [event_view(session, item) for item in neighbours],
    }


@router.get("/{event_id}/snapshot")
def event_snapshot(
    event_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    event = session.get(Event, event_id)
    if event is None or event.dataset != _dataset(user):
        raise NotFound("Событие не найдено.", "event_not_found")
    if not event.snapshot_path:
        raise AppError(
            "snapshot_disabled",
            "Кадр события не сохранён: сохранение кадров выключено в настройках.",
            409,
        )

    path = get_settings().snapshot_dir / event.snapshot_path
    if not path.exists():
        raise NotFound("Файл кадра не найден.", "snapshot_missing")
    return Response(content=path.read_bytes(), media_type="image/jpeg")


def _apply_status(
    session: Session, event: Event, change: str, comment: str, author: str
) -> None:
    session.add(
        EventHistory(
            event_id=event.id,
            at=now_utc(),
            author=author,
            from_status=event.status,
            to_status=change,
            comment=comment,
        )
    )
    event.status = change


@router.post("/{event_id}/status")
def change_status(
    event_id: int,
    payload: StatusChange,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    event = session.get(Event, event_id)
    if event is None or event.dataset != _dataset(user):
        raise NotFound("Событие не найдено.", "event_not_found")

    if payload.expected_status and event.status != payload.expected_status:
        raise Conflict(
            "Событие уже изменил другой пользователь: сейчас статус другой. Обновите страницу.",
            "event_changed",
            {"currentStatus": event.status},
        )

    author = user.display_name or user.login
    _apply_status(session, event, payload.status, payload.comment, author)
    session.commit()
    LOGGER.info("Событие %s: статус «%s» поставил %s", event_id, payload.status, author)
    return {"event": event_view(session, event, with_history=True)}


@router.post("/bulk-status")
def bulk_change_status(
    payload: BulkStatusChange,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    author = user.display_name or user.login
    events = session.scalars(
        select(Event).where(Event.id.in_(payload.ids), Event.dataset == _dataset(user))
    ).all()

    for event in events:
        _apply_status(session, event, payload.status, payload.comment, author)
    session.commit()

    return {
        "updated": len(events),
        "message": f"Статус изменён у событий: {len(events)}.",
    }

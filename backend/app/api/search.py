"""Поиск по источникам, событиям и разделам (ТЗ, раздел 4.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_session
from app.models import DATASET_REAL, Event, Source, User
from app.services import sources as sources_service

router = APIRouter(prefix="/api/search", tags=["search"])


def search_key(value: str) -> str:
    """Ключ поиска: без регистра и без разницы между «е» и «ё»."""
    return value.strip().lower().replace("ё", "е")

# Разделы интерфейса ищутся наравне с данными: по слову «отчёт» человек ждёт
# раздел «Отчёты», а не список файлов.
SECTIONS = [
    ("Главная", "/", "сводка обзор главная"),
    ("Оперативный мониторинг", "/monitor", "мониторинг камеры живое видео поток"),
    ("Анализ очередей", "/queues", "очередь очереди ожидание столовая"),
    ("Анализ КПП", "/checkpoints", "кпп проходная вход выход поток"),
    ("История и события", "/events", "события журнал история инциденты"),
    ("Отчёты", "/reports", "отчёт отчёты выгрузка excel pdf csv"),
    ("Источники видео", "/sources", "источники видео камеры файлы разметка"),
    ("Настройки", "/settings", "настройки пороги модель хранение"),
]


@router.get("")
def search(
    q: str = Query(default="", max_length=120),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    query = search_key(q)
    if len(query) < 2:
        return {"query": q, "sections": [], "sources": [], "events": [], "total": 0}

    sections = [
        {"title": title, "to": path}
        for title, path, keywords in SECTIONS
        if query in search_key(title) or query in search_key(keywords)
    ]

    pattern = f"%{query}%"
    lower = func.search_key
    found_sources = session.scalars(
        select(Source)
        .where(
            Source.deleted_at.is_(None),
            or_(lower(Source.name).like(pattern), lower(Source.location).like(pattern)),
        )
        .limit(6)
    ).all()

    # Теги хранятся списком, поэтому их фильтруем уже в памяти.
    tagged = [
        source
        for source in session.scalars(select(Source).where(Source.deleted_at.is_(None)))
        if any(query in search_key(str(tag)) for tag in (source.tags or []))
        and source not in found_sources
    ][:3]

    events = session.scalars(
        select(Event)
        .where(
            Event.dataset == (user.dataset or DATASET_REAL),
            or_(lower(Event.title).like(pattern), lower(Event.description).like(pattern)),
        )
        .order_by(Event.started_at.desc())
        .limit(6)
    ).all()

    from app.schemas.views import event_view

    source_items = [
        {
            "id": source.id,
            "name": source.name,
            "location": source.location,
            "scope": source.scope,
            "status": sources_service.status_of(source),
            "to": f"/monitor?source={source.id}",
            "reportTo": f"/reports?scope=source&source={source.id}",
            "readiness": sources_service.readiness_of(session, source)["state"],
        }
        for source in [*found_sources, *tagged]
    ]

    event_items = [
        {**event_view(session, event), "to": f"/events/{event.id}"} for event in events
    ]

    return {
        "query": q,
        "sections": sections,
        "sources": source_items,
        "events": event_items,
        "total": len(sections) + len(source_items) + len(event_items),
    }

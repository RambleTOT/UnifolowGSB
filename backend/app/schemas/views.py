"""Сборка ответов API.

Показатели и состояния приходят с сервера готовыми: интерфейсу не нужно
догадываться, что означает рост очереди и почему метрика не считается
(ТЗ, разделы 3.2 и 3.5).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cv.markup import Markup, markup_to_dict
from app.models import Event, EventHistory, Source, User, Video
from app.services.runtime import LiveSnapshot
from app.services.sources import get_markup, primary_metric, source_readiness, video_path

PROFILE_TITLES = {
    "ops": "Операционный центр",
    "security": "Пост охраны",
    "manager": "Менеджер объекта",
    "admin": "Технический администратор",
}

# Стартовый раздел и контур после входа зависят от профиля (ТЗ, раздел 1.4).
PROFILE_START = {
    "ops": {"section": "home", "scope": "all"},
    "security": {"section": "monitor", "scope": "gate"},
    "manager": {"section": "home", "scope": "canteen"},
    "admin": {"section": "sources", "scope": "all"},
}


def user_view(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "login": user.login,
        "displayName": user.display_name or user.login,
        "profile": user.profile,
        "profileTitle": PROFILE_TITLES.get(user.profile, PROFILE_TITLES["ops"]),
        "start": PROFILE_START.get(user.profile, PROFILE_START["ops"]),
        "dataset": user.dataset,
        "liveUpdates": user.live_updates,
        "notificationsSeenAt": user.notifications_seen_at.isoformat()
        if user.notifications_seen_at
        else None,
    }


def video_view(video: Video | None) -> dict[str, Any] | None:
    if video is None:
        return None
    return {
        "id": video.id,
        "name": video.original_name,
        "durationSeconds": round(video.duration_seconds, 2),
        "width": video.width,
        "height": video.height,
        "fps": round(video.fps, 2),
        "sizeBytes": video.size_bytes,
        "resolution": f"{video.width} × {video.height}" if video.width else None,
        "uploadedAt": video.created_at.isoformat(),
    }


def source_view(
    session: Session,
    source: Source,
    snapshot: LiveSnapshot | None = None,
    markup: Markup | None = None,
    include_markup: bool = False,
) -> dict[str, Any]:
    from app.services.settings import load_settings

    system_profile = load_settings(session).model_profile
    markup = markup if markup is not None else get_markup(session, source.id)
    stream = source.connection_type == "stream"
    if stream:
        # У потока «файла на диске» нет: есть ли сигнал, скажет рабочий поток.
        path = None
        video_assigned = bool(source.stream_url)
        file_exists = video_assigned
    else:
        path = video_path(source.video)
        video_assigned = source.video_id is not None
        file_exists = path is not None and path.exists()

    view: dict[str, Any] = {
        "id": source.id,
        "name": source.name,
        "scope": source.scope,
        "location": source.location,
        "tags": source.tags or [],
        "enabled": source.enabled,
        "deleted": source.deleted_at is not None,
        "connectionType": source.connection_type,
        "streamUrl": source.stream_url if stream else None,
        "video": None if stream else video_view(source.video),
        "videoAvailable": file_exists,
        # Наружу отдаём действующее значение и признак, откуда оно взялось.
        "modelProfile": source.model_profile or system_profile,
        "modelProfileOverride": source.model_profile is not None,
        "confidence": source.confidence,
        "aggregationSeconds": source.aggregation_seconds,
        "readiness": source_readiness(markup, video_assigned, file_exists, stream),
        "primaryMetric": primary_metric(markup),
        "status": source.status,
        "lastSignalAt": source.last_signal_at.isoformat() if source.last_signal_at else None,
        "lastError": source.last_error,
        "live": None,
    }

    if include_markup:
        view["markup"] = markup_to_dict(markup)

    if snapshot is not None:
        view["status"] = snapshot.status
        view["live"] = snapshot.to_message()
        view["lastSignalAt"] = (
            snapshot.updated_at.isoformat() if snapshot.updated_at else view["lastSignalAt"]
        )
    elif not source.enabled:
        # Выключенный источник — это решение пользователя, а не сбой.
        view["status"] = "disabled"
    elif not video_assigned:
        view["status"] = "no_video"
    elif not file_exists:
        # Файл назначен, но пропал — это «нет сигнала» с понятной причиной.
        view["status"] = "offline"
        view["lastError"] = f"Видеофайл не найден: {path.name if path else '—'}"

    return view


def event_view(session: Session, event: Event, with_history: bool = False) -> dict[str, Any]:
    """Событие в едином виде: одинаково выглядит в журнале, на Главной и в аналитике."""
    source = session.get(Source, event.source_id)
    duration = (
        (event.ended_at - event.started_at).total_seconds() if event.ended_at else None
    )
    exceed = (
        round((event.peak_value - event.threshold) / event.threshold * 100)
        if event.threshold
        else None
    )

    payload: dict[str, Any] = {
        "id": event.id,
        "type": event.type,
        "severity": event.severity,
        "title": event.title,
        "description": event.description,
        "sourceId": event.source_id,
        "sourceName": source.name if source else "источник удалён",
        "sourceDeleted": bool(source and source.deleted_at),
        "scope": source.scope if source else None,
        "startedAt": event.started_at.isoformat(),
        "endedAt": event.ended_at.isoformat() if event.ended_at else None,
        "durationSeconds": duration,
        "ongoing": event.ongoing,
        "status": event.status,
        "metricValue": round(event.metric_value, 1),
        "peakValue": round(event.peak_value, 1),
        "threshold": round(event.threshold, 1),
        "exceedPercent": exceed,
        "snapshotAvailable": bool(event.snapshot_path),
        "videoPositionSeconds": event.video_position_seconds,
        "loopNumber": event.loop_number,
        "dataset": event.dataset,
    }

    if with_history:
        history = session.scalars(
            select(EventHistory)
            .where(EventHistory.event_id == event.id)
            .order_by(EventHistory.at)
        )
        payload["history"] = [
            {
                "at": item.at.isoformat(),
                "author": item.author,
                "fromStatus": item.from_status,
                "toStatus": item.to_status,
                "comment": item.comment,
            }
            for item in history
        ]

    return payload

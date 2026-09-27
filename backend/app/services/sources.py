"""Источники: создание, изменение, разметка и готовность к подсчёту."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.timeutil import now_utc, start_of_day
from app.cv.markup import (
    Markup,
    describe_missing,
    markup_from_dict,
    markup_to_dict,
    readiness,
    validate_markup,
)
from app.cv.video_source import is_stream_url
from app.models import DATASET_REAL, Bucket, Geometry, Source, Video
from app.services.runtime import SourceRuntimeConfig
from app.services.settings import load_settings

LOGGER = logging.getLogger(__name__)

SCOPES = ("canteen", "gate")
CONNECTION_TYPES = ("video_loop", "stream")


def _clean_stream_url(value: Any) -> str | None:
    """Ссылка на поток: пустое — «не задана», иначе только сетевые протоколы."""
    if value is None:
        return None
    url = str(value).strip()
    if not url:
        return None
    if not is_stream_url(url):
        raise AppError(
            "validation_error",
            "Ссылка на поток должна начинаться с http://, https://, rtsp:// или rtmp://.",
            422,
            {"fields": {"stream_url": "Нужна ссылка на поток: HLS (.m3u8), RTSP или HTTP."}},
        )
    return url


def is_stream(source: Source) -> bool:
    return source.connection_type == "stream"


def has_signal_source(source: Source) -> bool:
    """Есть ли у источника, что показывать: файл или ссылка на поток."""
    return bool(source.stream_url) if is_stream(source) else source.video_id is not None


def list_sources(session: Session, include_deleted: bool = False) -> list[Source]:
    query = select(Source).order_by(Source.id)
    if not include_deleted:
        query = query.where(Source.deleted_at.is_(None))
    return list(session.scalars(query))


def get_source(session: Session, source_id: int, include_deleted: bool = False) -> Source:
    source = session.get(Source, source_id)
    if source is None or (source.deleted_at is not None and not include_deleted):
        raise NotFound("Источник не найден. Возможно, он удалён.", "source_not_found")
    return source


def _check_name(session: Session, name: str, source_id: int | None = None) -> None:
    name = name.strip()
    if not name:
        raise AppError("validation_error", "Укажите название источника.", 422,
                       {"fields": {"name": "Название обязательно."}})
    query = select(Source).where(Source.name == name, Source.deleted_at.is_(None))
    if source_id is not None:
        query = query.where(Source.id != source_id)
    if session.scalars(query).first() is not None:
        raise AppError("validation_error", f"Источник «{name}» уже есть.", 422,
                       {"fields": {"name": "Такое название уже занято."}})


def create_source(session: Session, payload: dict[str, Any]) -> Source:
    _check_name(session, payload.get("name", ""))
    scope = payload.get("scope", "canteen")
    if scope not in SCOPES:
        raise AppError("validation_error", "Выберите контур: столовая или КПП.", 422,
                       {"fields": {"scope": "Неизвестный контур."}})

    connection_type = payload.get("connection_type") or "video_loop"
    if connection_type not in CONNECTION_TYPES:
        raise AppError("validation_error", "Неизвестный тип подключения.", 422)

    source = Source(
        name=payload["name"].strip(),
        scope=scope,
        location=payload.get("location", "").strip(),
        tags=payload.get("tags", []),
        enabled=payload.get("enabled", True),
        connection_type=connection_type,
        video_id=payload.get("video_id"),
        stream_url=_clean_stream_url(payload.get("stream_url")),
        model_profile=payload.get("model_profile") or None,
        confidence=payload.get("confidence"),
        aggregation_seconds=payload.get("aggregation_seconds"),
        status="offline",
    )
    session.add(source)
    session.flush()
    LOGGER.info("Создан источник %s «%s»", source.id, source.name)
    return source


def update_source(session: Session, source_id: int, payload: dict[str, Any]) -> Source:
    source = get_source(session, source_id)

    if "name" in payload:
        _check_name(session, payload["name"], source_id)
        source.name = payload["name"].strip()
    if "scope" in payload:
        if payload["scope"] not in SCOPES:
            raise AppError("validation_error", "Неизвестный контур.", 422)
        source.scope = payload["scope"]
    for field_name in ("location", "tags", "enabled", "model_profile", "confidence",
                       "aggregation_seconds"):
        if field_name in payload:
            setattr(source, field_name, payload[field_name])
    if "connection_type" in payload and payload["connection_type"] is not None:
        if payload["connection_type"] not in CONNECTION_TYPES:
            raise AppError("validation_error", "Неизвестный тип подключения.", 422)
        source.connection_type = payload["connection_type"]
    if "stream_url" in payload:
        source.stream_url = _clean_stream_url(payload["stream_url"])
    if "video_id" in payload:
        if payload["video_id"] is not None and session.get(Video, payload["video_id"]) is None:
            raise NotFound("Видеофайл не найден.", "video_not_found")
        source.video_id = payload["video_id"]
        # Связанный объект уже загружен: после смены ссылки его нужно перечитать,
        # иначе ответ покажет прежний файл.
        session.flush()
        session.expire(source, ["video"])

    session.flush()
    return source


def delete_source(session: Session, source_id: int) -> Source:
    """Мягкое удаление: история и события остаются в аналитике."""
    source = get_source(session, source_id)
    source.deleted_at = now_utc()
    source.enabled = False
    session.flush()
    LOGGER.info("Источник %s помечен удалённым", source_id)
    return source


# --- разметка ---------------------------------------------------------------


def get_markup(session: Session, source_id: int) -> Markup:
    row = session.scalar(select(Geometry).where(Geometry.source_id == source_id))
    if row is None or not row.payload:
        return Markup()
    return markup_from_dict(row.payload)


def save_markup(session: Session, source_id: int, payload: dict[str, Any], author: str) -> Markup:
    get_source(session, source_id)
    markup = markup_from_dict(payload)

    problems = validate_markup(markup)
    if problems:
        raise AppError(
            "validation_error",
            "Разметку нельзя сохранить: есть ошибки.",
            422,
            {"objects": [{"id": p.object_id, "code": p.code, "message": p.message} for p in problems]},
        )

    row = session.scalar(select(Geometry).where(Geometry.source_id == source_id))
    if row is None:
        row = Geometry(source_id=source_id, payload=markup_to_dict(markup), updated_by=author)
        session.add(row)
    else:
        row.payload = markup_to_dict(markup)
        row.updated_by = author
    session.flush()
    LOGGER.info("Источник %s: разметка сохранена пользователем %s", source_id, author)
    return markup


# --- состояние и конфигурация ----------------------------------------------


def video_path(video: Video | None) -> Path | None:
    if video is None:
        return None
    return get_settings().video_dir / video.stored_name


def source_readiness(
    markup: Markup, video_assigned: bool, file_exists: bool, stream: bool = False
) -> dict[str, Any]:
    """Готовность к подсчёту (ТЗ, раздел 3.3) — с объяснением, чего не хватает."""
    if not video_assigned:
        missing = "не указана ссылка на поток" if stream else "видео не назначено"
        return {"state": "no_video", "missing": [missing]}
    if not file_exists:
        return {"state": "file_missing", "missing": ["видеофайл не найден на диске"]}
    state = readiness(markup)
    return {"state": state, "missing": describe_missing(markup)}


def readiness_of(session: Session, source: Source, markup: Markup | None = None) -> dict[str, Any]:
    """Готовность источника с учётом типа подключения: файл или поток."""
    markup = markup if markup is not None else get_markup(session, source.id)
    if is_stream(source):
        assigned = bool(source.stream_url)
        return source_readiness(markup, assigned, assigned, stream=True)
    path = video_path(source.video)
    return source_readiness(markup, source.video_id is not None, bool(path and path.exists()))


def status_of(source: Source) -> str:
    """Статус для списков: источник, которому нечего показывать, — «видео не назначено»."""
    return source.status if has_signal_source(source) else "no_video"


def countable_sources(session: Session) -> list[dict[str, Any]]:
    """Источники, которые вообще должны давать данные.

    Выключенный источник и источник без видео проблемой не считаются — они не
    входят в индикатор состояния данных (ТЗ, раздел 4.3).
    """
    rows: list[dict[str, Any]] = []
    for source in list_sources(session):
        if not source.enabled or not has_signal_source(source):
            continue
        if is_stream(source):
            # У потока «нет сигнала» определяет сам рабочий поток по факту.
            rows.append(
                {
                    "sourceId": source.id,
                    "name": source.name,
                    "status": source.status,
                    "error": source.last_error,
                }
            )
            continue
        path = video_path(source.video)
        exists = path is not None and path.exists()
        rows.append(
            {
                "sourceId": source.id,
                "name": source.name,
                "status": source.status if exists else "offline",
                "error": None if exists else f"Видеофайл не найден: {path.name if path else '—'}",
            }
        )
    return rows


def primary_metric(markup: Markup) -> str:
    """Главная метрика источника определяется его разметкой (ТЗ, раздел 3.1)."""
    if markup.lines:
        return "flow"
    if any(zone.kind == "queue" for zone in markup.zones):
        return "queue"
    if any(zone.kind == "occupancy" for zone in markup.zones):
        return "occupancy"
    return "none"


def today_totals(session: Session, source_id: int) -> tuple[int, int]:
    """Сколько уже посчитано с начала суток объекта: переживает перезапуск."""
    row = session.execute(
        select(func.sum(Bucket.entered), func.sum(Bucket.exited)).where(
            Bucket.source_id == source_id,
            Bucket.dataset == DATASET_REAL,
            Bucket.started_at >= start_of_day(),
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


def build_runtime_config(session: Session, source: Source) -> SourceRuntimeConfig | None:
    """Собрать конфигурацию для рабочего потока источника."""
    if is_stream(source):
        if not source.stream_url:
            return None
        path = None
    else:
        path = video_path(source.video)
        if path is None or not path.exists():
            return None

    app_settings = get_settings()
    system = load_settings(session)
    markup = get_markup(session, source.id)
    entries_today, exits_today = today_totals(session, source.id)

    return SourceRuntimeConfig(
        source_id=source.id,
        name=source.name,
        scope=source.scope,
        video_path=path,
        stream_url=source.stream_url if is_stream(source) else None,
        markup=markup,
        model_profile=source.model_profile or system.model_profile,
        confidence=source.confidence if source.confidence is not None else system.confidence,
        tracker=system.tracker,
        device=app_settings.device,
        analysis_mode=app_settings.analysis_mode,
        aggregation_seconds=source.aggregation_seconds or system.aggregation_seconds,
        cache_dir=app_settings.cache_dir,
        entries_today=entries_today,
        exits_today=exits_today,
    )


def touch_status(session: Session, source_id: int, status: str, error: str | None,
                 at: datetime | None = None) -> None:
    source = session.get(Source, source_id)
    if source is None:
        return
    source.status = status
    source.last_error = error
    source.last_signal_at = at or now_utc()

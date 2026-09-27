"""Видеофайлы, источники и их разметка."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Video(TimestampMixin, Base):
    """Загруженный файл. Один файл может использоваться несколькими источниками."""

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fps: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class Source(TimestampMixin, Base):
    """Источник видео: то, что пользователь видит в мониторинге."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="canteen", nullable=False)
    location: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Мягкое удаление: данные и события остаются в аналитике с пометкой
    # «источник удалён» (ТЗ, раздел 5.7).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # video_loop — файл по кругу, stream — прямой поток с камеры по ссылке.
    connection_type: Mapped[str] = mapped_column(String(32), default="video_loop", nullable=False)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"), nullable=True)
    stream_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    video: Mapped[Video | None] = relationship(lazy="joined")

    # Пусто — значит «как в системных настройках».
    model_profile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    aggregation_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Последнее известное состояние: нужно, чтобы список источников оставался
    # осмысленным сразу после перезапуска, до первого кадра.
    status: Mapped[str] = mapped_column(String(16), default="offline", nullable=False)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Geometry(TimestampMixin, Base):
    """Разметка источника: зоны и линии в нормированных координатах."""

    __tablename__ = "geometry"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(120), default="", nullable=False)

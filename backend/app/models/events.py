"""События: эпизоды отклонений и история их обработки (ТЗ, раздел 3.4)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.metrics import DATASET_REAL


class Event(TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_time", "dataset", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    dataset: Mapped[str] = mapped_column(String(8), default=DATASET_REAL, nullable=False)

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Состояние выставляет система, статус обработки — человек. Это разные вещи.
    ongoing: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)

    metric_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    snapshot_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    video_position_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    loop_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EventHistory(Base):
    """Кто, когда и с каким комментарием менял статус обработки."""

    __tablename__ = "event_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    author: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    from_status: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)

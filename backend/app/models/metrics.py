"""Метрики: интервалы агрегации, свёртки, ожидания и итоги кругов.

Базовый интервал — 5 секунд (настраивается). Из него собираются минутные и
часовые свёртки: аналитика за месяц не должна перебирать миллионы строк.

Уровни хранения разные, потому что вопросы разные: «сколько прошло через этот
проход» — уровень линии, «сколько стоит в этой очереди» — уровень зоны,
«что с источником» — уровень источника.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Признак набора данных: реальные и демо никогда не смешиваются (ТЗ, 3.8).
DATASET_REAL = "real"
DATASET_DEMO = "demo"


class _BucketColumns:
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    dataset: Mapped[str] = mapped_column(String(8), default=DATASET_REAL, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Сколько кадров попало в интервал: нужно для взвешенных свёрток и для
    # признака неполных данных.
    samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    people_in_frame_avg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    people_in_frame_max: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    people_in_zone_avg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    queue_avg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    queue_max: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    entered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exited: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wait_sum_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    wait_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fps_avg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms_avg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_avg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    health: Mapped[str] = mapped_column(String(16), default="online", nullable=False)
    # Интервал, попавший на стык кругов, помечается: значения в нём неполные.
    loop_boundary: Mapped[bool] = mapped_column(default=False, nullable=False)


class Bucket(_BucketColumns, Base):
    """Базовый интервал источника (по умолчанию 5 секунд)."""

    __tablename__ = "buckets"
    __table_args__ = (
        Index("ix_buckets_source_time", "source_id", "dataset", "started_at"),
    )


class BucketMinute(_BucketColumns, Base):
    """Минутная свёртка."""

    __tablename__ = "buckets_1m"
    __table_args__ = (
        Index("ix_buckets_1m_source_time", "source_id", "dataset", "started_at"),
    )


class BucketHour(_BucketColumns, Base):
    """Часовая свёртка."""

    __tablename__ = "buckets_1h"
    __table_args__ = (
        Index("ix_buckets_1h_source_time", "source_id", "dataset", "started_at"),
    )


class ZoneBucket(Base):
    """Интервал по одной зоне: без этого не сравнить зоны очереди между собой."""

    __tablename__ = "zone_buckets"
    __table_args__ = (
        Index("ix_zone_buckets_time", "source_id", "zone_id", "dataset", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    zone_id: Mapped[str] = mapped_column(String(64), nullable=False)
    zone_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    zone_kind: Mapped[str] = mapped_column(String(16), default="queue", nullable=False)
    dataset: Mapped[str] = mapped_column(String(8), default=DATASET_REAL, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    people_avg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    people_max: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    wait_sum_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    wait_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LineBucket(Base):
    """Интервал по одной контрольной линии: входы и выходы этого прохода."""

    __tablename__ = "line_buckets"
    __table_args__ = (
        Index("ix_line_buckets_time", "source_id", "line_id", "dataset", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    line_id: Mapped[str] = mapped_column(String(64), nullable=False)
    line_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    dataset: Mapped[str] = mapped_column(String(8), default=DATASET_REAL, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    entered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exited: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Wait(Base):
    """Завершённое ожидание одного человека в зоне очереди.

    Хранится отдельными записями, иначе не посчитать 95-й процентиль и не свести
    ожидание по нескольким источникам «по всем ожиданиям, а не средним средних»
    (ТЗ, раздел 3.2).
    """

    __tablename__ = "waits"
    __table_args__ = (Index("ix_waits_time", "source_id", "dataset", "ended_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    zone_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset: Mapped[str] = mapped_column(String(8), default=DATASET_REAL, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    seconds: Mapped[float] = mapped_column(Float, nullable=False)


class Loop(Base):
    """Итог одного полного прохода видеофайла: его сверяют с ручным подсчётом."""

    __tablename__ = "loops"
    __table_args__ = (Index("ix_loops_source", "source_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    loop_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    entered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exited: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

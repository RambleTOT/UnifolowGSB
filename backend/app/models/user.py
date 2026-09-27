"""Пользователь системы.

Права у всех одинаковые (ТЗ, раздел 4.1). На учётной записи хранятся личные
настройки: тема, профиль, режим данных, имя и отметка о просмотре уведомлений.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    # Профиль определяет только стартовый раздел и контур после входа.
    profile: Mapped[str] = mapped_column(String(32), default="ops", nullable=False)
    dataset: Mapped[str] = mapped_column(String(8), default="real", nullable=False)
    live_updates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    notifications_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

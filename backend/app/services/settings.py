"""Системные настройки: значения по умолчанию, чтение, сохранение и история.

Системные настройки общие для всех и влияют только на новые данные
(ТЗ, раздел 5.8). Значения по умолчанию берутся из окружения, дальше живут в базе.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.timeutil import now_utc
from app.models import SettingHistory, SystemSetting

LOGGER = logging.getLogger(__name__)

SETTINGS_KEY = "system"


@dataclass
class SystemSettings:
    """То, что пользователь меняет в разделе «Настройки»."""

    model_profile: str = "standard"
    tracker: str = "bytetrack.yaml"
    confidence: float = 0.25

    queue_threshold: int = 10
    wait_threshold_minutes: float = 5.0
    checkpoint_threshold_per_minute: int = 25
    event_min_duration_seconds: int = 15

    retention_days: int = 30
    aggregation_seconds: int = 5
    save_event_snapshots: bool = True

    # Границы значений: интерфейс показывает их у полей, а сервер проверяет.
    BOUNDS = {
        "confidence": (0.1, 0.95),
        "queue_threshold": (1, 100),
        "wait_threshold_minutes": (1, 60),
        "checkpoint_threshold_per_minute": (1, 200),
        "event_min_duration_seconds": (5, 300),
        "retention_days": (7, 365),
        "aggregation_seconds": (5, 300),
    }

    def validate(self) -> None:
        problems: dict[str, str] = {}
        for field_name, (low, high) in self.BOUNDS.items():
            value = getattr(self, field_name)
            if value < low or value > high:
                problems[field_name] = f"Допустимо от {low} до {high}."
        if self.model_profile not in ("fast", "standard", "accurate", "far"):
            problems["model_profile"] = "Неизвестный профиль модели."
        if problems:
            raise AppError(
                "validation_error",
                "Часть параметров вне допустимых границ.",
                422,
                {"fields": problems},
            )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("BOUNDS", None)
        return payload


def defaults() -> SystemSettings:
    settings = get_settings()
    return SystemSettings(
        model_profile=settings.model_profile,
        tracker=settings.tracker,
        confidence=settings.confidence,
        queue_threshold=settings.queue_threshold,
        wait_threshold_minutes=settings.wait_threshold_minutes,
        checkpoint_threshold_per_minute=settings.checkpoint_threshold_per_minute,
        event_min_duration_seconds=settings.event_min_duration_seconds,
        retention_days=settings.retention_days,
        aggregation_seconds=settings.aggregation_seconds,
        save_event_snapshots=settings.save_event_snapshots,
    )


def load_settings(session: Session) -> SystemSettings:
    row = session.get(SystemSetting, SETTINGS_KEY)
    if row is None:
        return defaults()
    payload = defaults().as_dict()
    payload.update(row.value or {})
    payload.pop("BOUNDS", None)
    return SystemSettings(**payload)


def save_settings(session: Session, new_settings: SystemSettings, author: str) -> SystemSettings:
    new_settings.validate()
    row = session.get(SystemSetting, SETTINGS_KEY)
    old_value = json.dumps(row.value, ensure_ascii=False) if row else ""

    if row is None:
        row = SystemSetting(key=SETTINGS_KEY, value=new_settings.as_dict())
        session.add(row)
    else:
        row.value = new_settings.as_dict()
    # История ссылается на строку настроек: она должна появиться первой.
    session.flush()

    session.add(
        SettingHistory(
            key=SETTINGS_KEY,
            at=now_utc(),
            author=author,
            old_value=old_value,
            new_value=json.dumps(new_settings.as_dict(), ensure_ascii=False),
        )
    )
    LOGGER.info("Настройки сохранены пользователем %s", author)
    return new_settings


def reset_settings(session: Session, author: str) -> SystemSettings:
    return save_settings(session, defaults(), author)


def history(session: Session, limit: int = 20) -> list[SettingHistory]:
    return list(
        session.scalars(
            select(SettingHistory).order_by(SettingHistory.at.desc()).limit(limit)
        )
    )

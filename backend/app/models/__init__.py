"""Модель данных приложения."""

from app.models.base import Base, TimestampMixin
from app.models.events import Event, EventHistory
from app.models.media import Geometry, Source, Video
from app.models.metrics import (
    DATASET_DEMO,
    DATASET_REAL,
    Bucket,
    BucketHour,
    BucketMinute,
    LineBucket,
    Loop,
    Wait,
    ZoneBucket,
)
from app.models.settings import SettingHistory, SystemSetting
from app.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "Bucket",
    "BucketHour",
    "BucketMinute",
    "DATASET_DEMO",
    "DATASET_REAL",
    "Event",
    "EventHistory",
    "Geometry",
    "LineBucket",
    "Loop",
    "SettingHistory",
    "Source",
    "SystemSetting",
    "User",
    "Video",
    "Wait",
    "ZoneBucket",
]

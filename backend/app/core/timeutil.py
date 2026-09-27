"""Время объекта.

Внутри система живёт в UTC, а пользователю показывает время объекта: сутки
«внутри сейчас», границы периодов и подписи графиков считаются именно по нему
(ТЗ, раздел 3.6).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def site_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def now_utc() -> datetime:
    """Текущий момент в UTC без сведений о поясе: так он и лежит в базе."""
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def to_site(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc).astimezone(site_timezone())


def start_of_day(moment: datetime | None = None) -> datetime:
    """Начало суток объекта, выраженное в UTC."""
    moment = moment or now_utc()
    local = to_site(moment)
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def floor_to(moment: datetime, seconds: int) -> datetime:
    """Округлить момент вниз до сетки интервалов агрегации."""
    epoch = moment.replace(tzinfo=timezone.utc).timestamp()
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=timezone.utc).replace(tzinfo=None)


def utc_offset_hours(moment: datetime | None = None) -> float:
    offset = to_site(moment or now_utc()).utcoffset() or timedelta()
    return offset.total_seconds() / 3600

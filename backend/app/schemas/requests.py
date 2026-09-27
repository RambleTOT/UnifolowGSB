"""Тела запросов. Проверка значений здесь, чтобы ошибки приходили по полям."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    profile: Literal["ops", "security", "manager", "admin"] | None = None
    dataset: Literal["real", "demo"] | None = None
    live_updates: bool | None = None


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    scope: Literal["canteen", "gate"] = "canteen"
    location: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    connection_type: Literal["video_loop", "stream"] = "video_loop"
    video_id: int | None = None
    stream_url: str | None = Field(default=None, max_length=1000)
    model_profile: Literal["fast", "standard", "accurate", "far"] | None = None
    confidence: float | None = Field(default=None, ge=0.1, le=0.95)
    aggregation_seconds: int | None = Field(default=None, ge=5, le=300)


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    scope: Literal["canteen", "gate"] | None = None
    location: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = None
    enabled: bool | None = None
    connection_type: Literal["video_loop", "stream"] | None = None
    video_id: int | None = None
    stream_url: str | None = Field(default=None, max_length=1000)
    model_profile: Literal["fast", "standard", "accurate", "far"] | None = None
    confidence: float | None = Field(default=None, ge=0.1, le=0.95)
    aggregation_seconds: int | None = Field(default=None, ge=5, le=300)


class MarkupRequest(BaseModel):
    anchor: Literal["bottom_center", "center"] = "bottom_center"
    lines: list[dict[str, Any]] = Field(default_factory=list)
    zones: list[dict[str, Any]] = Field(default_factory=list)


class SettingsUpdate(BaseModel):
    model_profile: Literal["fast", "standard", "accurate", "far"] | None = None
    tracker: str | None = None
    confidence: float | None = None
    queue_threshold: int | None = None
    wait_threshold_minutes: float | None = None
    checkpoint_threshold_per_minute: int | None = None
    event_min_duration_seconds: int | None = None
    retention_days: int | None = None
    aggregation_seconds: int | None = None
    save_event_snapshots: bool | None = None

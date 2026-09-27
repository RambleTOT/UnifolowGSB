"""Параметры запуска. Всё, что различается между машиной и сервером, живёт в .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env",),
        env_prefix="UNIFLOW_",
        extra="ignore",
    )

    env: str = "local"
    host: str = "127.0.0.1"
    port: int = 8000
    secret_key: str = "change-me-please"
    timezone: str = "Europe/Moscow"

    admin_login: str = "admin"
    admin_password: str = ""

    database_url: str = "sqlite:///./data/uniflow.db"
    video_dir: Path = ROOT_DIR / "data" / "videos"
    snapshot_dir: Path = ROOT_DIR / "data" / "snapshots"
    cache_dir: Path = ROOT_DIR / "data" / "cache"
    max_upload_mb: int = 512

    device: str = "auto"
    analysis_mode: str = "auto"
    model_profile: str = "standard"
    confidence: float = 0.25
    tracker: str = "bytetrack.yaml"
    aggregation_seconds: int = 5
    retention_days: int = 30

    queue_threshold: int = 10
    wait_threshold_minutes: float = 5.0
    checkpoint_threshold_per_minute: int = 25
    event_min_duration_seconds: int = 15
    save_event_snapshots: bool = True

    allowed_video_suffixes: tuple[str, ...] = Field(
        default=(".mp4", ".mov", ".mkv", ".avi", ".m4v")
    )

    @field_validator("video_dir", "snapshot_dir", "cache_dir", mode="after")
    @classmethod
    def _absolute_directories(cls, value: Path) -> Path:
        """Пути из .env считаются от корня проекта, а не от рабочего каталога.

        Иначе запуск из backend/ и из корня складывали бы данные в разные места.
        """
        return value if value.is_absolute() else (ROOT_DIR / value).resolve()

    @model_validator(mode="after")
    def _absolute_database(self) -> "Settings":
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            raw = self.database_url[len(prefix) :]
            if not raw.startswith("/"):
                resolved = (ROOT_DIR / raw).resolve()
                object.__setattr__(self, "database_url", f"{prefix}{resolved}")
        return self

    @property
    def is_local(self) -> bool:
        return self.env == "local"

    def ensure_directories(self) -> None:
        for directory in (self.video_dir, self.snapshot_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

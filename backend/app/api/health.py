"""Состояние сервера: используется и проверкой контейнера, и интерфейсом."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.timeutil import now_utc
from app.cv.device import device_label, resolve_device

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict:
    settings = get_settings()
    device = resolve_device(settings.device)
    return {
        "status": "ok",
        "time": now_utc().isoformat(),
        "timezone": settings.timezone,
        "device": device,
        "deviceTitle": device_label(device),
        "analysisMode": settings.analysis_mode,
        "upload": {
            "maxSizeMb": settings.max_upload_mb,
            "formats": list(settings.allowed_video_suffixes),
        },
    }

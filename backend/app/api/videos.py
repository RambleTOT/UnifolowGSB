"""Загрузка видеофайлов."""

from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError, NotFound
from app.cv.video_source import VideoUnavailable, probe_video
from app.models import User, Video
from app.schemas.views import video_view

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["videos"])

CHUNK = 1024 * 1024


@router.get("")
def list_videos(
    _user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    videos = session.scalars(select(Video).order_by(Video.created_at.desc()))
    return {"videos": [video_view(video) for video in videos]}


@router.post("")
async def upload_video(
    file: UploadFile = File(...),
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()

    if suffix not in settings.allowed_video_suffixes:
        allowed = ", ".join(settings.allowed_video_suffixes)
        raise AppError(
            "unsupported_format",
            f"Такой формат не поддерживается. Допустимые: {allowed}.",
            422,
        )

    settings.video_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = settings.video_dir / stored_name
    limit = settings.max_upload_mb * 1024 * 1024
    digest = hashlib.sha256()
    size = 0

    try:
        with target.open("wb") as stream:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise AppError(
                        "file_too_large",
                        f"Файл больше {settings.max_upload_mb} МБ.",
                        413,
                    )
                digest.update(chunk)
                stream.write(chunk)

        # Файл должен не только загрузиться, но и читаться: битое видео лучше
        # отклонить сразу, чем показать источник, который никогда не заработает.
        info = probe_video(target)
    except AppError:
        target.unlink(missing_ok=True)
        raise
    except VideoUnavailable as error:
        target.unlink(missing_ok=True)
        raise AppError("broken_video", f"Файл не читается: {error}", 422) from error
    except Exception as error:  # noqa: BLE001
        target.unlink(missing_ok=True)
        raise AppError("upload_failed", f"Загрузка не удалась: {error}", 500) from error

    video = Video(
        original_name=file.filename or stored_name,
        stored_name=stored_name,
        size_bytes=size,
        duration_seconds=info.duration_seconds,
        width=info.width,
        height=info.height,
        fps=info.fps,
        checksum=digest.hexdigest()[:32],
    )
    session.add(video)
    session.commit()
    LOGGER.info("Загружено видео %s (%.1f МБ)", video.original_name, size / 1024 / 1024)
    return {"video": video_view(video)}


@router.delete("/{video_id}")
def delete_video(
    video_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    video = session.get(Video, video_id)
    if video is None:
        raise NotFound("Видеофайл не найден.", "video_not_found")

    from app.models import Source

    used_by = session.scalars(select(Source).where(Source.video_id == video_id)).first()
    if used_by is not None:
        raise AppError(
            "video_in_use",
            f"Файл используется источником «{used_by.name}». Сначала замените файл у источника.",
            409,
        )

    path = get_settings().video_dir / video.stored_name
    path.unlink(missing_ok=True)
    session.delete(video)
    session.commit()
    return {"ok": True}

"""Источники видео: список, параметры, разметка и управление."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_session
from app.core.errors import AppError
from app.cv.markup import markup_to_dict
from app.cv.video_source import VideoUnavailable, probe_stream, probe_video
from app.models import User
from app.schemas.requests import MarkupRequest, SourceCreate, SourceUpdate
from app.schemas.views import source_view
from app.services import sources as sources_service
from app.services.manager import runtime_manager

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("")
def list_sources(
    _user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    sources = sources_service.list_sources(session)
    return {
        "sources": [
            source_view(session, source, runtime_manager.snapshot(source.id)) for source in sources
        ],
        "dataStatus": runtime_manager.data_status(
            sources_service.countable_sources(session), len(sources)
        ),
    }


@router.post("")
def create_source(
    payload: SourceCreate,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    source = sources_service.create_source(session, payload.model_dump(exclude_none=True))
    session.commit()
    runtime_manager.sync_sources()
    # Без разметки считается только число людей в кадре — интерфейс сразу
    # предлагает перейти к ней (ТЗ, раздел 5.7.1).
    return {
        "source": source_view(session, source, include_markup=True),
        "nextStep": "markup" if sources_service.has_signal_source(source) else "video",
    }


@router.get("/{source_id}")
def get_source(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    source = sources_service.get_source(session, source_id, include_deleted=True)
    return {
        "source": source_view(
            session, source, runtime_manager.snapshot(source_id), include_markup=True
        )
    }


@router.patch("/{source_id}")
def update_source(
    source_id: int,
    payload: SourceUpdate,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    previous_video = sources_service.get_source(session, source_id).video_id
    source = sources_service.update_source(session, source_id, payload.model_dump(exclude_unset=True))
    session.commit()
    runtime_manager.restart_source(source_id)

    markup = sources_service.get_markup(session, source_id)
    video_replaced = "video_id" in payload.model_dump(exclude_unset=True) and (
        previous_video != source.video_id
    )
    return {
        "source": source_view(session, source, runtime_manager.snapshot(source_id), markup, True),
        # Разметка привязана к кадру: после смены файла её нужно проверить.
        "warning": (
            "Файл заменён. Разметка может не подойти к новому видео — проверьте её."
            if video_replaced and not markup.is_empty
            else None
        ),
    }


@router.delete("/{source_id}")
def delete_source(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    source = sources_service.delete_source(session, source_id)
    session.commit()
    runtime_manager.stop_source(source_id)
    return {
        "ok": True,
        "message": (
            f"Источник «{source.name}» удалён. Накопленные данные и события остались "
            "в аналитике и журнале с пометкой «источник удалён»."
        ),
    }


@router.post("/{source_id}/enable")
def enable_source(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    source = sources_service.update_source(session, source_id, {"enabled": True})
    session.commit()
    runtime_manager.restart_source(source_id)
    return {"source": source_view(session, source, runtime_manager.snapshot(source_id))}


@router.post("/{source_id}/disable")
def disable_source(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    source = sources_service.update_source(session, source_id, {"enabled": False})
    session.commit()
    runtime_manager.stop_source(source_id)
    return {"source": source_view(session, source)}


@router.post("/{source_id}/check")
def check_source(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Проверка доступности по кнопке: файл или поток читается, вот его параметры."""
    source = sources_service.get_source(session, source_id)
    if sources_service.is_stream(source):
        if not source.stream_url:
            return {"ok": False, "message": "Не указана ссылка на поток."}
        try:
            info, _image = probe_stream(source.stream_url)
        except VideoUnavailable as error:
            return {"ok": False, "message": str(error)}
        return {
            "ok": True,
            "message": "Поток доступен, кадры приходят.",
            "stream": {"resolution": info.resolution, "fps": round(info.fps, 2)},
        }

    path = sources_service.video_path(source.video)
    if path is None:
        return {"ok": False, "message": "Источнику не назначен видеофайл."}

    try:
        info = probe_video(path)
    except VideoUnavailable as error:
        return {"ok": False, "message": str(error)}

    return {
        "ok": True,
        "message": "Файл доступен и читается.",
        "video": {
            "name": path.name,
            "durationSeconds": round(info.duration_seconds, 2),
            "resolution": info.resolution,
            "fps": round(info.fps, 2),
        },
    }


@router.post("/{source_id}/restart")
def restart_source(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    sources_service.get_source(session, source_id)
    runtime_manager.restart_source(source_id)
    return {"ok": True, "message": "Анализ источника перезапущен."}


@router.post("/{source_id}/restart-playback")
def restart_playback(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    """«Запустить с начала»: файл пойдёт заново, круг закроется."""
    sources_service.get_source(session, source_id)
    if not runtime_manager.restart_playback(source_id):
        raise AppError("source_not_running", "Источник сейчас не анализируется.", 409)
    return {"ok": True, "message": "Файл запущен с начала."}


# --- разметка ---------------------------------------------------------------


@router.get("/{source_id}/geometry")
def get_geometry(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    sources_service.get_source(session, source_id)
    markup = sources_service.get_markup(session, source_id)
    return {"markup": markup_to_dict(markup)}


@router.put("/{source_id}/geometry")
def put_geometry(
    source_id: int,
    payload: MarkupRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    markup = sources_service.save_markup(
        session, source_id, payload.model_dump(), user.display_name or user.login
    )
    session.commit()
    # Разметка применяется сразу и влияет только на новые данные: история не
    # пересчитывается (ТЗ, раздел 5.7.2).
    runtime_manager.apply_markup(source_id, markup)
    source = sources_service.get_source(session, source_id)
    return {
        "markup": markup_to_dict(markup),
        "source": source_view(session, source, runtime_manager.snapshot(source_id), markup),
        "message": "Разметка сохранена и применяется к новым данным. История не пересчитывается.",
    }


@router.get("/{source_id}/frame")
def get_frame(
    source_id: int,
    position: float = Query(default=0.0, ge=0.0, alias="pos"),
    detect: bool = Query(default=True),
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Кадр для разметки и опорные точки людей на нём.

    Опорные точки показываются, чтобы было видно: линии и зоны рисуются по полу,
    а не по головам (ТЗ, раздел 5.7.2).
    """
    import cv2

    source = sources_service.get_source(session, source_id)
    if sources_service.is_stream(source):
        image, width, height = _stream_frame(source)
        position_seconds, duration_seconds = 0.0, 0.0
    else:
        path = sources_service.video_path(source.video)
        if path is None or not path.exists():
            raise AppError(
                "no_video",
                "У источника нет видеофайла, разметка невозможна.",
                409,
            )

        info = probe_video(path)
        capture = cv2.VideoCapture(str(path))
        try:
            target_frame = int(
                min(max(position, 0.0), max(info.duration_seconds - 0.1, 0.0)) * info.fps
            )
            capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ok, image = capture.read()
            if not ok:
                raise AppError("frame_unavailable", "Не удалось прочитать кадр.", 409)
        finally:
            capture.release()
        width, height = info.width, info.height
        position_seconds = target_frame / info.fps
        duration_seconds = info.duration_seconds

    anchors: list[list[float]] = []
    if detect:
        from app.cv.detector import shared_tracker
        from app.cv.geometry import bbox_anchor

        markup = sources_service.get_markup(session, source_id)
        from app.services.settings import load_settings

        tracker = shared_tracker(source.model_profile or load_settings(session).model_profile)
        for box in tracker.update(image):
            anchor = bbox_anchor(box.bbox, markup.anchor)
            anchors.append([round(anchor.x, 4), round(anchor.y, 4)])

    encoded, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not encoded:
        raise AppError("frame_unavailable", "Не удалось подготовить кадр.", 500)

    return {
        "image": "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("ascii"),
        "positionSeconds": round(position_seconds, 2),
        "durationSeconds": round(duration_seconds, 2),
        "width": width,
        "height": height,
        "isStream": sources_service.is_stream(source),
        "anchors": anchors,
    }


def _stream_frame(source) -> tuple[object, int, int]:
    """Кадр потока для разметки: свежий кадр работающего источника или разовое чтение."""
    if not source.stream_url:
        raise AppError("no_video", "Не указана ссылка на поток, разметка невозможна.", 409)

    image = runtime_manager.last_image(source.id)
    if image is None:
        try:
            _info, image = probe_stream(source.stream_url)
        except VideoUnavailable as error:
            raise AppError("frame_unavailable", str(error), 409) from error
    height, width = image.shape[:2]
    return image, width, height

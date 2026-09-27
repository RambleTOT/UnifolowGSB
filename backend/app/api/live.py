"""Живая часть: поток изображения и метаданные кадра.

Изображение и наложение идут разными путями: браузер получает кадры потоком,
а рамки, зоны, линии и засчитанные проходы — сообщениями по веб-сокету.
Поэтому переключатели наложения работают мгновенно и не требуют другого потока
(задание, раздел 8).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import current_user, websocket_user
from app.core.db import SessionFactory, get_session
from app.core.errors import AppError
from app.core.security import SESSION_COOKIE
from app.core.timeutil import now_utc
from app.models import User
from app.services import sources as sources_service
from app.services.manager import runtime_manager

LOGGER = logging.getLogger(__name__)
router = APIRouter(tags=["live"])

BOUNDARY = "uniflow-frame"
# Частота опроса свежего кадра: файл идёт с обычной частотой, чаще смысла нет.
POLL_SECONDS = 0.04
SYSTEM_PULSE_SECONDS = 5.0


@router.get("/api/sources/{source_id}/snapshot.jpg")
def snapshot(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    sources_service.get_source(session, source_id)
    jpeg = runtime_manager.live_jpeg(source_id)
    if jpeg is None:
        raise AppError("no_frame", "Кадров от источника пока нет.", 409)
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/api/sources/{source_id}/analysis.jpg")
def analysis_frame(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    """Кадр режима «Точный анализ»: именно его обработала модель."""
    sources_service.get_source(session, source_id)
    jpeg, frame_index = runtime_manager.analysis_jpeg(source_id)
    if jpeg is None:
        raise AppError(
            "no_analysis_frame",
            "Модель ещё не обработала ни одного кадра.",
            409,
        )
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"X-Frame-Index": str(frame_index)},
    )


@router.get("/api/sources/{source_id}/stream.mjpg")
def stream(
    source_id: int,
    _user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    sources_service.get_source(session, source_id)

    async def frames():
        last: bytes | None = None
        while True:
            jpeg = runtime_manager.live_jpeg(source_id)
            if jpeg is not None and jpeg is not last:
                last = jpeg
                yield (
                    f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode("ascii") + jpeg + b"\r\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        frames(),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={"Cache-Control": "no-store"},
    )


@router.websocket("/ws/sources/{source_id}")
async def source_socket(websocket: WebSocket, source_id: int) -> None:
    """Метаданные кадра: рамки, зоны, линии, счётчики и засчитанные проходы."""
    session = SessionFactory()
    try:
        user = websocket_user(websocket.cookies.get(SESSION_COOKIE), session)
    finally:
        session.close()

    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    last_frame = -2
    try:
        while True:
            snapshot = runtime_manager.snapshot(source_id)
            if snapshot is None:
                await websocket.send_json(
                    {
                        "sourceId": source_id,
                        "status": "offline",
                        "error": "Источник сейчас не анализируется.",
                        "updatedAt": now_utc().isoformat(),
                    }
                )
                await asyncio.sleep(1.0)
                continue

            if snapshot.frame_index != last_frame:
                last_frame = snapshot.frame_index
                await websocket.send_json(snapshot.to_message())
            await asyncio.sleep(POLL_SECONDS)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        LOGGER.exception("Веб-сокет источника %s оборвался", source_id)
        return


@router.websocket("/ws/system")
async def system_socket(websocket: WebSocket) -> None:
    """Пульс сервера: состояние источников и признак живой связи.

    По нему интерфейс отличает «данные не идут» от «нет связи с сервером»
    (ТЗ, раздел 4.3).
    """
    session = SessionFactory()
    try:
        user = websocket_user(websocket.cookies.get(SESSION_COOKIE), session)
    finally:
        session.close()

    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    try:
        while True:
            session = SessionFactory()
            try:
                total = len(sources_service.list_sources(session))
                status = runtime_manager.data_status(
                    sources_service.countable_sources(session), total
                )
            finally:
                session.close()

            snapshots = runtime_manager.snapshots()
            await websocket.send_json(
                {
                    "type": "pulse",
                    "at": now_utc().isoformat(),
                    "dataStatus": status,
                    "sources": [
                        {
                            "sourceId": snapshot.source_id,
                            "name": snapshot.name,
                            "status": snapshot.status,
                            "modelStatus": snapshot.model_status,
                            "warmupPercent": snapshot.warmup_percent,
                            "analysisMode": snapshot.analysis_mode,
                            "error": snapshot.error,
                            "queue": snapshot.queue_size,
                            "peopleInFrame": snapshot.people_in_frame,
                            "entriesToday": snapshot.entries_today,
                            "exitsToday": snapshot.exits_today,
                            "insideNow": snapshot.inside_now,
                        }
                        for snapshot in snapshots.values()
                    ],
                }
            )
            await asyncio.sleep(SYSTEM_PULSE_SECONDS)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        LOGGER.exception("Системный веб-сокет оборвался")
        return

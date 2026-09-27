"""Демо-режим: сборка и очистка синтетической истории."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_session, session_scope
from app.core.timeutil import now_utc
from app.models import User
from app.services import demo

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/demo", tags=["demo"])

_lock = threading.Lock()
_state = {"running": False, "generatedAt": None, "error": None}


def _generate_in_background() -> None:
    try:
        with session_scope() as session:
            demo.generate(session)
        _state["generatedAt"] = now_utc().isoformat()
        _state["error"] = None
    except Exception as error:  # noqa: BLE001 — ошибка должна дойти до интерфейса
        LOGGER.exception("Не удалось собрать демо-данные")
        _state["error"] = str(error)
    finally:
        _state["running"] = False


def ensure_demo_data() -> bool:
    """Запустить сборку, если демо-истории ещё нет. Возвращает «уже готово»."""
    with session_scope() as session:
        if demo.has_demo_data(session):
            return True

    with _lock:
        if _state["running"]:
            return False
        _state["running"] = True

    threading.Thread(target=_generate_in_background, name="demo-generate", daemon=True).start()
    return False


@router.get("/status")
def status(
    _user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    ready = demo.has_demo_data(session)
    return {
        "ready": ready,
        "running": bool(_state["running"]),
        "generatedAt": _state["generatedAt"],
        "error": _state["error"],
    }


@router.post("/generate")
def generate(
    _user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    ready = ensure_demo_data()
    return {
        "ready": ready,
        "running": bool(_state["running"]),
        "message": "Демо-данные уже готовы."
        if ready
        else "Собираем демо-историю за 30 суток, это занимает несколько секунд.",
    }


@router.post("/clear")
def clear(
    _user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    demo.clear(session)
    session.commit()
    _state["generatedAt"] = None
    return {"ok": True, "message": "Демо-данные удалены. Реальные данные не затронуты."}

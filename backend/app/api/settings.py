"""Системные настройки."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_session
from app.models import User
from app.schemas.requests import SettingsUpdate
from app.services import settings as settings_service
from app.services.manager import runtime_manager

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _view(values: settings_service.SystemSettings) -> dict:
    return {
        "values": values.as_dict(),
        "bounds": settings_service.SystemSettings.BOUNDS,
    }


@router.get("")
def read_settings(
    _user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    return _view(settings_service.load_settings(session))


@router.put("")
def write_settings(
    payload: SettingsUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    current = settings_service.load_settings(session)
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(current, key, value)

    saved = settings_service.save_settings(session, current, user.display_name or user.login)
    session.commit()

    # Смена модели или параметров анализа перезапускает источники: они на время
    # уходят в «модель прогревается» (ТЗ, раздел 5.8).
    restart_required = bool(
        {"model_profile", "tracker", "confidence", "aggregation_seconds"} & set(changes)
    )
    if restart_required:
        runtime_manager.sync_sources()
        for source_id in list(runtime_manager.snapshots()):
            runtime_manager.restart_source(source_id)

    return {
        **_view(saved),
        "restarted": restart_required,
        "message": (
            "Настройки сохранены. Анализ перезапускается, источники ненадолго перейдут "
            "в состояние «модель прогревается»."
            if restart_required
            else "Настройки сохранены и действуют для новых данных."
        ),
    }


@router.post("/reset")
def reset_settings(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    saved = settings_service.reset_settings(session, user.display_name or user.login)
    session.commit()
    runtime_manager.sync_sources()
    return {**_view(saved), "message": "Значения возвращены к исходным."}

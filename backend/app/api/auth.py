"""Вход, выход и личные параметры учётной записи."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.security import (
    SESSION_COOKIE,
    SESSION_MAX_AGE_SECONDS,
    issue_session,
    login_rate_limiter,
    verify_password,
)
from app.core.timeutil import now_utc
from app.models import User
from app.schemas.requests import LoginRequest, ProfileUpdate
from app.schemas.views import user_view

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    client = request.client.host if request.client else "unknown"
    key = f"{payload.login.lower()}|{client}"

    blocked_for = login_rate_limiter.check(key)
    if blocked_for > 0:
        raise AppError(
            "too_many_attempts",
            f"Слишком много попыток входа. Повторите через {int(blocked_for // 60) + 1} мин.",
            429,
        )

    user = session.scalar(select(User).where(User.login == payload.login.strip()))
    # Сообщение одинаковое для неверного логина и неверного пароля: подсказывать,
    # что именно не так, значит помогать перебору.
    if user is None or not verify_password(user.password_hash, payload.password):
        login_rate_limiter.register_failure(key)
        raise AppError("invalid_credentials", "Неверный логин или пароль.", 401)

    login_rate_limiter.reset(key)
    user.last_login_at = now_utc()
    session.commit()

    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user.id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=not get_settings().is_local,
    )
    LOGGER.info("Вход пользователя %s", user.login)
    return {"user": user_view(user)}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": user_view(user)}


@router.patch("/me")
def update_me(
    payload: ProfileUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Личные параметры применяются сразу, без отдельного сохранения."""
    data = payload.model_dump(exclude_none=True)
    for field_name, value in data.items():
        setattr(user, field_name, value)
    session.add(user)
    session.commit()

    demo_ready = None
    if data.get("dataset") == "demo":
        from app.api.demo import ensure_demo_data

        demo_ready = ensure_demo_data()

    return {"user": user_view(user), "demoReady": demo_ready}

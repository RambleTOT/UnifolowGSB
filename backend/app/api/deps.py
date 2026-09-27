"""Зависимости API: текущий пользователь и сессия базы."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import Unauthorized
from app.core.security import SESSION_COOKIE, read_session
from app.models import User


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Все запросы, кроме входа, требуют сессии (задание, раздел 10)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized()

    user_id = read_session(token)
    if user_id is None:
        raise Unauthorized("Сессия истекла. Войдите заново.", "session_expired")

    user = session.get(User, user_id)
    if user is None:
        raise Unauthorized("Учётная запись больше не существует.", "user_missing")
    return user


def websocket_user(token: str | None, session: Session) -> User | None:
    """Проверка сессии для веб-сокета: cookie приходит в заголовке соединения."""
    if not token:
        return None
    user_id = read_session(token)
    if user_id is None:
        return None
    return session.get(User, user_id)

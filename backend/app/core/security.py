"""Вход в систему: хранение паролей, сессия и защита от перебора."""

from __future__ import annotations

import logging
import secrets
import string
import time
from dataclasses import dataclass, field
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings

LOGGER = logging.getLogger(__name__)

SESSION_COOKIE = "uniflow_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError):
        return False


def generate_password(length: int = 16) -> str:
    """Пароль первой учётной записи: печатается в консоль один раз."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="uniflow-session")


def issue_session(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session(token: str) -> int | None:
    try:
        payload = _serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    return payload.get("uid")


@dataclass
class _Attempts:
    count: int = 0
    first_at: float = field(default_factory=time.monotonic)
    blocked_until: float = 0.0


class LoginRateLimiter:
    """Ограничение частоты попыток входа.

    Сообщение об ошибке не раскрывает, что именно неверно, поэтому перебор
    должен упираться в паузу, а не в подсказку.
    """

    def __init__(self, limit: int = 10, window_seconds: float = 300.0, block_seconds: float = 300.0):
        self.limit = limit
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._attempts: dict[str, _Attempts] = {}
        self._lock = Lock()

    def check(self, key: str) -> float:
        """Сколько секунд ещё нельзя пробовать. 0 — можно."""
        with self._lock:
            state = self._attempts.get(key)
            if state is None:
                return 0.0
            now = time.monotonic()
            if state.blocked_until > now:
                return state.blocked_until - now
            return 0.0

    def register_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            state = self._attempts.get(key)
            if state is None or now - state.first_at > self.window_seconds:
                state = _Attempts()
                self._attempts[key] = state
            state.count += 1
            if state.count >= self.limit:
                state.blocked_until = now + self.block_seconds
                LOGGER.warning("Вход временно заблокирован для %s", key)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


login_rate_limiter = LoginRateLimiter()

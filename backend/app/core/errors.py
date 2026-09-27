"""Единый формат ошибок.

Ответ об ошибке несёт код для интерфейса и текст на русском, пригодный для
показа пользователю: сообщение должно объяснять, что случилось и что делать
(ТЗ, раздел 4.7).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = status.HTTP_400_BAD_REQUEST,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


class NotFound(AppError):
    def __init__(self, message: str = "Объект не найден.", code: str = "not_found") -> None:
        super().__init__(code, message, status.HTTP_404_NOT_FOUND)


class Unauthorized(AppError):
    def __init__(self, message: str = "Нужно войти в систему.", code: str = "unauthorized") -> None:
        super().__init__(code, message, status.HTTP_401_UNAUTHORIZED)


class Conflict(AppError):
    def __init__(self, message: str, code: str = "conflict", details: dict | None = None) -> None:
        super().__init__(code, message, status.HTTP_409_CONFLICT, details)


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


LOGGER = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=error.http_status,
            content=error_body(error.code, error.message, error.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        fields = {}
        for item in error.errors():
            location = [str(part) for part in item["loc"] if part not in ("body", "query")]
            fields[".".join(location) or "запрос"] = item.get("msg", "Неверное значение")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(
                "validation_error",
                "Проверьте заполненные поля: часть значений не подходит.",
                {"fields": fields},
            ),
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        """Непредвиденный сбой тоже должен объяснять себя по-человечески."""
        LOGGER.exception("Непредвиденная ошибка запроса")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(
                "internal_error",
                "Внутренняя ошибка сервера. Повторите попытку; если повторится — посмотрите журнал сервера.",
            ),
        )

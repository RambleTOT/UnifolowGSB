"""Точка входа приложения."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    analytics,
    auth,
    demo,
    events,
    health,
    live,
    notifications,
    reports,
    search,
    settings as settings_api,
    sources,
    videos,
)
from app.core.config import get_settings
from app.core.db import init_database, session_scope
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.services.bootstrap import bootstrap
from app.services.manager import runtime_manager

LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings = get_settings()
    LOGGER.info("UniFlow запускается: окружение %s, часовой пояс %s", settings.env, settings.timezone)

    init_database()
    with session_scope() as session:
        bootstrap(session)

    runtime_manager.start()
    try:
        yield
    finally:
        runtime_manager.stop()


app = FastAPI(
    title="UniFlow Analytics",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(sources.router)
app.include_router(videos.router)
app.include_router(settings_api.router)
app.include_router(analytics.router)
app.include_router(demo.router)
app.include_router(events.router)
app.include_router(notifications.router)
app.include_router(reports.router)
app.include_router(search.router)
app.include_router(live.router)


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """Любой адрес интерфейса отдаёт приложение: маршруты разбирает фронтенд."""
        candidate = FRONTEND_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIR / "index.html")

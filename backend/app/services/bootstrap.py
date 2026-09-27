"""Первый старт: учётная запись, источники и видео «из коробки».

Задача — чтобы после запуска система не встречала пользователя пустотой:
учётная запись есть, источники из ТЗ созданы, а видеофайлы с разметкой,
лежащие в каталоге видео, уже разобраны по источникам (задание, раздел 6.4).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generate_password, hash_password
from app.cv.markup import markup_from_dict, markup_to_dict, validate_markup
from app.cv.video_source import VideoUnavailable, probe_video
from app.models import Geometry, Source, User, Video

LOGGER = logging.getLogger(__name__)

# Стартовый набор источников (ТЗ, раздел 3.1). Видео у них пока нет — это
# нормальное состояние, а не сбой.
DEFAULT_SOURCES = [
    {"name": "Столовая", "scope": "canteen", "location": "Вход в столовую",
     "tags": ["столовая", "вход"]},
    {"name": "Раздача", "scope": "canteen", "location": "Линия раздачи",
     "tags": ["столовая", "очередь"]},
    {"name": "КПП 1", "scope": "gate", "location": "Основной проход",
     "tags": ["кпп", "основной"]},
    {"name": "КПП 2", "scope": "gate", "location": "Резервный проход",
     "tags": ["кпп", "резервный"]},
]


def ensure_admin(session: Session) -> str | None:
    """Создать первую учётную запись. Пароль печатается один раз."""
    settings = get_settings()
    if session.scalar(select(func.count()).select_from(User)):
        return None

    password = settings.admin_password.strip() or generate_password()
    generated = not settings.admin_password.strip()

    user = User(
        login=settings.admin_login,
        password_hash=hash_password(password),
        display_name="Администратор",
        profile="admin",
    )
    session.add(user)
    session.flush()

    if generated:
        LOGGER.warning(
            "\n%s\nСоздана учётная запись: %s\nПароль: %s\nСохраните его: больше он не появится.\n%s",
            "=" * 64,
            user.login,
            password,
            "=" * 64,
        )
        return password

    LOGGER.info("Создана учётная запись %s с паролем из .env", user.login)
    return None


def ensure_sources(session: Session) -> list[Source]:
    if session.scalar(select(func.count()).select_from(Source)):
        return list(session.scalars(select(Source)))

    created = []
    for payload in DEFAULT_SOURCES:
        source = Source(**payload, enabled=True, status="offline")
        session.add(source)
        created.append(source)
    session.flush()
    LOGGER.info("Созданы стартовые источники: %s", ", ".join(s.name for s in created))
    return created


def _register_video(session: Session, path: Path) -> Video | None:
    """Завести запись о видеофайле, лежащем в каталоге видео."""
    try:
        info = probe_video(path)
    except VideoUnavailable as error:
        LOGGER.warning("Видео %s не читается: %s", path.name, error)
        return None

    video = Video(
        original_name=path.name,
        stored_name=path.name,
        size_bytes=path.stat().st_size,
        duration_seconds=info.duration_seconds,
        width=info.width,
        height=info.height,
        fps=info.fps,
    )
    session.add(video)
    session.flush()
    return video


def _apply_markup(session: Session, source: Source, markup_path: Path) -> None:
    """Перенести разметку из файла рядом с видео в базу."""
    try:
        payload = json.loads(markup_path.read_text(encoding="utf-8"))
        markup = markup_from_dict(payload)
    except (OSError, ValueError, KeyError) as error:
        LOGGER.warning("Разметку %s прочитать не удалось: %s", markup_path.name, error)
        return

    if validate_markup(markup):
        LOGGER.warning("Разметка %s не прошла проверку и не применена", markup_path.name)
        return

    session.add(Geometry(source_id=source.id, payload=markup_to_dict(markup), updated_by="система"))
    LOGGER.info("Источнику «%s» назначена разметка из %s", source.name, markup_path.name)


def _markup_owner(markup_path: Path) -> str | None:
    """Имя источника, записанное в самой разметке полем `source`."""
    if not markup_path.exists():
        return None
    try:
        payload = json.loads(markup_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    owner = payload.get("source")
    return str(owner).strip() if isinstance(owner, str) and owner.strip() else None


def ensure_demo_videos(session: Session) -> None:
    """Подхватить лежащие рядом видеофайлы, чтобы система считала с первого старта.

    Кому достанется видео, написано в самой разметке полем `source`; если поля
    нет, файл отдаётся первому источнику, у которого видео ещё не назначено.
    Так один и тот же каталог `data/videos` разворачивает рабочий стенд и на
    машине разработчика, и на сервере (задание, раздел 6.4).
    """
    settings = get_settings()
    if session.scalar(select(func.count()).select_from(Video)):
        return

    sources = list(session.scalars(select(Source).order_by(Source.id)))
    if not sources:
        return
    by_name = {source.name.casefold(): source for source in sources}

    candidates = sorted(
        path
        for path in settings.video_dir.glob("*")
        if path.suffix.lower() in settings.allowed_video_suffixes and ".annotated" not in path.name
    )
    for path in candidates:
        markup_path = path.with_suffix(".markup.json")
        owner = _markup_owner(markup_path)
        source = by_name.get(owner.casefold()) if owner else None
        if source is None:
            if owner:
                LOGGER.warning("Разметка %s ссылается на источник «%s», которого нет", markup_path.name, owner)
            source = next(
                (
                    item
                    for item in sources
                    if item.video_id is None and item.connection_type != "stream"
                ),
                None,
            )
        if source is None or source.video_id is not None:
            continue

        video = _register_video(session, path)
        if video is None:
            continue
        source.video_id = video.id
        LOGGER.info("Источнику «%s» назначено видео %s", source.name, path.name)
        if markup_path.exists():
            _apply_markup(session, source, markup_path)


def ensure_demo_streams(session: Session) -> None:
    """Подключить прямые потоки из описаний `<имя>.stream.json` в каталоге видео.

    Описание — это та же разметка, что у роликов, плюс ссылка на поток и
    профиль модели. Источник, которому уже назначены видео или поток, не
    трогается: повторный старт ничего не перезаписывает.
    """
    settings = get_settings()
    sources = {source.name.casefold(): source for source in session.scalars(select(Source))}
    for path in sorted(settings.video_dir.glob("*.stream.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            owner = str(payload["source"]).strip()
            url = str(payload["stream_url"]).strip()
        except (OSError, ValueError, KeyError) as error:
            LOGGER.warning("Описание потока %s прочитать не удалось: %s", path.name, error)
            continue

        source = sources.get(owner.casefold())
        if source is None:
            LOGGER.warning("Описание %s ссылается на источник «%s», которого нет", path.name, owner)
            continue
        if source.video_id is not None or source.stream_url:
            continue

        source.connection_type = "stream"
        source.stream_url = url
        if payload.get("model_profile"):
            source.model_profile = str(payload["model_profile"])
        if payload.get("location"):
            source.location = str(payload["location"])
        session.flush()
        LOGGER.info("Источнику «%s» подключён прямой поток из %s", source.name, path.name)
        _apply_markup(session, source, path)


def bootstrap(session: Session) -> None:
    ensure_admin(session)
    ensure_sources(session)
    # Сначала потоки: они занимают свои источники по имени, и ролик без хозяина
    # уже не достанется источнику, который должен смотреть камеру.
    ensure_demo_streams(session)
    ensure_demo_videos(session)

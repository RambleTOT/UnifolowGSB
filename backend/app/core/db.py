"""Хранилище: SQLite в режиме WAL.

Продукт демонстрационный и живёт одним процессом, поэтому база — файл рядом с
приложением. WAL нужен, чтобы фоновая запись агрегатов не блокировала чтение
аналитики.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Base

LOGGER = logging.getLogger(__name__)

settings = get_settings()

engine = create_engine(
    settings.database_url,
    future=True,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record) -> None:
    # Встроенный lower() в SQLite умеет только латиницу: «Раздача» и «раздача»
    # для него разные слова. Заодно приравниваем «ё» к «е»: люди пишут и так, и так.
    dbapi_connection.create_function(
        "search_key",
        1,
        lambda value: value.lower().replace("ё", "е") if isinstance(value, str) else value,
    )

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)


# Колонки, добавленные после первого выпуска. `create_all` создаёт только новые
# таблицы, поэтому в уже существующую базу их докладываем сами — данные при
# этом не трогаются.
ADDED_COLUMNS = {
    "sources": {"stream_url": "VARCHAR(1000)"},
}


def init_database() -> None:
    """Схема создаётся при старте: полноценные миграции для демо избыточны."""
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            present = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
            for column, ddl in columns.items():
                if column not in present:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                    LOGGER.info("В таблицу %s добавлена колонка %s", table, column)
    LOGGER.info("База готова: %s", settings.database_url)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """Зависимость FastAPI."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()

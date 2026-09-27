"""Менеджер рабочих потоков: кто сейчас крутится и что с ним происходит.

Менеджер держит по потоку на включённый источник с видео, сводит их состояние
для индикатора состояния данных (ТЗ, раздел 4.3) и складывает записи в базу из
одного потока: у SQLite один писатель.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.timeutil import now_utc
from app.cv.markup import Markup
from app.models import DATASET_REAL, Event, Loop, Source
from app.services.aggregation import BucketPayload, apply_retention, persist_bucket, rebuild_rollups
from app.services.events import CloseEvent, EventEngine, OpenEvent, UpdateEvent
from app.services.runtime import LiveSnapshot, SourceWorker
from app.services.settings import load_settings
from app.services.sources import build_runtime_config, touch_status

LOGGER = logging.getLogger(__name__)

# Как часто обновляются свёртки и чистятся старые данные. Минутные свёртки
# нужны аналитике, поэтому собираем их чаще, чем раз в минуту: иначе первые
# минуты работы выглядят как «данных нет».
ROLLUP_INTERVAL_SECONDS = 30
RETENTION_INTERVAL_SECONDS = 3600
# Статус источника пишется в базу при изменении и не чаще этого — чтобы поток
# кадров не превратился в поток записей.
STATUS_WRITE_INTERVAL_SECONDS = 15


@dataclass
class _StatusState:
    status: str
    error: str | None
    written_at: float


class RuntimeManager:
    def __init__(self) -> None:
        self._workers: dict[int, SourceWorker] = {}
        self._lock = threading.RLock()
        self._queue: Queue[tuple[str, Any]] = Queue(maxsize=10000)
        self._stop = threading.Event()
        self._writer: threading.Thread | None = None
        self._maintenance: threading.Thread | None = None
        self._statuses: dict[int, _StatusState] = {}
        self._event_engines: dict[int, EventEngine] = {}
        # Открытые эпизоды: по одному на источник и тип события.
        self._active_events: dict[tuple[int, str], int] = {}
        self._started = False

    # --- запуск и остановка -------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()
        self._writer = threading.Thread(target=self._writer_loop, name="db-writer", daemon=True)
        self._writer.start()
        self._maintenance = threading.Thread(
            target=self._maintenance_loop, name="maintenance", daemon=True
        )
        self._maintenance.start()
        self._close_dangling_events()
        self._refresh_rollups()
        self.sync_sources()
        LOGGER.info("Менеджер источников запущен")

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join(timeout=5.0)
        if self._writer is not None:
            self._writer.join(timeout=5.0)
        self._started = False
        LOGGER.info("Менеджер источников остановлен")

    # --- управление источниками ---------------------------------------------

    def sync_sources(self) -> None:
        """Привести работающие потоки в соответствие с тем, что в базе."""
        with session_scope() as session:
            sources = list(
                session.scalars(
                    select(Source).where(Source.deleted_at.is_(None), Source.enabled.is_(True))
                )
            )
            wanted: dict[int, Any] = {}
            for source in sources:
                config = build_runtime_config(session, source)
                if config is not None:
                    wanted[source.id] = config
                    continue
                # Причина важна: «видео не назначено» и «файл пропал» — разные
                # состояния с разными следующими шагами для пользователя.
                if source.connection_type == "stream":
                    touch_status(session, source.id, "offline", "Не указана ссылка на поток.")
                elif source.video_id is None:
                    touch_status(session, source.id, "offline", "Видео не назначено.")
                else:
                    name = source.video.original_name if source.video else "файл"
                    touch_status(
                        session, source.id, "offline", f"Видеофайл не найден: {name}"
                    )

        with self._lock:
            for source_id in list(self._workers):
                if source_id not in wanted:
                    self._stop_worker(source_id)
            for source_id, config in wanted.items():
                if source_id not in self._workers:
                    self._start_worker(config)

    def restart_source(self, source_id: int) -> None:
        """Перезапустить поток источника: применить изменившиеся параметры."""
        with self._lock:
            self._stop_worker(source_id)
        with session_scope() as session:
            source = session.get(Source, source_id)
            if source is None or source.deleted_at is not None or not source.enabled:
                return
            config = build_runtime_config(session, source)
        if config is not None:
            with self._lock:
                self._start_worker(config)

    def stop_source(self, source_id: int) -> None:
        with self._lock:
            self._stop_worker(source_id)

    def restart_playback(self, source_id: int) -> bool:
        worker = self._worker(source_id)
        if worker is None:
            return False
        worker.restart_playback()
        return True

    def apply_markup(self, source_id: int, markup: Markup) -> None:
        worker = self._worker(source_id)
        if worker is not None:
            worker.apply_markup(markup)

    def _start_worker(self, config) -> None:
        worker = SourceWorker(
            config,
            on_bucket=lambda payload: self._enqueue("bucket", payload),
            on_status=self._handle_status,
            on_loop=lambda *args: self._enqueue("loop", args),
        )
        self._workers[config.source_id] = worker
        worker.start()
        LOGGER.info("Источник %s: рабочий поток создан", config.source_id)

    def _stop_worker(self, source_id: int) -> None:
        worker = self._workers.pop(source_id, None)
        if worker is None:
            return
        worker.stop()
        worker.join(timeout=5.0)
        self._statuses.pop(source_id, None)
        LOGGER.info("Источник %s: рабочий поток остановлен", source_id)

    def _worker(self, source_id: int) -> SourceWorker | None:
        with self._lock:
            return self._workers.get(source_id)

    # --- состояние для интерфейса -------------------------------------------

    def snapshot(self, source_id: int) -> LiveSnapshot | None:
        worker = self._worker(source_id)
        return worker.snapshot() if worker is not None else None

    def snapshots(self) -> dict[int, LiveSnapshot]:
        with self._lock:
            return {source_id: worker.snapshot() for source_id, worker in self._workers.items()}

    def live_jpeg(self, source_id: int) -> bytes | None:
        worker = self._worker(source_id)
        return worker.live_jpeg() if worker is not None else None

    def analysis_jpeg(self, source_id: int) -> tuple[bytes | None, int]:
        worker = self._worker(source_id)
        return worker.analysis_jpeg() if worker is not None else (None, -1)

    def last_image(self, source_id: int):
        """Последний кадр, прошедший анализ: для разметки потока без переподключения."""
        worker = self._worker(source_id)
        return worker.last_image() if worker is not None else None

    def is_running(self, source_id: int) -> bool:
        return self._worker(source_id) is not None

    def data_status(self, countable: list[dict[str, Any]], total_sources: int) -> dict[str, Any]:
        """Индикатор состояния данных (ТЗ, раздел 4.3).

        В расчёт входят только включённые источники с назначенным видео:
        выключенный или пустой источник проблемой не считается. Источник,
        у которого поток даже не запустился, тоже попадает в список проблем —
        иначе он молча исчезнет из поля зрения оператора.
        """
        snapshots = self.snapshots()
        healthy = 0
        problems: list[dict[str, Any]] = []

        for row in countable:
            snapshot = snapshots.get(row["sourceId"])
            if snapshot is not None:
                status, error = snapshot.status, snapshot.error
            else:
                status, error = row.get("status", "offline"), row.get("error")
                if status == "online":
                    status = "offline"

            if status == "online":
                healthy += 1
            else:
                problems.append(
                    {
                        "sourceId": row["sourceId"],
                        "name": row["name"],
                        "status": status,
                        "error": error,
                    }
                )

        if not countable:
            state = "no_sources"
        elif healthy == 0:
            state = "no_data"
        elif healthy < len(countable):
            state = "partial"
        else:
            state = "ok"

        return {
            "state": state,
            "healthy": healthy,
            "countable": len(countable),
            "total": total_sources,
            "problems": problems,
        }

    # --- запись в базу ------------------------------------------------------

    def _enqueue(self, kind: str, payload: Any) -> None:
        try:
            self._queue.put_nowait((kind, payload))
        except Exception:  # noqa: BLE001 — очередь переполнена: лучше потерять интервал, чем встать
            LOGGER.warning("Очередь записи переполнена, интервал пропущен")

    def _handle_status(self, source_id: int, status: str, error: str | None) -> None:
        now = time.monotonic()
        state = self._statuses.get(source_id)
        changed = state is None or state.status != status or state.error != error
        stale = state is not None and now - state.written_at > STATUS_WRITE_INTERVAL_SECONDS
        if not changed and not stale:
            return
        self._statuses[source_id] = _StatusState(status, error, now)
        self._enqueue("status", (source_id, status, error, now_utc()))

    def _writer_loop(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                kind, payload = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                with session_scope() as session:
                    if kind == "bucket":
                        persist_bucket(session, payload)
                        self._evaluate_events(session, payload)
                    elif kind == "status":
                        source_id, status, error, at = payload
                        touch_status(session, source_id, status, error, at)
                    elif kind == "loop":
                        source_id, number, started_at, ended_at, entered, exited = payload
                        session.add(
                            Loop(
                                source_id=source_id,
                                loop_number=number,
                                started_at=started_at,
                                ended_at=ended_at,
                                entered=entered,
                                exited=exited,
                            )
                        )
            except Exception:  # noqa: BLE001 — писатель не должен умирать из-за одной записи
                LOGGER.exception("Не удалось записать %s", kind)

    # --- события ------------------------------------------------------------

    def _close_dangling_events(self) -> None:
        """Эпизоды прошлого запуска закрываем: следить за ними больше некому."""
        with session_scope() as session:
            hanging = session.scalars(
                select(Event).where(Event.ongoing.is_(True), Event.dataset == DATASET_REAL)
            ).all()
            for event in hanging:
                event.ongoing = False
                event.ended_at = event.ended_at or now_utc()
            if hanging:
                LOGGER.info("Закрыто незавершённых событий с прошлого запуска: %s", len(hanging))

    def _evaluate_events(self, session, payload: BucketPayload) -> None:
        source = session.get(Source, payload.source_id)
        if source is None:
            return

        engine = self._event_engines.get(source.id)
        settings = load_settings(session)
        if engine is None:
            engine = EventEngine(source_id=source.id, scope=source.scope, settings=settings)
            self._event_engines[source.id] = engine
        else:
            engine.update_settings(settings)

        for action in engine.observe(payload, source.name):
            if isinstance(action, OpenEvent):
                self._open_event(session, source, action, settings.save_event_snapshots)
            elif isinstance(action, UpdateEvent):
                self._update_event(session, source.id, action)
            elif isinstance(action, CloseEvent):
                self._close_event(session, source.id, action)

    def _open_event(self, session, source: Source, action: OpenEvent, save_snapshot: bool) -> None:
        position, loop_number = (None, None)
        worker = self._worker(source.id)
        if worker is not None:
            position, loop_number = worker.playback_position()

        event = Event(
            source_id=source.id,
            dataset=DATASET_REAL,
            type=action.type,
            severity=action.severity,
            title=action.title,
            description=action.description,
            started_at=action.started_at,
            ongoing=True,
            status="open",
            metric_value=action.metric_value,
            peak_value=action.metric_value,
            threshold=action.threshold,
            video_position_seconds=position,
            loop_number=loop_number,
        )
        session.add(event)
        session.flush()
        self._active_events[(source.id, action.type)] = event.id

        if save_snapshot and worker is not None:
            snapshot = worker.render_event_snapshot()
            if snapshot:
                directory = get_settings().snapshot_dir
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"event-{event.id}.jpg"
                path.write_bytes(snapshot)
                event.snapshot_path = path.name

        LOGGER.info(
            "Источник %s: событие «%s» (%s)", source.id, action.title, action.severity
        )

    def _update_event(self, session, source_id: int, action: UpdateEvent) -> None:
        event_id = self._active_events.get((source_id, action.type))
        if event_id is None:
            return
        event = session.get(Event, event_id)
        if event is None:
            return
        event.peak_value = max(event.peak_value, action.peak_value)
        event.metric_value = action.metric_value
        event.severity = action.severity

    def _close_event(self, session, source_id: int, action: CloseEvent) -> None:
        event_id = self._active_events.pop((source_id, action.type), None)
        if event_id is None:
            return
        event = session.get(Event, event_id)
        if event is None:
            return
        event.ongoing = False
        event.ended_at = action.ended_at
        LOGGER.info("Источник %s: событие «%s» завершилось", source_id, event.title)

    def _refresh_rollups(self) -> None:
        try:
            with session_scope() as session:
                rebuild_rollups(session)
        except Exception:  # noqa: BLE001 — свёртки не должны мешать старту
            LOGGER.exception("Не удалось обновить свёртки при старте")

    def _maintenance_loop(self) -> None:
        """Свёртки и срок хранения: фоном, чтобы аналитика отвечала быстро."""
        last_retention = 0.0
        while not self._stop.wait(ROLLUP_INTERVAL_SECONDS):
            try:
                with session_scope() as session:
                    rebuild_rollups(session)
                    from app.services.demo import top_up

                    added = top_up(session)
                    if added:
                        LOGGER.debug("Демо-набор дополнен: %s минут", added)
                    if time.monotonic() - last_retention > RETENTION_INTERVAL_SECONDS:
                        apply_retention(session, load_settings(session).retention_days)
                        last_retention = time.monotonic()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Фоновое обслуживание не выполнилось")


runtime_manager = RuntimeManager()

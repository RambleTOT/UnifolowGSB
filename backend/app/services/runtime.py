"""Рабочие потоки источников: воспроизведение, анализ и живое состояние.

Один источник — один поток. Он читает файл по кругу в темпе реального времени
или прямой поток с камеры, прогоняет кадры через детекцию и подсчёт, держит свежее состояние для
интерфейса и складывает метрики в интервалы. Запись в базу вынесена в
отдельный поток: у SQLite один писатель.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.core.timeutil import now_utc, utc_offset_hours
from app.cv.counting import CountingEngine, CountingParams, FrameResult, TrackObservation
from app.cv.detector import MODEL_PROFILES, TrackedBox, UltralyticsPersonTracker
from app.cv.markup import Markup
from app.cv.video_source import LiveStreamSource, VideoFileSource, VideoUnavailable, probe_video
from app.services.aggregation import Aggregator, BucketPayload
from app.services.precompute import PrecomputeJob, cache_file, cache_key, load_tracks

LOGGER = logging.getLogger(__name__)

# Насколько анализ может отставать от видео, прежде чем источник считается
# нестабильным (ТЗ, раздел 3.3).
DEGRADED_LATENCY_MS = 1500.0
DEGRADED_FPS_RATIO = 0.4
# Сколько кадров измеряется скорость, прежде чем режим `auto` выберет путь.
AUTO_PROBE_FRAMES = 24
AUTO_MIN_FPS = 8.0
# Во сне компьютера монотонные часы стоят, а настенные идут. Если между
# соседними кадрами настенное время ушло вперёд сильнее монотонного, был сон:
# все, кто был в кадре, получили бы ожидание длиной в этот сон.
HOST_SLEEP_GAP_SECONDS = 5.0
# Статус «в норме» / «нестабильно» меняется, только если новое состояние держится
# столько секунд. Иначе у источника на пороге (эфир на 3 кадр/с при пороге 3.2)
# статус мигал бы несколько раз в секунду — и в мониторинге, и в индикаторе данных.
HEALTH_HOLD_SECONDS = 5.0
# Первые минуты после запуска рабочего потока — прогрев: грузятся модели и кэши,
# эфир набирает буфер. Событие «Проблема с источником» в это время не заводится.
WARMUP_SECONDS = 120.0
# Кадр в JPEG нужен, только пока его кто-то смотрит: стена мониторинга просит
# снимок раз в 2 с, поток MJPEG — непрерывно. Без зрителей кодирование — чистые
# потери: у ролика 60 кадр/с это было 120 кодирований в секунду впустую.
JPEG_WANTED_SECONDS = 5.0
# Сколько ждать свежего кадра, если снимок попросили после простоя.
JPEG_FRESH_WAIT_SECONDS = 0.5


def host_slept(wall_gap: float, monotonic_gap: float) -> bool:
    return wall_gap - monotonic_gap > HOST_SLEEP_GAP_SECONDS


@dataclass
class SourceRuntimeConfig:
    source_id: int
    name: str
    scope: str
    video_path: Path | None
    markup: Markup
    # Задана — источник читает прямой поток с камеры, а не файл.
    stream_url: str | None = None
    model_profile: str = "standard"
    confidence: float = 0.25
    tracker: str = "bytetrack.yaml"
    device: str = "auto"
    analysis_mode: str = "auto"
    aggregation_seconds: int = 5
    cache_dir: Path = Path("data/cache")
    jpeg_quality: int = 72
    jpeg_max_width: int = 1280
    # Уже посчитанное за сегодня: перезапуск потока не начинает сутки заново.
    entries_today: int = 0
    exits_today: int = 0


@dataclass
class LiveSnapshot:
    """Свежее состояние источника — то, что уходит в интерфейс."""

    source_id: int
    name: str
    status: str = "offline"
    model_status: str = "unavailable"
    warmup_percent: float | None = None
    analysis_mode: str = "realtime"
    error: str | None = None
    is_stream: bool = False
    resolution: str | None = None

    frame_index: int = -1
    position_seconds: float = 0.0
    duration_seconds: float = 0.0
    loop_number: int = 1
    loop_entries: int = 0
    loop_exits: int = 0
    previous_loop_entries: int | None = None
    previous_loop_exits: int | None = None

    people_in_frame: int = 0
    people_in_zone: int = 0
    queue_size: int = 0
    entries_today: int = 0
    exits_today: int = 0
    inside_now: int = 0
    avg_wait_seconds: float | None = None

    fps: float = 0.0
    latency_ms: float = 0.0
    confidence: float | None = None

    objects: list[dict] = field(default_factory=list)
    crossings: list[dict] = field(default_factory=list)
    zones: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)
    updated_at: datetime | None = None

    def to_message(self) -> dict[str, Any]:
        """Сообщение кадра для живой части (задание, раздел 8)."""
        return {
            "sourceId": self.source_id,
            "name": self.name,
            "status": self.status,
            "modelStatus": self.model_status,
            "warmupPercent": self.warmup_percent,
            "analysisMode": self.analysis_mode,
            "error": self.error,
            "isStream": self.is_stream,
            "resolution": self.resolution,
            "frameIndex": self.frame_index,
            "positionSeconds": round(self.position_seconds, 2),
            "durationSeconds": round(self.duration_seconds, 2),
            "loop": {
                "number": self.loop_number,
                "entered": self.loop_entries,
                "exited": self.loop_exits,
                "previousEntered": self.previous_loop_entries,
                "previousExited": self.previous_loop_exits,
            },
            "metrics": {
                "peopleInFrame": self.people_in_frame,
                "peopleInZone": self.people_in_zone,
                "queue": self.queue_size,
                "entriesToday": self.entries_today,
                "exitsToday": self.exits_today,
                "insideNow": self.inside_now,
                "avgWaitSeconds": self.avg_wait_seconds,
            },
            "technical": {
                "fps": round(self.fps, 1),
                "latencyMs": round(self.latency_ms),
                "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            },
            "objects": self.objects,
            "crossings": self.crossings,
            "zones": self.zones,
            "lines": self.lines,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class SourceWorker(threading.Thread):
    """Поток одного источника."""

    def __init__(
        self,
        config: SourceRuntimeConfig,
        on_bucket: Callable[[BucketPayload], None],
        on_status: Callable[[int, str, str | None], None],
        on_loop: Callable[[int, int, datetime, datetime, int, int], None],
    ) -> None:
        super().__init__(name=f"source-{config.source_id}", daemon=True)
        self.config = config
        self._on_bucket = on_bucket
        self._on_status = on_status
        self._on_loop = on_loop

        self._stop_event = threading.Event()
        self._restart = threading.Event()
        self._lock = threading.Lock()
        self._snapshot = LiveSnapshot(
            source_id=config.source_id, name=config.name, is_stream=config.stream_url is not None
        )
        self._live_jpeg: bytes | None = None
        self._analysis_jpeg: bytes | None = None
        # До какого момента кадры кодируются в JPEG: продлевается каждым запросом.
        self._live_wanted_until = 0.0
        self._analysis_wanted_until = 0.0
        self._live_encoded_at = 0.0
        self._analysis_encoded_at = 0.0
        self._fresh_live = threading.Event()
        self._fresh_analysis = threading.Event()
        self._started_monotonic = time.monotonic()
        self._health_state = "online"
        self._health_candidate: str | None = None
        self._health_candidate_since = 0.0
        self._analysis_frame_index = -1
        # Последний обработанный кадр и его результат: из них собирается кадр
        # события с наложением (ТЗ, раздел 3.4).
        self._last_image = None
        self._last_result: FrameResult | None = None
        self._pending_markup: Markup | None = None

        self._engine = CountingEngine(
            lines=config.markup.lines,
            zones=config.markup.zones,
            params=config.markup.counting_params(CountingParams(anchor=config.markup.anchor)),
            timezone_offset_hours=utc_offset_hours(),
            inside_per_loop=config.stream_url is None,
        )
        self._engine.entries_today = config.entries_today
        self._engine.exits_today = config.exits_today
        self._aggregator = Aggregator(config.source_id, config.aggregation_seconds)
        self._tracker: UltralyticsPersonTracker | None = None
        self._precompute: PrecomputeJob | None = None
        self._precompute_target: Path | None = None
        self._cached_tracks: dict[int, list[TrackedBox]] | None = None
        self._loop_started_at = now_utc()

    # --- управление ---------------------------------------------------------

    def stop(self) -> None:
        self._stop_event.set()
        if self._precompute is not None:
            self._precompute.stop()

    def restart_playback(self) -> None:
        """«Запустить с начала»: файл начинается заново, круг закрывается."""
        self._restart.set()

    def apply_markup(self, markup: Markup) -> None:
        """Новая разметка применяется сразу и влияет только на новые данные."""
        with self._lock:
            self._pending_markup = markup
            self.config.markup = markup

    def snapshot(self) -> LiveSnapshot:
        with self._lock:
            return self._snapshot

    def live_jpeg(self) -> bytes | None:
        with self._lock:
            now = time.monotonic()
            self._live_wanted_until = now + JPEG_WANTED_SECONDS
            stale = now - self._live_encoded_at > 1.0
            if stale:
                self._fresh_live.clear()
        # После простоя кадр в памяти старый: даём потоку закодировать свежий.
        if stale:
            self._fresh_live.wait(JPEG_FRESH_WAIT_SECONDS)
        with self._lock:
            return self._live_jpeg

    def analysis_jpeg(self) -> tuple[bytes | None, int]:
        with self._lock:
            now = time.monotonic()
            self._analysis_wanted_until = now + JPEG_WANTED_SECONDS
            stale = now - self._analysis_encoded_at > 1.0
            if stale:
                self._fresh_analysis.clear()
        if stale:
            self._fresh_analysis.wait(JPEG_FRESH_WAIT_SECONDS)
        with self._lock:
            return self._analysis_jpeg, self._analysis_frame_index

    def last_image(self):
        with self._lock:
            return None if self._last_image is None else self._last_image.copy()

    def render_event_snapshot(self) -> bytes | None:
        """Кадр события: то же наложение, что видит оператор в мониторинге."""
        import cv2

        from app.cv.overlay import OverlayOptions, render_frame

        with self._lock:
            image = self._last_image
            result = self._last_result
            markup = self.config.markup

        if image is None or result is None:
            return None

        canvas = render_frame(
            image,
            result,
            lines=markup.lines,
            zones=markup.zones,
            options=OverlayOptions(show_counters=True),
        )
        ok, buffer = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buffer.tobytes() if ok else None

    def playback_position(self) -> tuple[float | None, int | None]:
        snapshot = self.snapshot()
        return snapshot.position_seconds, snapshot.loop_number

    # --- жизненный цикл -----------------------------------------------------

    def run(self) -> None:
        LOGGER.info("Источник %s: поток запущен", self.config.source_id)
        while not self._stop_event.is_set():
            try:
                self._run_once()
            except VideoUnavailable as error:
                self._fail("offline", str(error))
                self._stop_event.wait(5.0)
            except Exception as error:  # noqa: BLE001 — поток не должен умирать молча
                LOGGER.exception("Источник %s: сбой анализа", self.config.source_id)
                self._fail("degraded", f"Сбой анализа: {error}")
                self._stop_event.wait(3.0)
        self._flush_aggregator()
        LOGGER.info("Источник %s: поток остановлен", self.config.source_id)

    def _run_once(self) -> None:
        import cv2

        is_stream = self.config.stream_url is not None
        if is_stream:
            # Эфир нельзя посчитать заранее: у потока нет файла, только «сейчас».
            source = LiveStreamSource(self.config.stream_url)
            info = source.open()
            self._update(duration_seconds=0.0, error=None, resolution=info.resolution)
            # Кадры в буфере потока идут не чаще max_fps: от этого считаются
            # пропуски и порог «нестабилен».
            frame_rate = min(info.fps, source.max_fps)
        else:
            info = probe_video(self.config.video_path)
            self._update(
                duration_seconds=info.duration_seconds, error=None, resolution=info.resolution
            )
            frame_rate = info.fps

        tracker = self._ensure_tracker()
        mode = "realtime" if is_stream else self.config.analysis_mode
        # Режим показывается пользователю как справочная информация и должен
        # соответствовать действительности (задание, раздел 5.4).
        self._update(analysis_mode="realtime" if mode == "auto" else mode)
        # Видео начинает играть сразу: пользователь видит картинку, пока
        # готовится анализ (ТЗ, раздел 5.2, состояние «модель прогревается»).
        if mode == "precomputed":
            self._start_precompute(tracker)
        elif mode == "auto":
            self._update(model_status="warming_up")

        if not is_stream:
            source = VideoFileSource(self.config.video_path, loop=True, realtime=True)
            source.open()
        self._loop_started_at = now_utc()

        fps_ema: float | None = None
        previous_frame_at: float | None = None
        first_frame = True
        probe_frames = 0
        probe_spent = 0.0
        previous_clock: tuple[float, float] | None = None  # (настенное, монотонное)

        try:
            for frame in source.frames():
                if self._stop_event.is_set():
                    return

                if self._restart.is_set():
                    self._restart.clear()
                    if not is_stream:
                        self._close_loop()
                        self._engine.start_new_loop()
                    if self._tracker is not None and mode != "precomputed":
                        self._tracker.reset()
                    source.close()
                    return

                # Разрыв во времени — поток переподключился или прыгнул вперёд,
                # компьютер засыпал: люди ушли далеко, старые треки только
                # помешают, а незавершённые ожидания вобрали бы весь перерыв.
                wall_now, monotonic_now = time.time(), time.monotonic()
                slept = previous_clock is not None and host_slept(
                    wall_now - previous_clock[0], monotonic_now - previous_clock[1]
                )
                previous_clock = (wall_now, monotonic_now)
                if getattr(frame, "discontinuity", False) or slept:
                    if slept:
                        LOGGER.info("Источник %s: был сон компьютера, треки сброшены", self.config.source_id)
                    self._engine.reset_tracks()
                    if self._tracker is not None and mode != "precomputed":
                        self._tracker.reset()

                if frame.is_loop_start and not first_frame:
                    # Граница круга: сцена меняется скачком, но это не сбой и не
                    # уход людей из кадра — выходы здесь не засчитываются.
                    self._close_loop()
                    self._engine.start_new_loop()
                    if self._tracker is not None and mode != "precomputed":
                        self._tracker.reset()
                first_frame = False

                started = time.monotonic()
                self._publish_live_frame(frame.image, cv2)
                self._collect_precompute()

                self._apply_pending_markup()
                boxes = self._detect(frame, mode, tracker)

                finished = time.monotonic()
                spent = finished - started

                if mode == "auto":
                    probe_frames += 1
                    probe_spent += spent
                    if probe_frames >= AUTO_PROBE_FRAMES:
                        mode = self._choose_mode(probe_frames / probe_spent, frame_rate, tracker)

                # Частота кадров — это сколько кадров в секунду реально проходит
                # анализ, а не на что способна модель в лаборатории.
                if previous_frame_at is not None:
                    instant = 1.0 / max(1e-6, finished - previous_frame_at)
                    fps_ema = instant if fps_ema is None else fps_ema * 0.8 + instant * 0.2
                previous_frame_at = finished

                # Отставание: время обработки кадра плюс кадры, которые пришлось
                # пропустить, чтобы догнать воспроизведение.
                skipped_ms = frame.skipped * (1000.0 / frame_rate if frame_rate else 0.0)
                latency_ms = spent * 1000.0 + skipped_ms
                status = self._stable_health(self._health(fps_ema or 0.0, latency_ms, frame_rate))

                observations = [
                    TrackObservation(box.track_id, box.bbox, box.confidence) for box in boxes
                ]
                result = self._engine.process_frame(observations, time.time())

                self._publish_analysis_frame(frame.image, frame.index, cv2, result)
                self._update_from_result(
                    result,
                    frame=frame,
                    status=status,
                    fps=fps_ema or 0.0,
                    latency_ms=latency_ms,
                )
                self._accumulate(result, status, fps_ema or 0.0, latency_ms, frame.is_loop_start)
        finally:
            source.close()

    # --- анализ -------------------------------------------------------------

    def _ensure_tracker(self) -> UltralyticsPersonTracker:
        if self._tracker is None:
            profile = MODEL_PROFILES.get(self.config.model_profile, MODEL_PROFILES["standard"])
            self._tracker = UltralyticsPersonTracker(
                profile=self.config.model_profile,
                tracker=self.config.tracker,
                device=self.config.device,
                confidence=self.config.confidence,
                imgsz=profile["imgsz"],
            )
        if not self._tracker.is_loaded:
            self._update(model_status="warming_up")
            self._tracker.load()
        return self._tracker

    def _choose_mode(self, measured_fps: float, video_fps: float, tracker) -> str:
        """`auto` смотрит на реальную скорость анализа во время воспроизведения."""
        required = max(AUTO_MIN_FPS, video_fps * 0.5)
        if measured_fps >= required:
            LOGGER.info(
                "Источник %s: анализ успевает (%.1f кадр/с при нужных %.1f) — режим «в реальном времени»",
                self.config.source_id,
                measured_fps,
                required,
            )
            self._update(analysis_mode="realtime", model_status="ready", warmup_percent=None)
            return "realtime"

        LOGGER.info(
            "Источник %s: анализ не успевает (%.1f кадр/с при нужных %.1f) — переходим к предрасчёту",
            self.config.source_id,
            measured_fps,
            required,
        )
        self._update(analysis_mode="precomputed")
        self._start_precompute(tracker)
        return "precomputed"

    def _start_precompute(self, tracker) -> None:
        """Запустить подготовку анализа фоном: видео при этом продолжает идти."""
        if self._cached_tracks is not None or (self._precompute and self._precompute.is_running):
            return

        profile = MODEL_PROFILES.get(self.config.model_profile, MODEL_PROFILES["standard"])
        key = cache_key(
            self.config.video_path,
            tracker.weights_name or profile["weights"],
            tracker.imgsz,
            self.config.confidence,
            self.config.tracker,
        )
        target = cache_file(self.config.cache_dir, key)

        if target.exists():
            self._cached_tracks = load_tracks(target)
            self._update(model_status="ready", warmup_percent=None)
            return

        self._update(model_status="warming_up", warmup_percent=0.0)
        job = PrecomputeJob(
            self.config.video_path,
            target,
            tracker,
            on_progress=lambda progress: self._update(warmup_percent=progress.percent),
        )
        self._precompute_target = target
        self._precompute = job
        job.start()
        LOGGER.info("Источник %s: начата подготовка анализа", self.config.source_id)

    def _collect_precompute(self) -> None:
        """Забрать результат подготовки, когда она закончилась."""
        job = self._precompute
        if job is None or job.is_running:
            return

        self._precompute = None
        if job.progress.error:
            self._update(model_status="error", warmup_percent=None, error=job.progress.error)
            LOGGER.warning(
                "Источник %s: подготовка анализа не удалась: %s",
                self.config.source_id,
                job.progress.error,
            )
            return

        target = getattr(self, "_precompute_target", None)
        if target is None or not target.exists():
            return
        self._cached_tracks = load_tracks(target)
        self._update(model_status="ready", warmup_percent=None, error=None)
        LOGGER.info("Источник %s: анализ готов, счётчики пошли", self.config.source_id)

    def _detect(self, frame, mode: str, tracker: UltralyticsPersonTracker) -> list[TrackedBox]:
        if mode == "precomputed":
            if self._cached_tracks is None:
                # Кадры идут, но анализа ещё нет: счётчики честно стоят на месте.
                return []
            return self._cached_tracks.get(frame.index, [])
        self._update(model_status="ready", warmup_percent=None)
        return tracker.update(frame.image)

    def _apply_pending_markup(self) -> bool:
        with self._lock:
            markup = self._pending_markup
            self._pending_markup = None
        if markup is None:
            return False
        self._engine.set_geometry(markup.lines, markup.zones)
        LOGGER.info("Источник %s: применена новая разметка", self.config.source_id)
        return True

    # --- состояние ----------------------------------------------------------

    def _stable_health(self, raw: str) -> str:
        """Переключить статус, только если новое состояние продержалось."""
        now = time.monotonic()
        if raw == self._health_state:
            self._health_candidate = None
            return self._health_state
        if self._health_candidate != raw:
            self._health_candidate = raw
            self._health_candidate_since = now
        elif now - self._health_candidate_since >= HEALTH_HOLD_SECONDS:
            self._health_state = raw
            self._health_candidate = None
        return self._health_state

    def _health(self, fps: float, latency_ms: float, video_fps: float) -> str:
        if latency_ms > DEGRADED_LATENCY_MS:
            return "degraded"
        if video_fps > 0 and fps < video_fps * DEGRADED_FPS_RATIO:
            return "degraded"
        return "online"

    def _publish_live_frame(self, image, cv2) -> None:
        with self._lock:
            wanted = time.monotonic() < self._live_wanted_until or self._live_jpeg is None
        if not wanted:
            return
        jpeg = self._encode(image, cv2)
        if jpeg is None:
            return
        with self._lock:
            self._live_jpeg = jpeg
            self._live_encoded_at = time.monotonic()
        self._fresh_live.set()

    def _publish_analysis_frame(self, image, frame_index: int, cv2, result: FrameResult) -> None:
        with self._lock:
            # Сырой кадр держим всегда: из него собирается кадр события.
            self._last_image = image
            self._last_result = result
            wanted = time.monotonic() < self._analysis_wanted_until or self._analysis_jpeg is None
        if not wanted:
            return
        jpeg = self._encode(image, cv2)
        if jpeg is None:
            return
        with self._lock:
            self._analysis_jpeg = jpeg
            self._analysis_frame_index = frame_index
            self._analysis_encoded_at = time.monotonic()
        self._fresh_analysis.set()

    def _encode(self, image, cv2) -> bytes | None:
        height, width = image.shape[:2]
        if width > self.config.jpeg_max_width:
            scale = self.config.jpeg_max_width / width
            image = cv2.resize(image, (self.config.jpeg_max_width, int(height * scale)))
        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality])
        return buffer.tobytes() if ok else None

    def _update(self, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self._snapshot, key, value)
            self._snapshot.updated_at = now_utc()

    def _update_from_result(
        self,
        result: FrameResult,
        *,
        frame,
        status: str,
        fps: float,
        latency_ms: float,
    ) -> None:
        markup = self.config.markup
        confidences = [obj.confidence for obj in result.objects]

        zones = [
            {
                "id": zone.id,
                "name": zone.name,
                "kind": zone.kind,
                "polygon": [[point.x, point.y] for point in zone.polygon],
                "people": result.zone_counts.get(zone.id, 0),
                "capacity": zone.capacity,
            }
            for zone in markup.zones
        ]
        lines = [
            {
                "id": line.id,
                "name": line.name,
                "a": [line.a.x, line.a.y],
                "b": [line.b.x, line.b.y],
                "entrySide": line.entry_side,
                "counts": line.counts,
                "entered": result.line_counters.get(line.id, {}).get("in", 0),
                "exited": result.line_counters.get(line.id, {}).get("out", 0),
            }
            for line in markup.lines
        ]

        self._update(
            status=status,
            error=None,
            frame_index=frame.index,
            position_seconds=frame.position_seconds,
            loop_number=result.loop_number,
            loop_entries=result.loop_entries,
            loop_exits=result.loop_exits,
            previous_loop_entries=result.previous_loop_entries,
            previous_loop_exits=result.previous_loop_exits,
            people_in_frame=result.people_in_frame,
            people_in_zone=result.people_in_zone,
            queue_size=result.queue_size,
            entries_today=result.entries_today,
            exits_today=result.exits_today,
            inside_now=result.inside_now,
            avg_wait_seconds=result.avg_wait_seconds,
            fps=fps,
            latency_ms=latency_ms,
            confidence=(sum(confidences) / len(confidences)) if confidences else None,
            objects=[
                {
                    "trackId": obj.track_id,
                    "bbox": [round(value, 4) for value in obj.bbox],
                    "confidence": round(obj.confidence, 3),
                    "state": obj.state,
                    "anchor": [round(obj.anchor.x, 4), round(obj.anchor.y, 4)],
                }
                for obj in result.objects
            ],
            crossings=[
                {
                    "lineId": crossing.line_id,
                    "lineName": crossing.line_name,
                    "direction": crossing.direction,
                    "trackId": crossing.track_id,
                    "point": [round(crossing.point.x, 4), round(crossing.point.y, 4)],
                }
                for crossing in result.crossings
            ],
            zones=zones,
            lines=lines,
        )
        self._on_status(self.config.source_id, status, None)

    def _accumulate(
        self, result: FrameResult, status: str, fps: float, latency_ms: float, loop_boundary: bool
    ) -> None:
        markup = self.config.markup
        payload = self._aggregator.add(
            result,
            now_utc(),
            fps=fps,
            latency_ms=latency_ms,
            health=status,
            loop_boundary=loop_boundary,
            warming=time.monotonic() - self._started_monotonic < WARMUP_SECONDS,
            zone_names={zone.id: (zone.name, zone.kind) for zone in markup.zones},
            line_names={line.id: line.name for line in markup.lines},
        )
        if payload is not None:
            self._on_bucket(payload)

    def _flush_aggregator(self) -> None:
        payload = self._aggregator.flush()
        if payload is not None:
            self._on_bucket(payload)

    def _close_loop(self) -> None:
        snapshot = self.snapshot()
        ended_at = now_utc()
        self._on_loop(
            self.config.source_id,
            snapshot.loop_number,
            self._loop_started_at,
            ended_at,
            snapshot.loop_entries,
            snapshot.loop_exits,
        )
        self._loop_started_at = ended_at

    def _fail(self, status: str, message: str) -> None:
        self._update(status=status, error=message, model_status="unavailable")
        self._on_status(self.config.source_id, status, message)

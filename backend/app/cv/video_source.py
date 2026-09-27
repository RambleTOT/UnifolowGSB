"""Источники видео: файл по кругу и прямой поток с камеры.

Файл воспроизводится по кругу и анализируется так же, как живой поток (ТЗ,
раздел 1.2), поэтому у его чтения есть две вещи, которых не бывает у обычного
чтения файла: темп реального времени с пропуском кадров и явная граница круга.
Прямой поток — ссылка на камеру (HLS, RTSP, HTTP): кругов у него нет, зато есть
обрывы связи, которые надо переживать без падения источника.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

LOGGER = logging.getLogger(__name__)

DEFAULT_FPS = 25.0


@dataclass(frozen=True, slots=True)
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float

    @property
    def resolution(self) -> str:
        return f"{self.width} × {self.height}"


class VideoUnavailable(RuntimeError):
    """Файл не найден, не читается или не декодируется."""


def probe_video(path: str | Path) -> VideoInfo:
    """Прочитать параметры файла. Используется и при проверке доступности источника."""
    import cv2

    file_path = Path(path)
    if not file_path.exists():
        raise VideoUnavailable(f"Файл не найден: {file_path}")

    capture = cv2.VideoCapture(str(file_path))
    if not capture.isOpened():
        capture.release()
        raise VideoUnavailable(f"Файл не открывается: {file_path.name}")

    try:
        ok, _ = capture.read()
        if not ok:
            raise VideoUnavailable(f"Файл не декодируется: {file_path.name}")

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS)) or DEFAULT_FPS
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()

    if fps <= 0 or fps > 240:
        fps = DEFAULT_FPS
    duration = frame_count / fps if frame_count > 0 else 0.0

    return VideoInfo(
        path=str(file_path),
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_seconds=duration,
    )


@dataclass(frozen=True, slots=True)
class SourceFrame:
    """Кадр источника вместе с положением внутри файла."""

    image: object
    index: int
    position_seconds: float
    loop_number: int
    is_loop_start: bool
    skipped: int = 0
    # Разрыв во времени: переподключение или прыжок вперёд. Сопровождение после
    # него начинается заново — люди за это время ушли далеко.
    discontinuity: bool = False


class VideoFileSource:
    """Чтение файла по кругу.

    `realtime=True` держит темп самого файла: если анализ не успевает, кадры
    пропускаются и берётся самый свежий, чтобы задержка не росла со временем.
    """

    def __init__(
        self,
        path: str | Path,
        loop: bool = True,
        realtime: bool = False,
        stride: int = 1,
    ) -> None:
        self.path = Path(path)
        self.loop = loop
        self.realtime = realtime
        self.stride = max(1, stride)
        self.info: VideoInfo | None = None
        self._capture = None
        self._loop_number = 1

    def open(self) -> VideoInfo:
        import cv2

        self.info = probe_video(self.path)
        self._capture = cv2.VideoCapture(str(self.path))
        if not self._capture.isOpened():
            raise VideoUnavailable(f"Файл не открывается: {self.path.name}")
        return self.info

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def __enter__(self) -> "VideoFileSource":
        self.open()
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def frames(self) -> Iterator[SourceFrame]:
        if self._capture is None:
            self.open()

        assert self.info is not None
        capture = self._capture
        frame_interval = 1.0 / self.info.fps
        started_at = time.monotonic()
        frame_index = 0
        is_loop_start = True

        while True:
            skipped = 0
            if self.realtime:
                # Догоняем реальное время: лишние кадры пропускаем без декодирования.
                target_index = int((time.monotonic() - started_at) / frame_interval)
                while frame_index + self.stride <= target_index - self.stride:
                    if not capture.grab():
                        break
                    frame_index += 1
                    skipped += 1

            for _ in range(self.stride - 1):
                if not capture.grab():
                    break
                frame_index += 1

            ok, image = capture.read()
            if not ok:
                if not self.loop:
                    return
                # Конец файла: начинаем круг заново. Ни одного выхода здесь не
                # засчитывается — это не уход человека из кадра, а начало файла.
                self._restart(capture)
                frame_index = 0
                started_at = time.monotonic()
                is_loop_start = True
                self._loop_number += 1
                continue

            position = frame_index / self.info.fps
            yield SourceFrame(
                image=image,
                index=frame_index,
                position_seconds=position,
                loop_number=self._loop_number,
                is_loop_start=is_loop_start,
                skipped=skipped,
            )
            is_loop_start = False
            frame_index += 1

            if self.realtime:
                ahead = started_at + frame_index * frame_interval - time.monotonic()
                if ahead > 0:
                    time.sleep(min(ahead, frame_interval))

    def _restart(self, capture) -> None:
        import cv2

        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        LOGGER.debug("Источник %s: начало нового круга", self.path.name)


# --- прямой поток --------------------------------------------------------------

# Какие ссылки принимаются как прямой поток. Видеофайл с диска сюда не подходит:
# у него своя логика — круги и перемотка.
STREAM_SCHEMES = ("http://", "https://", "rtsp://", "rtsps://", "rtmp://")
# Живой HLS отдаёт видео сегментами по 5–15 секунд, поэтому таймауты длинные:
# открытие подкачивает несколько сегментов, а чтение ждёт появления следующего.
STREAM_OPEN_TIMEOUT_SECONDS = 60.0
STREAM_READ_TIMEOUT_SECONDS = 40.0
STREAM_STALL_SECONDS = 45.0
STREAM_RECONNECT_SECONDS = 3.0
# На сколько секунд воспроизведение HLS отстаёт от того, что уже скачано.
# Сегменты приходят рывками раз в 5–15 секунд, плюс 1.5–3 секунды на скачивание
# (изредка до 10): отставание должно перекрывать и то и другое, иначе буфер
# будет пустеть на каждой границе сегмента.
STREAM_HLS_DELAY_SECONDS = 25.0
# Если впереди накопилось больше, чем задержка плюс этот запас, воспроизведение
# перепрыгивает вперёд: смотреть эфир минутной давности незачем.
STREAM_CATCHUP_SECONDS = 8.0
# Потолок буфера на случай, если анализ встал: старые кадры выбрасываются.
STREAM_BUFFER_LIMIT_SECONDS = STREAM_HLS_DELAY_SECONDS + 20.0


def is_stream_url(value: str | None) -> bool:
    return bool(value) and value.strip().lower().startswith(STREAM_SCHEMES)


def _open_capture(url: str):
    import cv2

    return cv2.VideoCapture(
        url,
        cv2.CAP_FFMPEG,
        [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(STREAM_OPEN_TIMEOUT_SECONDS * 1000),
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(STREAM_READ_TIMEOUT_SECONDS * 1000),
        ],
    )


@dataclass(frozen=True, slots=True)
class StreamInfo:
    url: str
    width: int
    height: int
    fps: float

    @property
    def resolution(self) -> str:
        return f"{self.width} × {self.height}"


def probe_stream(url: str) -> tuple[StreamInfo, object]:
    """Открыть поток и прочитать один кадр: для проверки и для кадра разметки."""
    import cv2

    if not is_stream_url(url):
        raise VideoUnavailable("Это не ссылка на поток: нужен адрес http(s)://, rtsp:// или rtmp://")

    capture = _open_capture(url)
    try:
        if not capture.isOpened():
            raise VideoUnavailable("Поток не открывается: проверьте ссылку и доступность камеры.")
        ok, image = capture.read()
        if not ok or image is None:
            raise VideoUnavailable("Поток открылся, но кадры не приходят.")
        height, width = image.shape[:2]
        fps = float(capture.get(cv2.CAP_PROP_FPS)) or DEFAULT_FPS
    finally:
        capture.release()

    if fps <= 0 or fps > 240:
        fps = DEFAULT_FPS
    return StreamInfo(url=url, width=width, height=height, fps=fps), image


class LiveStreamSource:
    """Прямой поток с камеры: HLS, RTSP или HTTP.

    Устроен как обычный плеер: отдельный поток читает и декодирует видео с
    опережением и складывает кадры в буфер, а наружу они выходят строго по
    меткам времени самого потока. Это важно для HLS: камера отдаёт видео
    сегментами по 5–15 секунд, и на каждой границе сегмента чтение замирает на
    пару секунд, пока скачивается следующий. Без буфера трекер видел бы
    рывки — люди прыгали бы на метры вперёд, треки рвались, проходы терялись.

    Если анализ медленнее камеры, берётся самый свежий кадр, наступивший по
    расписанию, — задержка не копится (ТЗ, раздел 3.3). В буфере кадры лежат в
    JPEG и не чаще `max_fps` в секунду: несжатый кадр Full HD — 6 МБ.
    Связь рвётся — чтение переподключается само, а если кадров нет дольше
    `STREAM_STALL_SECONDS`, наружу уходит «нет сигнала».
    """

    def __init__(self, url: str, max_fps: float = 8.0, start_delay: float | None = None) -> None:
        self.url = url.strip()
        self.max_fps = max_fps
        # HLS нужен запас хотя бы на одну заминку между сегментами; RTSP идёт ровно.
        self.start_delay = (
            start_delay if start_delay is not None
            else (STREAM_HLS_DELAY_SECONDS if ".m3u8" in self.url.lower() else 1.0)
        )
        self.info: StreamInfo | None = None
        self._thread = None
        self._cond = None
        self._stop = None
        self._buffer: deque = deque()
        self._sequence = 0
        self._generation = 0
        self._last_arrival = 0.0
        self._error: str | None = None

    def open(self) -> StreamInfo:
        import threading

        info, _first = probe_stream(self.url)
        self.info = info
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._last_arrival = time.monotonic()
        self._thread = threading.Thread(target=self._read_loop, name="stream-reader", daemon=True)
        self._thread.start()
        return info

    def close(self) -> None:
        if self._stop is not None:
            self._stop.set()
            with self._cond:
                self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=STREAM_READ_TIMEOUT_SECONDS + 2)
            self._thread = None

    def __enter__(self) -> "LiveStreamSource":
        self.open()
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    # --- чтение ---------------------------------------------------------------

    def _read_loop(self) -> None:
        import cv2

        capture = None
        last_kept = None
        min_step = 1.0 / self.max_fps if self.max_fps > 0 else 0.0
        while not self._stop.is_set():
            if capture is None:
                capture = _open_capture(self.url)
                if not capture.isOpened():
                    capture.release()
                    capture = None
                    self._error = "поток не открывается"
                    self._stop.wait(STREAM_RECONNECT_SECONDS)
                    continue
                self._error = None
                last_kept = None
                # Новое подключение — новая шкала времени: старый буфер не годится.
                with self._cond:
                    self._buffer.clear()
                    self._generation += 1
                LOGGER.info("Поток %s: подключено", self.url)

            ok, image = capture.read()
            if not ok or image is None:
                LOGGER.warning("Поток %s: кадры перестали приходить, переподключаемся", self.url)
                capture.release()
                capture = None
                self._error = "связь с потоком прервалась"
                self._stop.wait(STREAM_RECONNECT_SECONDS)
                continue

            pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if last_kept is not None and 0 <= pts - last_kept < min_step - 0.01:
                continue
            last_kept = pts
            encoded, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not encoded:
                continue

            with self._cond:
                self._sequence += 1
                self._buffer.append((pts, self._sequence, buffer.tobytes()))
                # Анализ стоит — буфер не растёт бесконечно: старое выбрасываем.
                while self._buffer and pts - self._buffer[0][0] > STREAM_BUFFER_LIMIT_SECONDS:
                    self._buffer.popleft()
                self._last_arrival = time.monotonic()
                self._cond.notify_all()

        if capture is not None:
            capture.release()

    # --- выдача ---------------------------------------------------------------

    def frames(self) -> Iterator[SourceFrame]:
        import cv2
        import numpy as np

        if self._thread is None:
            self.open()

        started_at = time.monotonic()
        clock: tuple[float, float] | None = None  # (метка потока, настенное время)
        generation = -1
        taken_sequence = 0
        delay = self.start_delay
        underrun = False
        jumped = True  # первый кадр — тоже начало новой шкалы

        while not self._stop.is_set():
            with self._cond:
                if generation != self._generation:
                    generation = self._generation
                    clock = None
                    jumped = True

                if clock is None:
                    # Запускаем часы, когда запас в буфере не меньше задержки, и
                    # сразу встаём на `delay` позади скачанного: старое отбрасываем.
                    # После опустошения буфера хватает половины запаса: ждать полный
                    # — это полминуты замершей картинки, а следующий сегмент и так на подходе.
                    needed = delay / 2 if underrun else delay
                    span = self._buffer[-1][0] - self._buffer[0][0] if self._buffer else 0.0
                    if not self._buffer or span < needed:
                        self._wait_or_fail(1.0)
                        continue
                    clock = self._anchor(self._buffer[-1][0] - min(delay, span))
                    jumped = True
                    underrun = False

                if not self._buffer:
                    # Буфер опустел: камера отстала сильнее обычного. На будущее
                    # держим запас побольше.
                    clock = None
                    underrun = True
                    delay = min(delay * 1.3, STREAM_BUFFER_LIMIT_SECONDS - 5.0)
                    LOGGER.info("Поток %s: буфер опустел, запас увеличен до %.0f с", self.url, delay)
                    self._wait_or_fail(1.0)
                    continue

                playhead = clock[0] + (time.monotonic() - clock[1])
                head = self._buffer[-1][0]
                if head - playhead > delay + STREAM_CATCHUP_SECONDS or self._buffer[0][0] - playhead > 1.0:
                    # Слишком отстали или кадры впереди выброшены — встаём заново.
                    clock = self._anchor(head - delay)
                    playhead = clock[0]
                    jumped = True

                due = 0
                for item in self._buffer:
                    if item[0] > playhead:
                        break
                    due += 1
                if not due:
                    self._cond.wait(timeout=min(max(self._buffer[0][0] - playhead, 0.005), 0.5))
                    continue
                for _ in range(due - 1):
                    self._buffer.popleft()
                pts, sequence, payload = self._buffer.popleft()

            image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            skipped = max(0, sequence - taken_sequence - 1) if taken_sequence else 0
            taken_sequence = sequence
            yield SourceFrame(
                image=image,
                index=sequence,
                position_seconds=time.monotonic() - started_at,
                loop_number=1,
                # У потока нет кругов: граница круга — понятие только для файла.
                is_loop_start=False,
                skipped=skipped,
                discontinuity=jumped,
            )
            jumped = False

    def _anchor(self, target_pts: float) -> tuple[float, float]:
        """Поставить часы на `target_pts`, выбросив всё, что старше. Вызывать под замком."""
        while len(self._buffer) > 1 and self._buffer[0][0] < target_pts:
            self._buffer.popleft()
        return (max(target_pts, self._buffer[0][0]), time.monotonic())

    def _wait_or_fail(self, timeout: float) -> None:
        """Подождать кадров под замком; слишком долгое молчание — «нет сигнала»."""
        self._cond.wait(timeout=timeout)
        if time.monotonic() - self._last_arrival > STREAM_STALL_SECONDS:
            reason = self._error or "кадры не приходят"
            raise VideoUnavailable(f"Нет сигнала: {reason} дольше {int(STREAM_STALL_SECONDS)} с.")

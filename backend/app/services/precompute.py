"""Предрасчёт треков по видеофайлу.

На слабом железе (сервер без видеокарты) модель не успевает за
воспроизведением. Тогда она один раз проходит файл целиком и складывает треки
по кадрам в кэш, а при воспроизведении подсчёт по зонам и линиям идёт вживую
(задание, раздел 5.4). Правка разметки не требует повторного прохода: в кэше
лежат только рамки людей, а не результаты подсчёта.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.cv.detector import PersonTracker, TrackedBox
from app.cv.video_source import VideoFileSource, probe_video

LOGGER = logging.getLogger(__name__)


def cache_key(video_path: Path, weights: str, imgsz: int, confidence: float, tracker: str) -> str:
    """Ключ кэша: файл, модель и параметры детекции."""
    stat = video_path.stat()
    raw = "|".join(
        [
            video_path.name,
            str(stat.st_size),
            str(int(stat.st_mtime)),
            weights,
            str(imgsz),
            f"{confidence:.3f}",
            tracker,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def cache_file(cache_dir: Path, key: str) -> Path:
    return cache_dir / "tracks" / f"{key}.jsonl.gz"


def load_tracks(path: Path) -> dict[int, list[TrackedBox]]:
    """Прочитать кэш целиком: он маленький, а доступ нужен по номеру кадра."""
    tracks: dict[int, list[TrackedBox]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for raw_line in stream:
            record = json.loads(raw_line)
            tracks[int(record["i"])] = [
                TrackedBox(
                    track_id=int(item[0]),
                    bbox=(float(item[1]), float(item[2]), float(item[3]), float(item[4])),
                    confidence=float(item[5]),
                )
                for item in record["t"]
            ]
    return tracks


@dataclass
class PrecomputeProgress:
    done_frames: int = 0
    total_frames: int = 0
    finished: bool = False
    error: str | None = None

    @property
    def percent(self) -> float:
        if self.total_frames <= 0:
            return 0.0
        return min(100.0, self.done_frames / self.total_frames * 100.0)


class PrecomputeJob:
    """Проход модели по всему файлу в отдельном потоке."""

    def __init__(
        self,
        video_path: Path,
        target: Path,
        tracker: PersonTracker,
        on_progress: Callable[[PrecomputeProgress], None] | None = None,
    ) -> None:
        self.video_path = video_path
        self.target = target
        self.tracker = tracker
        self.on_progress = on_progress
        self.progress = PrecomputeProgress()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"precompute-{self.video_path.stem}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        temporary = self.target.with_suffix(".part")
        try:
            info = probe_video(self.video_path)
            self.progress.total_frames = info.frame_count
            self.target.parent.mkdir(parents=True, exist_ok=True)

            source = VideoFileSource(self.video_path, loop=False, realtime=False)
            source.open()
            with gzip.open(temporary, "wt", encoding="utf-8") as stream:
                for frame in source.frames():
                    if self._stop.is_set():
                        LOGGER.info("Предрасчёт %s прерван", self.video_path.name)
                        return
                    boxes = self.tracker.update(frame.image)
                    record = {
                        "i": frame.index,
                        "t": [
                            [
                                box.track_id,
                                round(box.bbox[0], 4),
                                round(box.bbox[1], 4),
                                round(box.bbox[2], 4),
                                round(box.bbox[3], 4),
                                round(box.confidence, 3),
                            ]
                            for box in boxes
                        ],
                    }
                    stream.write(json.dumps(record, separators=(",", ":")) + "\n")
                    self.progress.done_frames = frame.index + 1
                    if self.on_progress and frame.index % 25 == 0:
                        self.on_progress(self.progress)
            source.close()

            temporary.replace(self.target)
            self.progress.finished = True
            LOGGER.info(
                "Предрасчёт %s готов: %s кадров", self.video_path.name, self.progress.done_frames
            )
        except Exception as error:  # noqa: BLE001 — любая ошибка должна дойти до интерфейса
            self.progress.error = str(error)
            LOGGER.exception("Предрасчёт %s не удался", self.video_path.name)
        finally:
            temporary.unlink(missing_ok=True)
            if self.on_progress:
                self.on_progress(self.progress)

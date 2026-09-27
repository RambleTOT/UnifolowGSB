"""Детекция и сопровождение людей.

Детектор спрятан за узким интерфейсом: модель можно заменить, не трогая ни
подсчёт, ни API (задание, раздел 4, примечание о лицензии). Наружу отдаются
только нормированные рамки, номера треков и уверенность — ничего, что описывало
бы конкретного человека (ТЗ, раздел 1.3).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from app.cv.device import resolve_device

LOGGER = logging.getLogger(__name__)

# Инференс по всем источникам идёт через один замок: ускорители (и MPS на
# Apple, и CUDA) не рассчитаны на одновременные вызовы из нескольких потоков —
# Metal падает с «A command encoder is already encoding to this command buffer».
# Один поток инференса, обходящий источники по кругу, — как и задумано в задании.
INFERENCE_LOCK = threading.Lock()

# Веса складываются в один каталог, иначе каждый запуск из другого рабочего
# каталога качает их заново.
WEIGHTS_DIR = Path(
    os.environ.get("UNIFLOW_CACHE_DIR", Path(__file__).resolve().parents[3] / "data" / "cache")
) / "weights"

# Класс «человек» в наборе COCO. Ничего другого система не считает.
PERSON_CLASS = 0

# Порядок попыток загрузки весов: сначала актуальное семейство, затем запасное.
WEIGHTS_FALLBACK: dict[str, tuple[str, ...]] = {
    "yolo26n": ("yolo26n.pt", "yolo11n.pt"),
    "yolo26s": ("yolo26s.pt", "yolo11s.pt"),
    "yolo26m": ("yolo26m.pt", "yolo11m.pt"),
    "yolo11n": ("yolo11n.pt",),
    "yolo11s": ("yolo11s.pt",),
    "yolo11m": ("yolo11m.pt",),
}

# Профили модели: то, что пользователь выбирает в Настройках, — это профиль,
# а не имя файла весов.
MODEL_PROFILES: dict[str, dict[str, Any]] = {
    "fast": {"weights": "yolo26n", "imgsz": 640, "title": "Люди · быстрый"},
    "standard": {"weights": "yolo26n", "imgsz": 960, "title": "Люди · стандартный"},
    "accurate": {"weights": "yolo26s", "imgsz": 960, "title": "Люди · точный"},
    # Широкий план — площадь, улица с высоты: люди на кадре Full HD по 20–50
    # пикселей. При входе 960 кадр ужимается вдвое и модель их почти не видит
    # (на Дворцовой: 9 человек против 32 при полном разрешении).
    "far": {"weights": "yolo26n", "imgsz": 1920, "title": "Люди · дальний план"},
}


@dataclass(frozen=True, slots=True)
class TrackedBox:
    """Один сопровождаемый человек на кадре, координаты нормированы к кадру."""

    track_id: int
    bbox: tuple[float, float, float, float]
    confidence: float


class PersonTracker(Protocol):
    """Детекция + сопровождение для одного источника."""

    def update(self, frame: Any) -> list[TrackedBox]: ...

    def reset(self) -> None: ...


class UltralyticsPersonTracker:
    """Реализация поверх Ultralytics YOLO с трекером ByteTrack.

    Экземпляр создаётся на каждый источник: состояние трекера привязано к
    экземпляру модели и не должно делиться между источниками (задание, 5.1).
    """

    def __init__(
        self,
        profile: str = "standard",
        weights: str | None = None,
        tracker: str = "bytetrack.yaml",
        device: str = "auto",
        confidence: float = 0.25,
        imgsz: int | None = None,
        max_detections: int = 300,
    ) -> None:
        profile_config = MODEL_PROFILES.get(profile, MODEL_PROFILES["standard"])
        self.profile = profile
        self.requested_weights = weights or profile_config["weights"]
        self.imgsz = imgsz or profile_config["imgsz"]
        self.tracker = tracker
        self.confidence = confidence
        self.max_detections = max_detections
        self.device = resolve_device(device)
        self.weights_name: str | None = None
        self._model = None

    # --- загрузка модели ----------------------------------------------------

    def load(self) -> None:
        if self._model is not None:
            return

        from ultralytics import YOLO  # импорт внутри: он тяжёлый

        candidates = WEIGHTS_FALLBACK.get(
            self.requested_weights, (f"{self.requested_weights}.pt", "yolo11n.pt")
        )
        errors: list[str] = []
        for candidate in candidates:
            try:
                with INFERENCE_LOCK:
                    self._model = YOLO(_weights_source(candidate))
                self.weights_name = candidate
                _cache_weights(candidate)
                LOGGER.info(
                    "Модель %s загружена, устройство %s, размер входа %s",
                    candidate,
                    self.device,
                    self.imgsz,
                )
                return
            except Exception as error:  # noqa: BLE001 — нужен именно откат на запасные веса
                errors.append(f"{candidate}: {error}")
                LOGGER.warning("Не удалось загрузить веса %s: %s", candidate, error)

        raise RuntimeError("Не удалось загрузить ни одни веса модели: " + "; ".join(errors))

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    # --- работа по кадрам ---------------------------------------------------

    def update(self, frame: Any) -> list[TrackedBox]:
        """Обработать кадр (BGR) и вернуть сопровождаемых людей."""
        if self._model is None:
            self.load()

        height, width = frame.shape[:2]
        with INFERENCE_LOCK:
            results = self._model.track(
                source=frame,
                persist=True,
                tracker=self.tracker,
                classes=[PERSON_CLASS],
                conf=self.confidence,
                imgsz=self.imgsz,
                device=self.device,
                max_det=self.max_detections,
                verbose=False,
            )
        if not results:
            return []

        boxes = results[0].boxes
        if boxes is None or boxes.id is None:
            return []

        tracked: list[TrackedBox] = []
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.cpu().numpy().astype(int)
        confidences = boxes.conf.cpu().numpy()

        for (x1, y1, x2, y2), track_id, confidence in zip(xyxy, ids, confidences):
            tracked.append(
                TrackedBox(
                    track_id=int(track_id),
                    bbox=(
                        float(x1) / width,
                        float(y1) / height,
                        float(x2) / width,
                        float(y2) / height,
                    ),
                    confidence=float(confidence),
                )
            )
        return tracked

    def reset(self) -> None:
        """Сбросить сопровождение: граница круга начинает нумерацию треков заново."""
        model = self._model
        if model is None:
            return
        predictor = getattr(model, "predictor", None)
        trackers = getattr(predictor, "trackers", None) if predictor is not None else None
        if trackers:
            for tracker in trackers:
                reset = getattr(tracker, "reset", None)
                if callable(reset):
                    reset()
                else:  # pragma: no cover — на случай другой версии библиотеки
                    model.predictor = None
                    return
            return
        if predictor is not None:
            model.predictor = None


def _weights_source(name: str) -> str:
    """Путь к весам: сначала общий кэш, иначе имя — библиотека скачает сама."""
    cached = WEIGHTS_DIR / name
    return str(cached) if cached.exists() else name


def _cache_weights(name: str) -> None:
    """Перенести только что скачанные веса в общий кэш."""
    downloaded = Path(name)
    target = WEIGHTS_DIR / name
    if target.exists() or not downloaded.exists():
        return
    try:
        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(downloaded), str(target))
        LOGGER.info("Веса %s сохранены в %s", name, WEIGHTS_DIR)
    except OSError as error:  # pragma: no cover — кэш не критичен
        LOGGER.warning("Не удалось сохранить веса в кэш: %s", error)


def build_tracker(
    profile: str = "standard",
    device: str = "auto",
    confidence: float = 0.25,
    tracker: str = "bytetrack.yaml",
    imgsz: int | None = None,
    weights: str | None = None,
) -> PersonTracker:
    return UltralyticsPersonTracker(
        profile=profile,
        weights=weights,
        tracker=tracker,
        device=device,
        confidence=confidence,
        imgsz=imgsz,
    )


_SHARED_TRACKERS: dict[str, PersonTracker] = {}
_SHARED_LOCK = threading.Lock()


def shared_tracker(profile: str = "standard") -> PersonTracker:
    """Трекер для разовых задач вроде кадра в редакторе разметки.

    Рабочие потоки источников держат свои экземпляры: у них своё состояние
    сопровождения. Здесь же состояние не важно, а важна скорость ответа.
    """
    with _SHARED_LOCK:
        tracker = _SHARED_TRACKERS.get(profile)
        if tracker is None:
            tracker = build_tracker(profile=profile)
            _SHARED_TRACKERS[profile] = tracker
        return tracker


def profile_title(profile: str) -> str:
    return MODEL_PROFILES.get(profile, MODEL_PROFILES["standard"])["title"]


def available_profiles() -> Sequence[str]:
    return tuple(MODEL_PROFILES)

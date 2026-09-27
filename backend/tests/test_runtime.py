"""Рабочий поток источника: кадры в JPEG кодируются только для зрителей."""

from __future__ import annotations

import cv2
import numpy as np

from app.cv.markup import Markup
from app.services.runtime import SourceRuntimeConfig, SourceWorker


def make_worker() -> SourceWorker:
    config = SourceRuntimeConfig(
        source_id=1, name="Проверка", scope="gate", video_path=None, markup=Markup()
    )
    return SourceWorker(
        config,
        on_bucket=lambda payload: None,
        on_status=lambda *args: None,
        on_loop=lambda *args: None,
    )


def frame(value: int):
    return np.full((12, 16, 3), value, dtype=np.uint8)


def test_first_frame_is_always_encoded():
    worker = make_worker()
    worker._publish_live_frame(frame(10), cv2)
    assert worker._live_jpeg is not None


def test_frames_are_not_encoded_when_nobody_watches():
    worker = make_worker()
    worker._publish_live_frame(frame(10), cv2)
    first = worker._live_jpeg

    worker._publish_live_frame(frame(200), cv2)
    assert worker._live_jpeg is first


def test_request_turns_encoding_back_on():
    worker = make_worker()
    worker._publish_live_frame(frame(10), cv2)
    first = worker._live_jpeg

    worker.live_jpeg()  # кто-то открыл стену мониторинга
    worker._publish_live_frame(frame(200), cv2)
    assert worker._live_jpeg is not first


def test_raw_frame_for_event_snapshot_is_kept_without_viewers():
    worker = make_worker()
    worker._publish_analysis_frame(frame(10), 1, cv2, result=None)
    worker._publish_analysis_frame(frame(99), 2, cv2, result=None)
    # JPEG не перекодировался, но кадр для снимка события — свежий.
    assert worker._analysis_frame_index == 1
    assert int(worker.last_image()[0, 0, 0]) == 99


def test_health_does_not_flicker_on_the_threshold(monkeypatch):
    from app.services import runtime

    clock = {"now": 100.0}
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock["now"])
    worker = make_worker()

    # Короткие провалы ниже порога статус не трогают.
    for step, raw in enumerate(["degraded", "online", "degraded", "online"]):
        clock["now"] = 100.0 + step
        assert worker._stable_health(raw) == "online"

    # Провал, который держится дольше 5 секунд, — уже «нестабильно».
    for second in range(0, 7):
        clock["now"] = 200.0 + second
        state = worker._stable_health("degraded")
    assert state == "degraded"

    # И обратно — тоже только после устойчивого восстановления.
    clock["now"] = 210.0
    assert worker._stable_health("online") == "degraded"
    clock["now"] = 216.0
    assert worker._stable_health("online") == "online"

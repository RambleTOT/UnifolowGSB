"""Прямой поток: кадры выходят по расписанию потока, а не рывками сегментов."""

from __future__ import annotations

import time

import numpy as np
import pytest

from app.cv import video_source
from app.cv.video_source import LiveStreamSource, StreamInfo, VideoUnavailable, is_stream_url

FRAME_STEP = 0.04  # 25 кадров в секунду
SEGMENT_FRAMES = 10  # сегмент HLS в миниатюре: 0.4 с видео
BACKLOG_SEGMENTS = 3  # при открытии HLS отдаёт несколько сегментов сразу


class BurstyCapture:
    """Поддельный HLS: сегмент целиком за миг, потом пауза до следующего."""

    def __init__(self) -> None:
        self.index = 0
        self.opened_at = time.monotonic()

    def isOpened(self) -> bool:  # noqa: N802 — интерфейс OpenCV
        return True

    def read(self):
        segment = self.index // SEGMENT_FRAMES
        if segment >= BACKLOG_SEGMENTS:
            # Живой край: следующий сегмент появляется в темпе эфира.
            ready_at = self.opened_at + (segment - BACKLOG_SEGMENTS + 1) * SEGMENT_FRAMES * FRAME_STEP
            delay = ready_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        self.index += 1
        return True, np.full((8, 8, 3), self.index % 255, dtype=np.uint8)

    def get(self, _prop) -> float:
        return (self.index - 1) * FRAME_STEP * 1000.0

    def release(self) -> None:
        pass


@pytest.fixture
def bursty_stream(monkeypatch):
    monkeypatch.setattr(video_source, "_open_capture", lambda url: BurstyCapture())
    monkeypatch.setattr(
        video_source,
        "probe_stream",
        lambda url: (StreamInfo(url=url, width=8, height=8, fps=25.0), np.zeros((8, 8, 3), np.uint8)),
    )


def test_stream_frames_come_out_evenly_despite_bursts(bursty_stream):
    source = LiveStreamSource("https://camera.example/live.m3u8", max_fps=100, start_delay=0.6)
    source.open()
    arrivals: list[float] = []
    indices: list[int] = []
    breaks: list[bool] = []
    try:
        started = time.monotonic()
        for frame in source.frames():
            arrivals.append(time.monotonic())
            indices.append(frame.index)
            breaks.append(frame.discontinuity)
            if time.monotonic() - started > 2.0:
                break
    finally:
        source.close()

    gaps = [later - earlier for earlier, later in zip(arrivals, arrivals[1:])]
    # Без выравнивания кадры шли бы пачками по 10 с паузой 0.4 с между ними.
    assert max(gaps) < 0.2
    assert len(indices) > 25
    assert indices == sorted(indices)
    # Разрыв только в самом начале: дальше шкала времени непрерывна.
    assert breaks[0] is True
    assert not any(breaks[1:])


def test_stream_without_frames_reports_no_signal(monkeypatch):
    class DeadCapture(BurstyCapture):
        def read(self):
            return False, None

    monkeypatch.setattr(video_source, "_open_capture", lambda url: DeadCapture())
    monkeypatch.setattr(
        video_source,
        "probe_stream",
        lambda url: (StreamInfo(url=url, width=8, height=8, fps=25.0), np.zeros((8, 8, 3), np.uint8)),
    )
    monkeypatch.setattr(video_source, "STREAM_STALL_SECONDS", 0.5)
    monkeypatch.setattr(video_source, "STREAM_RECONNECT_SECONDS", 0.05)

    source = LiveStreamSource("rtsp://camera.example/live")
    source.open()
    try:
        with pytest.raises(VideoUnavailable, match="Нет сигнала"):
            for _frame in source.frames():
                pass
    finally:
        source.close()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://streamer.example/public/master.m3u8?sid=1", True),
        ("rtsp://192.168.1.10:554/stream1", True),
        ("  HTTP://camera.local/mjpeg  ", True),
        ("/data/videos/gate.mp4", False),
        ("ftp://camera.example/stream", False),
        ("", False),
        (None, False),
    ],
)
def test_stream_url_recognition(value, expected):
    assert is_stream_url(value) is expected


@pytest.mark.parametrize(
    ("wall_gap", "monotonic_gap", "slept"),
    [
        (0.12, 0.12, False),  # обычный кадр
        (3.0, 3.0, False),  # долгий кадр, но часы согласны
        (1200.0, 0.1, True),  # крышка была закрыта 20 минут
        (6.0, 0.5, True),  # короткий сон ночью
        (4.0, 0.0, False),  # мелкая поправка часов — не сон
    ],
)
def test_host_sleep_detection(wall_gap, monotonic_gap, slept):
    from app.services.runtime import host_slept

    assert host_slept(wall_gap, monotonic_gap) is slept

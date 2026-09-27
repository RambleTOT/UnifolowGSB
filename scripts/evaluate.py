#!/usr/bin/env python3
"""Офлайн-проверка подсчёта на видеофайле.

Прогоняет по видео ровно тот же код подсчёта, что работает в приложении, и
печатает, сколько человек вошло и сколько вышло. По желанию сохраняет
размеченный ролик: рамки, номера треков, опорные точки, зоны, линия, вспышка в
момент засчитывания прохода и бегущие счётчики — по нему сверяют цифры вручную
(задание на разработку, разделы 2 и 5.6).

Примеры:
    python scripts/evaluate.py --video data/videos/gate.mp4
    python scripts/evaluate.py --video data/videos/gate.mp4 \
        --markup data/videos/gate.markup.json --output data/videos/gate.annotated.mp4
    python scripts/evaluate.py --video data/videos/gate.mp4 --expected-in 42 --expected-out 39
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cv.counting import CountingEngine, CountingParams, TrackObservation  # noqa: E402
from app.cv.detector import build_tracker  # noqa: E402
from app.cv.markup import (  # noqa: E402
    Markup,
    default_markup_for_frame,
    markup_from_dict,
    validate_markup,
)
from app.cv.overlay import OverlayOptions, render_frame  # noqa: E402
from app.cv.video_source import VideoFileSource, probe_video  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Проверка точности подсчёта на видео")
    parser.add_argument("--video", required=True, help="путь к видеофайлу")
    parser.add_argument("--markup", help="файл разметки (JSON); без него берётся линия поперёк кадра")
    parser.add_argument("--output", help="куда сохранить размеченный ролик (.mp4)")
    parser.add_argument("--model", default="standard", help="профиль модели: fast | standard | accurate")
    parser.add_argument("--weights", help="конкретные веса, например yolo11n")
    parser.add_argument("--device", default="auto", help="auto | cpu | mps | cuda")
    parser.add_argument("--conf", type=float, default=0.25, help="порог уверенности детекции")
    parser.add_argument("--imgsz", type=int, help="размер входа модели, например 960")
    parser.add_argument("--stride", type=int, default=1, help="анализировать каждый N-й кадр")
    parser.add_argument("--loops", type=int, default=1, help="сколько кругов файла прогнать")
    parser.add_argument("--max-frames", type=int, help="ограничение на число кадров")
    parser.add_argument("--min-track-age", type=int, default=3, help="кадров до подтверждения трека")
    parser.add_argument("--dead-zone", type=float, default=0.004, help="мёртвая зона вокруг линии")
    parser.add_argument("--expected-in", type=int, help="ручной подсчёт входов")
    parser.add_argument("--expected-out", type=int, help="ручной подсчёт выходов")
    parser.add_argument("--quiet", action="store_true", help="без построчного вывода проходов")
    return parser.parse_args()


def load_markup(path: str | None) -> Markup:
    if not path:
        print("Разметка не задана: беру линию поперёк кадра на высоте 55 %.")
        return default_markup_for_frame()

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    markup = markup_from_dict(payload)
    problems = validate_markup(markup)
    for problem in problems:
        print(f"  ! разметка «{problem.object_id}»: {problem.message}")
    return markup


def describe_markup(markup: Markup) -> None:
    for line in markup.lines:
        side = "сверху" if line.entry_side < 0 else "снизу"
        print(
            f"  линия «{line.name}»: ({line.a.x:.2f}, {line.a.y:.2f}) — "
            f"({line.b.x:.2f}, {line.b.y:.2f}), вход {side}, считаем: {line.counts}"
        )
    for zone in markup.zones:
        kind = "очередь" if zone.kind == "queue" else "заполненность"
        print(f"  зона «{zone.name}» ({kind}): {len(zone.polygon)} точек")


def main() -> int:
    args = parse_args()
    video_path = Path(args.video)

    info = probe_video(video_path)
    print(f"Видео: {video_path.name}")
    print(
        f"  {info.resolution}, {info.fps:.1f} кадр/с, "
        f"{info.frame_count} кадров, {info.duration_seconds:.1f} с"
    )

    markup = load_markup(args.markup)
    describe_markup(markup)

    params = markup.counting_params(
        CountingParams(
            anchor=markup.anchor,
            min_track_age_frames=args.min_track_age,
            dead_zone=args.dead_zone,
        )
    )
    engine = CountingEngine(lines=markup.lines, zones=markup.zones, params=params)
    tracker = build_tracker(
        profile=args.model,
        weights=args.weights,
        device=args.device,
        confidence=args.conf,
        imgsz=args.imgsz,
    )
    tracker.load()
    print(f"  модель: {tracker.weights_name}, устройство: {tracker.device}, вход: {tracker.imgsz}")

    writer = None
    source = VideoFileSource(video_path, loop=args.loops > 1, realtime=False, stride=args.stride)
    base_time = time.time()
    processed = 0
    crossings_total = 0
    max_queue = 0
    started = time.monotonic()
    last_result = None

    try:
        source.open()
        for frame in source.frames():
            if frame.is_loop_start and processed > 0:
                engine.start_new_loop()
                tracker.reset()
                print(f"— начало круга {engine.loop_number} —")
                if engine.loop_number > args.loops:
                    break

            observations = [
                TrackObservation(box.track_id, box.bbox, box.confidence)
                for box in tracker.update(frame.image)
            ]
            result = engine.process_frame(
                observations, base_time + frame.position_seconds + (frame.loop_number - 1) * 1e5
            )
            last_result = result
            processed += 1
            max_queue = max(max_queue, result.queue_size)

            for crossing in result.crossings:
                crossings_total += 1
                if not args.quiet:
                    direction = "вход " if crossing.direction == "in" else "выход"
                    print(
                        f"  {direction} · кадр {frame.index:>6} · {frame.position_seconds:7.2f} с "
                        f"· трек #{crossing.track_id} · линия «{crossing.line_name}»"
                    )

            if args.output:
                import cv2

                canvas = render_frame(
                    frame.image,
                    result,
                    lines=markup.lines,
                    zones=markup.zones,
                    options=OverlayOptions(),
                    extra_counters=[f"Кадр {frame.index} · {frame.position_seconds:.1f} с"],
                )
                if writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(
                        args.output,
                        fourcc,
                        info.fps / args.stride,
                        (canvas.shape[1], canvas.shape[0]),
                    )
                writer.write(canvas)

            if args.max_frames and processed >= args.max_frames:
                break
    finally:
        source.close()
        if writer is not None:
            writer.release()

    elapsed = time.monotonic() - started
    speed = processed / elapsed if elapsed > 0 else 0.0

    print()
    print("Итог")
    print(f"  обработано кадров: {processed} за {elapsed:.1f} с ({speed:.1f} кадр/с)")
    print(f"  входы:  {engine.entries_today}")
    print(f"  выходы: {engine.exits_today}")
    print(f"  всего засчитанных проходов: {crossings_total}")
    if markup.zones:
        print(f"  максимальная очередь: {max_queue} чел")
    if last_result is not None:
        for line_id, counters in last_result.line_counters.items():
            print(f"  линия {line_id}: вход {counters['in']}, выход {counters['out']}")

    if args.expected_in is not None or args.expected_out is not None:
        print()
        print("Сверка с ручным подсчётом")
        for title, counted, expected in (
            ("входы", engine.entries_today, args.expected_in),
            ("выходы", engine.exits_today, args.expected_out),
        ):
            if expected is None:
                continue
            delta = counted - expected
            share = abs(delta) / expected * 100 if expected else 0.0
            verdict = "в пределах цели" if share <= 10 else "ХУЖЕ ЦЕЛИ (более 10 %)"
            print(f"  {title}: система {counted}, вручную {expected}, расхождение {delta:+d} ({share:.1f} %) — {verdict}")

    if args.output:
        print()
        print(f"Размеченный ролик: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

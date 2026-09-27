#!/usr/bin/env python3
"""Достать из видео несколько кадров, чтобы посмотреть на сцену.

Нужно перед разметкой: по кадрам видно ракурс, направление движения людей,
где ставить контрольную линию и где люди стоят, а где проходят мимо.

    python scripts/extract_frames.py --video data/videos/gate.mp4 --count 16
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cv.video_source import probe_video  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Извлечение кадров из видео")
    parser.add_argument("--video", required=True)
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--out", help="каталог для кадров (по умолчанию рядом с видео)")
    parser.add_argument("--width", type=int, default=960, help="ширина сохраняемых кадров")
    args = parser.parse_args()

    import cv2

    video_path = Path(args.video)
    info = probe_video(video_path)
    out_dir = Path(args.out) if args.out else video_path.parent / f"{video_path.stem}-frames"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{video_path.name}: {info.resolution}, {info.fps:.1f} кадр/с, {info.duration_seconds:.1f} с")

    capture = cv2.VideoCapture(str(video_path))
    total = info.frame_count or 0
    saved = []
    try:
        for index in range(args.count):
            position = int(total * (index + 0.5) / args.count) if total else index * 25
            capture.set(cv2.CAP_PROP_POS_FRAMES, position)
            ok, frame = capture.read()
            if not ok:
                continue
            if args.width and frame.shape[1] > args.width:
                scale = args.width / frame.shape[1]
                frame = cv2.resize(frame, (args.width, int(frame.shape[0] * scale)))
            target = out_dir / f"{video_path.stem}-{index:02d}-{position:06d}.jpg"
            cv2.imwrite(str(target), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
            saved.append(target)
    finally:
        capture.release()

    print(f"Сохранено кадров: {len(saved)} в {out_dir}")
    for path in saved:
        print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

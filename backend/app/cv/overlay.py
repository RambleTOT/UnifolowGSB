"""Отрисовка наложения аналитики на кадр.

Наложение отвечает на главный вопрос пользователя: «что именно система
считает» (ТЗ, раздел 5.2). Поэтому рисуются не только рамки людей, но и зоны,
линии, опорные точки и момент засчитывания прохода.

Тот же код рисует кадр для режима «Точный анализ», кадр события и размеченный
ролик офлайн-проверки — картинка везде одна и та же.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from app.cv.counting import Crossing, FrameResult, LineSpec, ZoneSpec
from app.cv.geometry import Point

# Цвета в BGR — как их ждёт OpenCV.
COLOR_MOVING = (203, 95, 27)
COLOR_QUEUE = (110, 159, 14)
COLOR_CROSSING = (11, 158, 245)
COLOR_ZONE_QUEUE = (255, 132, 75)
COLOR_ZONE_OCCUPANCY = (130, 190, 90)
COLOR_LINE = (11, 158, 245)
COLOR_ANCHOR = (255, 255, 255)
COLOR_PANEL = (32, 24, 22)
COLOR_TEXT = (255, 255, 255)

STATE_COLORS = {
    "moving": COLOR_MOVING,
    "queue": COLOR_QUEUE,
    "crossing": COLOR_CROSSING,
}

FONT_CANDIDATES = (
    Path(__file__).resolve().parents[1] / "assets" / "fonts" / "DejaVuSans.ttf",
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)


@dataclass(frozen=True, slots=True)
class OverlayOptions:
    show_boxes: bool = True
    show_track_ids: bool = True
    show_zones_and_lines: bool = True
    show_anchors: bool = True
    show_counters: bool = True


@lru_cache(maxsize=8)
def _font(size: int):
    """Шрифт с кириллицей: встроенные шрифты OpenCV её не умеют."""
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:  # pragma: no cover
                continue

    try:  # matplotlib приходит вместе с ultralytics и несёт DejaVu
        import matplotlib

        bundled = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        if bundled.exists():
            return ImageFont.truetype(str(bundled), size)
    except Exception:  # pragma: no cover  # noqa: BLE001
        pass

    return ImageFont.load_default()


def draw_text(image, text: str, origin: tuple[int, int], size: int = 16, color=COLOR_TEXT,
              background=None):
    """Подпись на кадре с поддержкой русского текста."""
    import numpy as np
    from PIL import Image, ImageDraw

    pil_image = Image.fromarray(image[:, :, ::-1])
    draw = ImageDraw.Draw(pil_image)
    font = _font(size)

    if background is not None:
        left, top, right, bottom = draw.textbbox(origin, text, font=font)
        draw.rectangle(
            (left - 6, top - 4, right + 6, bottom + 4),
            fill=tuple(int(channel) for channel in background[::-1]),
        )

    draw.text(origin, text, font=font, fill=tuple(int(channel) for channel in color[::-1]))
    image[:, :] = np.asarray(pil_image)[:, :, ::-1]
    return image


def _to_pixels(point: Point, width: int, height: int) -> tuple[int, int]:
    return int(round(point.x * width)), int(round(point.y * height))


def draw_zone(image, zone: ZoneSpec, people: int | None = None) -> None:
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    color = COLOR_ZONE_QUEUE if zone.kind == "queue" else COLOR_ZONE_OCCUPANCY
    points = np.array(
        [_to_pixels(point, width, height) for point in zone.polygon], dtype=np.int32
    )

    overlay = image.copy()
    cv2.fillPoly(overlay, [points], color)
    cv2.addWeighted(overlay, 0.14, image, 0.86, 0, dst=image)
    cv2.polylines(image, [points], isClosed=True, color=color, thickness=2)

    label = zone.name if people is None else f"{zone.name} · {people} чел"
    anchor_x = int(points[:, 0].mean())
    anchor_y = int(points[:, 1].min())
    draw_text(image, label, (anchor_x - 60, max(4, anchor_y - 26)), 16, COLOR_TEXT, color)


def draw_line(image, line: LineSpec, counters: dict[str, int] | None = None) -> None:
    """Линия со стрелкой в сторону «вход» и счётчиками по этой линии."""
    import cv2

    height, width = image.shape[:2]
    start = _to_pixels(line.a, width, height)
    end = _to_pixels(line.b, width, height)
    cv2.line(image, start, end, COLOR_LINE, 3)

    middle = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
    # Нормаль к линии, направленная в сторону входа.
    normal = (-dy / length, dx / length)
    direction = 1 if line.entry_side > 0 else -1
    arrow_end = (
        int(middle[0] + normal[0] * 46 * direction),
        int(middle[1] + normal[1] * 46 * direction),
    )
    cv2.arrowedLine(image, middle, arrow_end, COLOR_LINE, 3, tipLength=0.35)

    label = f"{line.name} · вход"
    if counters:
        label += f" · ↑{counters.get('in', 0)} / ↓{counters.get('out', 0)}"
    draw_text(image, label, (min(start[0], end[0]), max(4, min(start[1], end[1]) - 28)),
              16, COLOR_TEXT, COLOR_LINE)


def draw_objects(image, result: FrameResult, options: OverlayOptions) -> None:
    import cv2

    height, width = image.shape[:2]
    for obj in result.objects:
        color = STATE_COLORS.get(obj.state, COLOR_MOVING)
        x1, y1, x2, y2 = obj.bbox
        top_left = (int(x1 * width), int(y1 * height))
        bottom_right = (int(x2 * width), int(y2 * height))

        if options.show_boxes:
            thickness = 3 if obj.state == "crossing" else 2
            cv2.rectangle(image, top_left, bottom_right, color, thickness)

        if options.show_anchors:
            anchor = _to_pixels(obj.anchor, width, height)
            cv2.circle(image, anchor, 4, COLOR_ANCHOR, -1)
            cv2.circle(image, anchor, 5, color, 1)

        if options.show_track_ids:
            label = f"#{obj.track_id} · {obj.confidence * 100:.0f}%"
            draw_text(image, label, (top_left[0], max(4, top_left[1] - 22)), 14, COLOR_TEXT, color)


def draw_crossing_flash(image, crossings: Iterable[Crossing]) -> None:
    """Вспышка в момент засчитывания прохода: главный признак правильного подсчёта."""
    import cv2

    height, width = image.shape[:2]
    for crossing in crossings:
        point = _to_pixels(crossing.point, width, height)
        cv2.circle(image, point, 26, COLOR_CROSSING, 3)
        label = "ВХОД" if crossing.direction == "in" else "ВЫХОД"
        draw_text(image, f"{label} · {crossing.line_name}", (point[0] + 30, point[1] - 14),
                  18, COLOR_TEXT, COLOR_CROSSING)


def draw_counters(image, result: FrameResult, extra: Sequence[str] = ()) -> None:
    """Бегущие счётчики: то, что сверяют с ручным подсчётом."""
    import cv2

    height, width = image.shape[:2]
    lines = [
        f"В кадре: {result.people_in_frame} чел    Очередь: {result.queue_size} чел",
        f"Круг {result.loop_number}: ↑ {result.loop_entries} / ↓ {result.loop_exits} чел",
        f"За сутки: ↑ {result.entries_today} / ↓ {result.exits_today} · внутри {result.inside_now} чел",
    ]
    if result.avg_wait_seconds is not None:
        lines.append(f"Ожидание сейчас: {result.avg_wait_seconds / 60:.1f} мин")
    lines.extend(extra)

    panel_height = 24 * len(lines) + 18
    panel = image[0:panel_height, 0:width].copy()
    cv2.rectangle(panel, (0, 0), (width, panel_height), COLOR_PANEL, -1)
    cv2.addWeighted(panel, 0.72, image[0:panel_height, 0:width], 0.28, 0,
                    dst=image[0:panel_height, 0:width])

    for index, text in enumerate(lines):
        draw_text(image, text, (14, 10 + index * 24), 17, COLOR_TEXT)


def render_frame(
    image,
    result: FrameResult,
    lines: Sequence[LineSpec] = (),
    zones: Sequence[ZoneSpec] = (),
    options: OverlayOptions | None = None,
    extra_counters: Sequence[str] = (),
):
    """Собрать кадр с полным наложением. Исходный кадр не меняется."""
    options = options or OverlayOptions()
    canvas = image.copy()

    if options.show_zones_and_lines:
        for zone in zones:
            draw_zone(canvas, zone, result.zone_counts.get(zone.id))
        for line in lines:
            draw_line(canvas, line, result.line_counters.get(line.id))

    draw_objects(canvas, result, options)
    draw_crossing_flash(canvas, result.crossings)

    if options.show_counters:
        draw_counters(canvas, result, extra_counters)

    return canvas

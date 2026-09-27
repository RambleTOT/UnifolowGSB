"""Ядро подсчёта: линии, зоны, состояние треков, время ожидания.

Здесь живёт вся доменная логика «сколько вошло, сколько вышло, сколько стоит в
очереди и сколько ждёт». Модуль не знает ни про модель распознавания, ни про
базу данных, ни про веб: на вход приходят треки кадра, на выходе — счётчики и
события кадра. Тот же код используется и в приложении, и в scripts/evaluate.py,
чтобы проверка точности проверяла ровно то, что работает в продукте.

Термины — по ТЗ, раздел 2: источник, зона анализа, контрольная линия, трек, круг.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Sequence

from app.cv.geometry import (
    AnchorMode,
    Point,
    bbox_anchor,
    distance,
    distance_point_to_segment,
    point_in_polygon,
    segments_intersect,
    side_of_line,
)

Direction = Literal["in", "out"]
LineCounts = Literal["in", "out", "both"]
ZoneKind = Literal["queue", "occupancy"]
ObjectStateName = Literal["moving", "queue", "crossing"]


@dataclass(frozen=True, slots=True)
class LineSpec:
    """Контрольная линия: отрезок и сторона, которая считается входом."""

    id: str
    name: str
    a: Point
    b: Point
    entry_side: int = 1  # +1 или -1 — знак стороны, переход на которую считается входом
    counts: LineCounts = "both"


@dataclass(frozen=True, slots=True)
class ZoneSpec:
    """Зона анализа: очередь или заполненность."""

    id: str
    name: str
    polygon: tuple[Point, ...]
    kind: ZoneKind = "queue"
    min_dwell_seconds: float = 5.0
    capacity: int | None = None


@dataclass(frozen=True, slots=True)
class CountingParams:
    """Параметры подсчёта. Значения по умолчанию подобраны под съёмку под углом."""

    anchor: AnchorMode = "bottom_center"
    # Трек должен прожить столько кадров, прежде чем его проходы засчитываются.
    min_track_age_frames: int = 3
    # Мёртвая зона вокруг линии в долях кадра: дрожание рамки не даёт повторов.
    dead_zone: float = 0.004
    # Минимальный интервал между двумя проходами одного трека через одну линию.
    crossing_debounce_seconds: float = 1.0
    # Сколько секунд объект показывается как «пересекает линию».
    crossing_state_seconds: float = 1.0
    # Через сколько секунд без наблюдений трек считается потерянным.
    lost_track_seconds: float = 2.0
    # Наследование времени ожидания при смене номера трека внутри зоны.
    inherit_max_gap_seconds: float = 2.0
    inherit_max_distance: float = 0.08


@dataclass(frozen=True, slots=True)
class TrackObservation:
    """Один трек на одном кадре — то, что отдаёт трекер."""

    track_id: int
    bbox: tuple[float, float, float, float]  # нормированные x1, y1, x2, y2
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class Crossing:
    """Засчитанный проход: он попадает в метаданные кадра и виден в интерфейсе."""

    line_id: str
    line_name: str
    direction: Direction
    track_id: int
    at: float
    point: Point


@dataclass(frozen=True, slots=True)
class WaitRecord:
    """Завершённое ожидание: человек покинул зону очереди."""

    zone_id: str
    seconds: float
    ended_at: float


@dataclass(frozen=True, slots=True)
class ObjectState:
    track_id: int
    bbox: tuple[float, float, float, float]
    confidence: float
    anchor: Point
    state: ObjectStateName


@dataclass(frozen=True, slots=True)
class FrameResult:
    """Результат обработки одного кадра."""

    at: float
    objects: tuple[ObjectState, ...]
    crossings: tuple[Crossing, ...]
    completed_waits: tuple[WaitRecord, ...]
    people_in_frame: int
    people_in_zone: int
    queue_size: int
    avg_wait_seconds: float | None
    zone_counts: dict[str, int]
    line_counters: dict[str, dict[str, int]]
    entries_today: int
    exits_today: int
    inside_now: int
    loop_number: int
    loop_entries: int
    loop_exits: int
    previous_loop_entries: int | None
    previous_loop_exits: int | None


@dataclass
class _TrackState:
    track_id: int
    first_seen_at: float
    last_seen_at: float
    age_frames: int = 0
    last_anchor: Point | None = None
    last_anchor_outside: dict[str, Point] = field(default_factory=dict)
    committed_side: dict[str, int] = field(default_factory=dict)
    last_crossing_at: dict[str, float] = field(default_factory=dict)
    zone_entered_at: dict[str, float] = field(default_factory=dict)
    crossing_until: float = 0.0


@dataclass
class _OrphanWait:
    """Ожидание потерянного трека: ждёт, не подхватит ли его новый номер."""

    zone_id: str
    entered_at: float
    ended_at: float
    lost_at: float
    anchor: Point
    min_dwell_seconds: float


class CountingEngine:
    """Считает проходы через линии и время в зонах по потоку треков.

    Состояние живёт в пределах одного круга воспроизведения: на границе круга
    (`start_new_loop`) треки сбрасываются, и ни один выход не засчитывается —
    иначе конец файла давал бы пачку ложных проходов (задание, раздел 5.1).
    """

    def __init__(
        self,
        lines: Sequence[LineSpec] = (),
        zones: Sequence[ZoneSpec] = (),
        params: CountingParams | None = None,
        timezone_offset_hours: float = 0.0,
    ) -> None:
        self.lines: tuple[LineSpec, ...] = tuple(lines)
        self.zones: tuple[ZoneSpec, ...] = tuple(zones)
        self.params = params or CountingParams()
        self.timezone_offset_hours = timezone_offset_hours

        self._tracks: dict[int, _TrackState] = {}
        self._orphans: list[_OrphanWait] = []

        self._line_counters: dict[str, dict[str, int]] = {
            line.id: {"in": 0, "out": 0} for line in self.lines
        }
        self.entries_today = 0
        self.exits_today = 0
        self._current_day: str | None = None

        self.loop_number = 1
        self.loop_entries = 0
        self.loop_exits = 0
        self.previous_loop_entries: int | None = None
        self.previous_loop_exits: int | None = None

    # --- разметка -----------------------------------------------------------

    def set_geometry(self, lines: Sequence[LineSpec], zones: Sequence[ZoneSpec]) -> None:
        """Применить новую разметку. История не пересчитывается (ТЗ, 5.7.2)."""
        self.lines = tuple(lines)
        self.zones = tuple(zones)
        for line in self.lines:
            self._line_counters.setdefault(line.id, {"in": 0, "out": 0})
        for track in self._tracks.values():
            track.committed_side.clear()
            track.last_anchor_outside.clear()
            track.zone_entered_at.clear()
        self._orphans.clear()

    # --- круг воспроизведения ----------------------------------------------

    def start_new_loop(self) -> None:
        """Файл начался заново: сбросить треки, закрыть итог круга."""
        self.previous_loop_entries = self.loop_entries
        self.previous_loop_exits = self.loop_exits
        self.loop_entries = 0
        self.loop_exits = 0
        self.loop_number += 1
        self.reset_tracks()

    def reset_tracks(self) -> None:
        """Забыть всех, кто сейчас в кадре, не трогая счётчики.

        Нужно при разрыве во времени: поток переподключился, воспроизведение
        прыгнуло вперёд, компьютер засыпал. Незавершённые ожидания при этом не
        записываются — их длительность уже не известна. Иначе выходит две беды:
        трекер после сброса снова раздаёт номера с единицы и новый человек
        наследует состояние старого с тем же номером, а ожидание вбирает в
        себя весь перерыв.
        """
        self._tracks.clear()
        self._orphans.clear()

    # --- обработка кадра ----------------------------------------------------

    def process_frame(
        self,
        observations: Sequence[TrackObservation],
        at: float,
    ) -> FrameResult:
        self._roll_day_if_needed(at)

        params = self.params
        crossings: list[Crossing] = []
        completed_waits: list[WaitRecord] = []
        seen_ids: set[int] = set()
        objects: list[ObjectState] = []
        zone_counts: dict[str, int] = {zone.id: 0 for zone in self.zones}
        queue_dwells: list[float] = []

        for observation in observations:
            seen_ids.add(observation.track_id)
            anchor = bbox_anchor(observation.bbox, params.anchor)
            track = self._tracks.get(observation.track_id)
            if track is None:
                track = _TrackState(
                    track_id=observation.track_id,
                    first_seen_at=at,
                    last_seen_at=at,
                )
                self._tracks[observation.track_id] = track

            track.age_frames += 1
            track.last_seen_at = at

            crossings.extend(self._update_lines(track, anchor, at))

            in_queue = False
            for zone in self.zones:
                inside = point_in_polygon(zone.polygon, anchor)
                if inside:
                    if zone.id not in track.zone_entered_at:
                        track.zone_entered_at[zone.id] = self._inherit_wait_start(
                            zone.id, anchor, at, observation.track_id
                        )
                    dwell = at - track.zone_entered_at[zone.id]
                    if zone.kind == "queue":
                        if dwell >= zone.min_dwell_seconds:
                            zone_counts[zone.id] += 1
                            queue_dwells.append(dwell)
                            in_queue = True
                    else:
                        zone_counts[zone.id] += 1
                elif zone.id in track.zone_entered_at:
                    wait = self._close_wait(zone, track, at)
                    if wait is not None:
                        completed_waits.append(wait)

            track.last_anchor = anchor

            if at < track.crossing_until:
                state: ObjectStateName = "crossing"
            elif in_queue:
                state = "queue"
            else:
                state = "moving"
            objects.append(
                ObjectState(
                    track_id=observation.track_id,
                    bbox=observation.bbox,
                    confidence=observation.confidence,
                    anchor=anchor,
                    state=state,
                )
            )

        completed_waits.extend(self._expire_tracks(seen_ids, at))
        completed_waits.extend(self._expire_orphans(at))

        queue_size = sum(
            count for zone, count in self._zone_pairs(zone_counts) if zone.kind == "queue"
        )
        people_in_zone = sum(
            count for zone, count in self._zone_pairs(zone_counts) if zone.kind == "occupancy"
        )
        avg_wait = sum(queue_dwells) / len(queue_dwells) if queue_dwells else None

        return FrameResult(
            at=at,
            objects=tuple(objects),
            crossings=tuple(crossings),
            completed_waits=tuple(completed_waits),
            people_in_frame=len(observations),
            people_in_zone=people_in_zone,
            queue_size=queue_size,
            avg_wait_seconds=avg_wait,
            zone_counts=dict(zone_counts),
            line_counters={key: dict(value) for key, value in self._line_counters.items()},
            entries_today=self.entries_today,
            exits_today=self.exits_today,
            inside_now=max(0, self.entries_today - self.exits_today),
            loop_number=self.loop_number,
            loop_entries=self.loop_entries,
            loop_exits=self.loop_exits,
            previous_loop_entries=self.previous_loop_entries,
            previous_loop_exits=self.previous_loop_exits,
        )

    # --- внутреннее ---------------------------------------------------------

    def _zone_pairs(self, zone_counts: dict[str, int]):
        for zone in self.zones:
            yield zone, zone_counts.get(zone.id, 0)

    def _update_lines(self, track: _TrackState, anchor: Point, at: float) -> list[Crossing]:
        params = self.params
        crossings: list[Crossing] = []

        for line in self.lines:
            gap = distance_point_to_segment(anchor, line.a, line.b)
            if gap <= params.dead_zone:
                # В мёртвой зоне сторона не фиксируется: рамка дрожит на линии.
                continue

            current_side = side_of_line(line.a, line.b, anchor)
            if current_side == 0:
                continue

            previous_side = track.committed_side.get(line.id)
            previous_anchor = track.last_anchor_outside.get(line.id)
            track.committed_side[line.id] = current_side
            track.last_anchor_outside[line.id] = anchor

            if previous_side is None or previous_anchor is None:
                # Первое наблюдение стороны: трек, появившийся уже за линией,
                # прохода не даёт — засчитываем только переход между сторонами.
                continue
            if previous_side == current_side:
                continue
            if track.age_frames < params.min_track_age_frames:
                continue
            if not segments_intersect(previous_anchor, anchor, line.a, line.b):
                # Точка сменила сторону прямой, но мимо самого отрезка.
                continue
            last_at = track.last_crossing_at.get(line.id)
            if last_at is not None and at - last_at < params.crossing_debounce_seconds:
                continue

            direction: Direction = "in" if current_side == line.entry_side else "out"
            if line.counts != "both" and line.counts != direction:
                continue

            track.last_crossing_at[line.id] = at
            track.crossing_until = at + params.crossing_state_seconds
            self._line_counters.setdefault(line.id, {"in": 0, "out": 0})[direction] += 1
            if direction == "in":
                self.entries_today += 1
                self.loop_entries += 1
            else:
                self.exits_today += 1
                self.loop_exits += 1

            crossings.append(
                Crossing(
                    line_id=line.id,
                    line_name=line.name,
                    direction=direction,
                    track_id=track.track_id,
                    at=at,
                    point=anchor,
                )
            )

        return crossings

    def _inherit_wait_start(
        self, zone_id: str, anchor: Point, at: float, track_id: int
    ) -> float:
        """Смена номера трека внутри зоны не должна обнулять ожидание.

        Трекер иногда теряет человека и выдаёт ему новый номер. Если рядом с
        местом пропажи и вскоре после неё появился новый трек, он продолжает
        ожидание прежнего, а не начинает его заново.
        """
        params = self.params
        best_distance = params.inherit_max_distance
        best_entered: float | None = None
        source_track: _TrackState | None = None
        source_orphan: int | None = None

        for other in self._tracks.values():
            if other.track_id == track_id or zone_id not in other.zone_entered_at:
                continue
            # Трек, видимый в этом же кадре, — это другой человек.
            if other.last_seen_at >= at or other.last_anchor is None:
                continue
            if at - other.last_seen_at > params.inherit_max_gap_seconds:
                continue
            gap = distance(other.last_anchor, anchor)
            if gap <= best_distance:
                best_distance = gap
                best_entered = other.zone_entered_at[zone_id]
                source_track, source_orphan = other, None

        for index, orphan in enumerate(self._orphans):
            if orphan.zone_id != zone_id:
                continue
            if at - orphan.lost_at > params.inherit_max_gap_seconds:
                continue
            gap = distance(orphan.anchor, anchor)
            if gap <= best_distance:
                best_distance = gap
                best_entered = orphan.entered_at
                source_track, source_orphan = None, index

        if best_entered is None:
            return at

        # Ожидание передаётся новому треку, а не удваивается.
        if source_track is not None:
            source_track.zone_entered_at.pop(zone_id, None)
        elif source_orphan is not None:
            self._orphans.pop(source_orphan)
        return best_entered

    def _close_wait(self, zone: ZoneSpec, track: _TrackState, at: float) -> WaitRecord | None:
        entered_at = track.zone_entered_at.pop(zone.id, None)
        if entered_at is None or zone.kind != "queue":
            return None
        seconds = at - entered_at
        if seconds < zone.min_dwell_seconds:
            return None
        return WaitRecord(zone_id=zone.id, seconds=seconds, ended_at=at)

    def _expire_tracks(self, seen_ids: set[int], at: float) -> list[WaitRecord]:
        """Потерянные треки: ожидание переходит в «осиротевшие», а не пропадает."""
        completed: list[WaitRecord] = []
        lost_ids = [
            track_id
            for track_id, track in self._tracks.items()
            if track_id not in seen_ids
            and at - track.last_seen_at > self.params.lost_track_seconds
        ]

        for track_id in lost_ids:
            track = self._tracks.pop(track_id)
            for zone in self.zones:
                entered_at = track.zone_entered_at.pop(zone.id, None)
                if entered_at is None or zone.kind != "queue":
                    continue
                if track.last_anchor is None:
                    wait = self._wait_record(zone, entered_at, track.last_seen_at)
                    if wait is not None:
                        completed.append(wait)
                    continue
                self._orphans.append(
                    _OrphanWait(
                        zone_id=zone.id,
                        entered_at=entered_at,
                        ended_at=track.last_seen_at,
                        lost_at=at,
                        anchor=track.last_anchor,
                        min_dwell_seconds=zone.min_dwell_seconds,
                    )
                )
        return completed

    def _expire_orphans(self, at: float) -> list[WaitRecord]:
        """Никто не подхватил ожидание за отведённое время — оно завершилось."""
        limit = self.params.inherit_max_gap_seconds
        completed: list[WaitRecord] = []
        alive: list[_OrphanWait] = []

        for orphan in self._orphans:
            if at - orphan.lost_at <= limit:
                alive.append(orphan)
                continue
            seconds = orphan.ended_at - orphan.entered_at
            if seconds >= orphan.min_dwell_seconds:
                completed.append(
                    WaitRecord(zone_id=orphan.zone_id, seconds=seconds, ended_at=orphan.ended_at)
                )

        self._orphans = alive
        return completed

    def _wait_record(self, zone: ZoneSpec, entered_at: float, ended_at: float) -> WaitRecord | None:
        seconds = ended_at - entered_at
        if zone.kind != "queue" or seconds < zone.min_dwell_seconds:
            return None
        return WaitRecord(zone_id=zone.id, seconds=seconds, ended_at=ended_at)

    def _roll_day_if_needed(self, at: float) -> None:
        """«Внутри сейчас» считается с начала суток по времени объекта."""
        moment = datetime.fromtimestamp(at, tz=timezone.utc)
        local_day = moment.timestamp() + self.timezone_offset_hours * 3600
        day_key = datetime.fromtimestamp(local_day, tz=timezone.utc).strftime("%Y-%m-%d")
        if self._current_day is None:
            self._current_day = day_key
            return
        if day_key != self._current_day:
            self._current_day = day_key
            self.entries_today = 0
            self.exits_today = 0

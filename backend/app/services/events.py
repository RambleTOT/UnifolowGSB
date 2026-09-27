"""Правила событий.

Событие — это эпизод, а не момент (ТЗ, раздел 3.4). Оно открывается, только
если отклонение продержалось заданное время, живёт, пока условие выполняется,
и закрывается с запасом — иначе на границе порога рождалась бы череда
одинаковых событий вместо одного.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.services.aggregation import BucketPayload
from app.services.settings import SystemSettings

LOGGER = logging.getLogger(__name__)

EventType = Literal[
    "queue_spike", "slow_movement", "checkpoint_overload", "abnormal_traffic", "camera_drop"
]
Severity = Literal["low", "medium", "high", "critical"]

# Значение должно опуститься заметно ниже порога, иначе событие будет мигать.
CLOSE_RATIO = 0.9

SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}

TITLES: dict[str, str] = {
    "queue_spike": "Рост очереди",
    "slow_movement": "Длительное ожидание",
    "checkpoint_overload": "Перегрузка КПП",
    "abnormal_traffic": "Нетипичный трафик",
    "camera_drop": "Проблема с источником",
}


@dataclass(frozen=True, slots=True)
class OpenEvent:
    type: EventType
    severity: Severity
    title: str
    description: str
    started_at: datetime
    metric_value: float
    threshold: float


@dataclass(frozen=True, slots=True)
class UpdateEvent:
    type: EventType
    severity: Severity
    peak_value: float
    metric_value: float


@dataclass(frozen=True, slots=True)
class CloseEvent:
    type: EventType
    ended_at: datetime


Action = OpenEvent | UpdateEvent | CloseEvent


@dataclass
class _RuleState:
    """Состояние одного правила по одному источнику."""

    above_since: datetime | None = None
    below_since: datetime | None = None
    active: bool = False
    peak: float = 0.0
    severity: Severity = "medium"


def queue_severity(value: float, threshold: float) -> Severity:
    if value > threshold * 2:
        return "critical"
    if value > threshold * 1.4:
        return "high"
    return "medium"


def wait_severity(value: float, threshold: float) -> Severity:
    if value > threshold * 2.4:
        return "critical"
    if value > threshold * 1.6:
        return "high"
    return "medium"


def checkpoint_severity(value: float, threshold: float) -> Severity:
    if value > threshold * 2:
        return "critical"
    if value > threshold * 1.4:
        return "high"
    return "medium"


@dataclass
class EventEngine:
    """Оценивает интервалы одного источника и выдаёт действия над событиями."""

    source_id: int
    scope: str
    settings: SystemSettings
    states: dict[str, _RuleState] = field(default_factory=dict)

    def update_settings(self, settings: SystemSettings) -> None:
        self.settings = settings

    def observe(self, payload: BucketPayload, source_name: str) -> list[Action]:
        actions: list[Action] = []
        minimum = float(self.settings.event_min_duration_seconds)
        moment = payload.started_at

        # Очередь: ориентируемся на пик внутри интервала, а не на среднее —
        # короткий всплеск тоже заметен оператору.
        if payload.zones or payload.queue_max:
            actions += self._rule(
                "queue_spike",
                value=payload.queue_max,
                threshold=float(self.settings.queue_threshold),
                severity=queue_severity,
                moment=moment,
                minimum=minimum,
                source_name=source_name,
                description=(
                    "Очередь держится выше порога. Стоит посмотреть, все ли линии обслуживания открыты."
                ),
            )

        # Ожидание: считается по завершённым ожиданиям в интервале.
        if payload.wait_count:
            wait_minutes = payload.wait_sum_seconds / payload.wait_count / 60.0
            actions += self._rule(
                "slow_movement",
                value=wait_minutes,
                threshold=float(self.settings.wait_threshold_minutes),
                severity=wait_severity,
                moment=moment,
                minimum=minimum,
                source_name=source_name,
                description="Люди ждут дольше норматива: очередь движется медленно.",
            )

        # Поток через линию приводим к «человек в минуту» — порог задан именно так.
        if self.scope == "gate":
            seconds = max(1.0, float(self.settings.aggregation_seconds))
            per_minute = (payload.entered + payload.exited) * 60.0 / seconds
            actions += self._rule(
                "checkpoint_overload",
                value=per_minute,
                threshold=float(self.settings.checkpoint_threshold_per_minute),
                severity=checkpoint_severity,
                moment=moment,
                minimum=minimum,
                source_name=source_name,
                description="Через проход идёт больше людей, чем он рассчитан пропускать.",
            )

        # Проблема с источником: степень зависит от того, отстал анализ или
        # данные пропали совсем.
        health = payload.health
        if health != "online" and getattr(payload, "warming", False):
            # Прогрев после запуска: просадка ожидаема, событие не заводим, но и
            # уже открытое не закрываем — источник ещё не показал, что здоров.
            pass
        elif health != "online":
            severity: Severity = "critical" if health == "offline" else "medium"
            # У проблемы с источником нет числового порога: сравнивать нечего,
            # поэтому правило срабатывает от самого факта, а в событие попадает
            # понятная пара «1 из 1».
            actions += self._rule(
                "camera_drop",
                value=1.0,
                threshold=0.0,
                severity=lambda *_: severity,
                moment=moment,
                minimum=30.0 if health == "degraded" else 0.0,
                source_name=source_name,
                description=(
                    "Видеопоток недоступен: данные не поступают."
                    if health == "offline"
                    else "Анализ отстаёт от воспроизведения: счётчики могут запаздывать."
                ),
                force_value=1.0,
                force_threshold=1.0,
            )
        else:
            actions += self._close_if_active("camera_drop", moment)

        return actions

    def _rule(
        self,
        rule: EventType,
        *,
        value: float,
        threshold: float,
        severity,
        moment: datetime,
        minimum: float,
        source_name: str,
        description: str,
        force_value: float | None = None,
        force_threshold: float | None = None,
    ) -> list[Action]:
        state = self.states.setdefault(rule, _RuleState())
        actions: list[Action] = []
        exceeded = value > threshold

        if exceeded:
            state.below_since = None
            if state.above_since is None:
                state.above_since = moment

            held = (moment - state.above_since).total_seconds()
            level: Severity = severity(value, threshold)

            if not state.active and held >= minimum:
                state.active = True
                state.peak = value
                state.severity = level
                actions.append(
                    OpenEvent(
                        type=rule,
                        severity=level,
                        title=f"{TITLES[rule]} · {source_name}",
                        description=description,
                        started_at=state.above_since,
                        metric_value=force_value if force_value is not None else value,
                        threshold=force_threshold if force_threshold is not None else threshold,
                    )
                )
            elif state.active:
                state.peak = max(state.peak, value)
                # Приоритет может повышаться, но не понижается, пока эпизод идёт.
                if SEVERITY_ORDER[level] > SEVERITY_ORDER[state.severity]:
                    state.severity = level
                actions.append(
                    UpdateEvent(
                        type=rule,
                        severity=state.severity,
                        peak_value=state.peak,
                        metric_value=value,
                    )
                )
            return actions

        state.above_since = None
        if not state.active:
            state.below_since = None
            return actions

        # Закрываем с запасом: возврат ровно к порогу ещё не значит, что всё прошло.
        if value <= threshold * CLOSE_RATIO:
            if state.below_since is None:
                state.below_since = moment
            if (moment - state.below_since).total_seconds() >= minimum:
                state.active = False
                state.below_since = None
                actions.append(CloseEvent(type=rule, ended_at=moment))
        else:
            state.below_since = None

        return actions

    def _close_if_active(self, rule: EventType, moment: datetime) -> list[Action]:
        state = self.states.get(rule)
        if state is None or not state.active:
            if state is not None:
                state.above_since = None
            return []
        state.active = False
        state.above_since = None
        state.below_since = None
        return [CloseEvent(type=rule, ended_at=moment)]

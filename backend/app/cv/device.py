"""Выбор устройства для инференса: CUDA → MPS → CPU.

Железо заранее неизвестно (задание, раздел 1), поэтому устройство определяется
автоматически, а в интерфейсе показывается как справочная информация.
"""

from __future__ import annotations

import logging
from functools import lru_cache

LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def resolve_device(preferred: str = "auto") -> str:
    if preferred and preferred != "auto":
        return preferred

    try:
        import torch
    except ImportError:  # pragma: no cover - окружение без torch
        LOGGER.warning("torch не установлен, анализ пойдёт на CPU")
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def device_label(device: str) -> str:
    """Подпись устройства для интерфейса, на русском."""
    if device.startswith("cuda"):
        return "Видеокарта NVIDIA"
    if device == "mps":
        return "Ускоритель Apple"
    return "Процессор"

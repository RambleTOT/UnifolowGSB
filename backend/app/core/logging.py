"""Журнал сервера: коротко и по делу, с русскими сообщениями."""

from __future__ import annotations

import logging
import sys

FORMAT = "%(asctime)s  %(levelname)-7s %(name)s  %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(FORMAT, datefmt="%H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(level)
    # Ultralytics и multipart слишком разговорчивы для рабочего журнала.
    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    logging.getLogger("python_multipart").setLevel(logging.WARNING)

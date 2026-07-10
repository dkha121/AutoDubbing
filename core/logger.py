"""Centralised logging: daily rotating file + an in-app Qt signal sink."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from utils.path_utils import ensure_dir, package_root

_CONFIGURED = False
_LOG_DIR = package_root() / "data" / "logs"


class QtLogHandler(logging.Handler):
    """A logging handler that forwards records to a callback (e.g. a Qt signal).

    The UI registers a callback so log lines appear in the Logs panel without
    coupling the logging layer to PySide6.
    """

    def __init__(self) -> None:
        super().__init__()
        self._callbacks: list = []
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    def add_callback(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # pragma: no cover - formatting guard
            return
        for cb in list(self._callbacks):
            try:
                cb(msg, record.levelno)
            except Exception:  # pragma: no cover - never let UI break logging
                pass


qt_handler = QtLogHandler()


def setup_logging(level: int = logging.INFO) -> Path:
    """Configure root logging once. Returns the log directory."""
    global _CONFIGURED
    log_dir = ensure_dir(_LOG_DIR)
    if _CONFIGURED:
        return log_dir

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "app.log", when="midnight", backupCount=14, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    root.addHandler(qt_handler)

    _CONFIGURED = True
    return log_dir


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)

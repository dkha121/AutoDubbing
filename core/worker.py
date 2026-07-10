"""Generic background worker built on QThread.

Heavy tasks (ffmpeg, ASR, translation, TTS, render) run inside a Worker so the
GUI never blocks. Workers emit progress/log/finished/failed signals and support
cooperative cancellation via a threading.Event passed to the task function.
"""
from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from core.logger import get_logger

logger = get_logger(__name__)


class WorkerSignals(QObject):
    progress = Signal(float, str)   # 0..100, message
    log = Signal(str, int)          # message, levelno
    finished = Signal(object)       # result
    failed = Signal(str)            # error message


class TaskContext:
    """Passed to task functions so they can report progress and check cancel."""

    def __init__(self, signals: WorkerSignals, cancel_event: threading.Event) -> None:
        self._signals = signals
        self._cancel = cancel_event

    def progress(self, percent: float, message: str = "") -> None:
        self._signals.progress.emit(float(percent), message)

    def log(self, message: str, level: int = 20) -> None:
        self._signals.log.emit(message, level)

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise CancelledError("Task cancelled by user")


class CancelledError(Exception):
    pass


class Worker(QThread):
    """Runs `fn(ctx, *args, **kwargs)` in a background thread."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:  # noqa: D401 - QThread entry point
        ctx = TaskContext(self.signals, self._cancel_event)
        try:
            result = self._fn(ctx, *self._args, **self._kwargs)
            if self._cancel_event.is_set():
                self.signals.failed.emit("Cancelled")
            else:
                self.signals.finished.emit(result)
        except CancelledError:
            self.signals.failed.emit("Cancelled")
        except Exception as exc:  # noqa: BLE001 - surface any task error to UI
            logger.exception("Worker task failed")
            self.signals.failed.emit(f"{exc}\n{traceback.format_exc()}")

"""Realtime log panel widget that subscribes to the logging Qt handler."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from core.logger import qt_handler

_LEVEL_COLORS = {
    logging.DEBUG: "#888888",
    logging.INFO: "#dddddd",
    logging.WARNING: "#e0a000",
    logging.ERROR: "#ff5555",
    logging.CRITICAL: "#ff0000",
}


class _LogBridge(QObject):
    """Marshals log callbacks (from any thread) onto the Qt event loop."""
    message = Signal(str, int)


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        layout.addWidget(self.view)

        self._bridge = _LogBridge()
        self._bridge.message.connect(self._append)
        qt_handler.add_callback(self._on_log)

    def _on_log(self, message: str, levelno: int) -> None:
        # Called from arbitrary threads -> hop to GUI thread via signal.
        self._bridge.message.emit(message, levelno)

    def _append(self, message: str, levelno: int) -> None:
        color = _LEVEL_COLORS.get(levelno, "#dddddd")
        self.view.appendHtml(f'<span style="color:{color}">{message}</span>')
        self.view.moveCursor(QTextCursor.End)

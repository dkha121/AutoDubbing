"""Simple timeline widget: draws subtitle segments along a horizontal track."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from models.subtitle_segment import SubtitleSegment


class TimelineWidget(QWidget):
    seek_requested = Signal(float)  # seconds

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(60)
        self._segments: list[SubtitleSegment] = []
        self._duration = 0.0
        self._playhead = 0.0

    def set_segments(self, segments: list[SubtitleSegment], duration: float) -> None:
        self._segments = segments
        self._duration = max(duration, segments[-1].end if segments else 0.0, 1.0)
        self.update()

    def set_playhead(self, seconds: float) -> None:
        self._playhead = seconds
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._duration > 0:
            frac = event.position().x() / max(1, self.width())
            self.seek_requested.emit(frac * self._duration)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        if self._duration <= 0:
            painter.setPen(QPen(QColor("#666")))
            painter.drawText(self.rect(), Qt.AlignCenter, "No timeline")
            return
        w = self.width()
        h = self.height()
        scale = w / self._duration
        painter.setBrush(QBrush(QColor("#3a7bd5")))
        painter.setPen(Qt.NoPen)
        for seg in self._segments:
            x = seg.start * scale
            seg_w = max(1.0, seg.duration * scale)
            painter.drawRect(QRectF(x, h * 0.25, seg_w, h * 0.5))
        # Playhead
        painter.setPen(QPen(QColor("#ff5555"), 2))
        px = self._playhead * scale
        painter.drawLine(px, 0, px, h)

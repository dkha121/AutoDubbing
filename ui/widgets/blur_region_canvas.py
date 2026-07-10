"""Blur region canvas: draw rectangles over a frame to define blur/logo regions.

The canvas works in the video's pixel coordinate space. The widget scales a
background frame (if provided) to fit, while regions are stored in real video
pixels so they map straight to FFmpeg filter coordinates.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from models.blur_region import BlurRegion


class BlurRegionCanvas(QWidget):
    region_added = Signal(object)   # BlurRegion
    region_selected = Signal(str)   # region id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self._regions: list[BlurRegion] = []
        self._frame: QPixmap | None = None
        self._video_w = 1920
        self._video_h = 1080
        self._drag_start: QPoint | None = None
        self._drag_cur: QPoint | None = None
        self._selected_id: str | None = None

    def set_video_size(self, width: int, height: int) -> None:
        self._video_w = max(1, width)
        self._video_h = max(1, height)
        self.update()

    def set_frame(self, pixmap: QPixmap | None) -> None:
        self._frame = pixmap
        self.update()

    def set_regions(self, regions: list[BlurRegion]) -> None:
        self._regions = regions
        self.update()

    def regions(self) -> list[BlurRegion]:
        return self._regions

    # ---- coordinate mapping ------------------------------------------
    def _draw_rect(self) -> QRect:
        """The on-screen rectangle the video maps into (letterboxed fit)."""
        ww, wh = self.width(), self.height()
        vw, vh = self._video_w, self._video_h
        scale = min(ww / vw, wh / vh)
        dw, dh = int(vw * scale), int(vh * scale)
        return QRect((ww - dw) // 2, (wh - dh) // 2, dw, dh)

    def _to_video(self, point: QPoint) -> tuple[int, int]:
        r = self._draw_rect()
        sx = self._video_w / max(1, r.width())
        sy = self._video_h / max(1, r.height())
        return int((point.x() - r.x()) * sx), int((point.y() - r.y()) * sy)

    def _to_screen(self, x: int, y: int, w: int, h: int) -> QRect:
        r = self._draw_rect()
        sx = r.width() / self._video_w
        sy = r.height() / self._video_h
        return QRect(int(r.x() + x * sx), int(r.y() + y * sy), int(w * sx), int(h * sy))

    # ---- mouse -------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._drag_start = event.position().toPoint()
        self._drag_cur = self._drag_start

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None:
            self._drag_cur = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None:
            return
        x1, y1 = self._to_video(self._drag_start)
        x2, y2 = self._to_video(event.position().toPoint())
        self._drag_start = self._drag_cur = None
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        if w > 5 and h > 5:
            region = BlurRegion(x=x, y=y, width=w, height=h)
            self._regions.append(region)
            self._selected_id = region.id
            self.region_added.emit(region)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101010"))
        draw_rect = self._draw_rect()
        if self._frame:
            painter.drawPixmap(draw_rect, self._frame)
        else:
            painter.setPen(QPen(QColor("#444")))
            painter.drawRect(draw_rect)
            painter.drawText(draw_rect, Qt.AlignCenter, "Frame preview")

        for region in self._regions:
            screen = self._to_screen(region.x, region.y, region.width, region.height)
            selected = region.id == self._selected_id
            painter.setPen(QPen(QColor("#ff5555" if selected else "#3a7bd5"), 2))
            painter.setBrush(QBrush(QColor(58, 123, 213, 60)))
            painter.drawRect(screen)

        if self._drag_start and self._drag_cur:
            painter.setPen(QPen(QColor("#00ff88"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRect(self._drag_start, self._drag_cur))

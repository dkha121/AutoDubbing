"""Subtitle layout + live-preview canvas.

Shows the video frame, lets the user drag a rectangle that defines where the
Vietnamese subtitle sits, and renders sample text inside it using the current
style (font size, colour, outline, background box, bold). This is a WYSIWYG
preview — the same style dict is handed to FFmpeg at render time.

The subtitle box is stored in video-pixel coordinates so margins map cleanly to
libass MarginV/MarginL/MarginR.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class SubtitlePreviewCanvas(QWidget):
    box_changed = Signal()  # emitted when the user drags a new subtitle box

    SAMPLE_TEXT = "Đây là phụ đề tiếng Việt mẫu"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self._frame: QPixmap | None = None
        self._video_w = 1920
        self._video_h = 1080
        # subtitle box in video px; None = use default bottom band
        self._box: QRect | None = None
        self._drag_start = None
        self._drag_cur = None
        self._action = None       # 'move' | 'resize' | 'new'
        self._press_pt = None
        self._orig_box: QRect | None = None
        # live style
        self._style = {
            "font": "Arial", "font_size": 24, "primary": "#FFFFFF",
            "outline_color": "#000000", "outline": 2, "bold": False,
            "border_style": 1, "back_color": "#000000",
        }

    def set_video_size(self, w: int, h: int) -> None:
        self._video_w = max(1, w)
        self._video_h = max(1, h)
        self.update()

    def set_frame(self, pix: QPixmap | None) -> None:
        self._frame = pix
        self.update()

    def set_style(self, style: dict) -> None:
        self._style.update(style)
        self.update()

    def set_box(self, box: QRect | None) -> None:
        self._box = box
        self.update()

    def box(self) -> QRect | None:
        return self._box

    # ---- coordinate mapping (letterboxed fit) ------------------------
    def _draw_rect(self) -> QRect:
        ww, wh = self.width(), self.height()
        scale = min(ww / self._video_w, wh / self._video_h)
        dw, dh = int(self._video_w * scale), int(self._video_h * scale)
        return QRect((ww - dw) // 2, (wh - dh) // 2, dw, dh)

    def _to_video(self, pt) -> tuple[int, int]:
        r = self._draw_rect()
        sx = self._video_w / max(1, r.width())
        sy = self._video_h / max(1, r.height())
        return int((pt.x() - r.x()) * sx), int((pt.y() - r.y()) * sy)

    def _box_screen(self) -> QRect:
        """Screen rect of the subtitle box (default = bottom 18% band)."""
        r = self._draw_rect()
        if self._box is None:
            h = int(r.height() * 0.18)
            return QRect(r.x() + int(r.width() * 0.06), r.y() + r.height() - h - int(r.height() * 0.04),
                         int(r.width() * 0.88), h)
        sx = r.width() / self._video_w
        sy = r.height() / self._video_h
        return QRect(int(r.x() + self._box.x() * sx), int(r.y() + self._box.y() * sy),
                     int(self._box.width() * sx), int(self._box.height() * sy))

    # ---- mouse: move / resize / draw a subtitle box ------------------
    _HANDLE = 14  # px hit-area for the resize handle (bottom-right corner)

    def _hit_test(self, pt) -> str:
        """Return 'resize' if on the BR handle, 'move' if inside, else 'new'."""
        box = self._box_screen()
        br = box.bottomRight()
        if abs(pt.x() - br.x()) <= self._HANDLE and abs(pt.y() - br.y()) <= self._HANDLE:
            return "resize"
        if box.contains(pt):
            return "move"
        return "new"

    def mousePressEvent(self, event):  # noqa: N802
        pt = event.position().toPoint()
        self._action = self._hit_test(pt)
        self._press_pt = pt
        # ensure we have a concrete box (materialise the default band) to edit
        if self._action in ("move", "resize") and self._box is None:
            scr = self._box_screen()
            x, y = self._to_video(scr.topLeft())
            x2, y2 = self._to_video(scr.bottomRight())
            self._box = QRect(x, y, x2 - x, y2 - y)
        self._orig_box = QRect(self._box) if self._box else None
        self._drag_start = pt
        self._drag_cur = pt

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_start is None:
            return
        pt = event.position().toPoint()
        self._drag_cur = pt
        r = self._draw_rect()
        sx = self._video_w / max(1, r.width())
        sy = self._video_h / max(1, r.height())
        dx = int((pt.x() - self._press_pt.x()) * sx)
        dy = int((pt.y() - self._press_pt.y()) * sy)

        if self._action == "move" and self._orig_box is not None:
            nx = max(0, min(self._video_w - self._orig_box.width(), self._orig_box.x() + dx))
            ny = max(0, min(self._video_h - self._orig_box.height(), self._orig_box.y() + dy))
            self._box = QRect(nx, ny, self._orig_box.width(), self._orig_box.height())
        elif self._action == "resize" and self._orig_box is not None:
            nw = max(40, self._orig_box.width() + dx)
            nh = max(24, self._orig_box.height() + dy)
            self._box = QRect(self._orig_box.x(), self._orig_box.y(), nw, nh)
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_start is None:
            return
        if self._action == "new":
            x1, y1 = self._to_video(self._drag_start)
            x2, y2 = self._to_video(event.position().toPoint())
            x, y, w, h = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
            if w > 20 and h > 20:
                self._box = QRect(x, y, w, h)
        self._drag_start = self._drag_cur = None
        self._action = None
        self.box_changed.emit()
        self.update()

    # ---- paint -------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101010"))
        dr = self._draw_rect()
        if self._frame:
            p.drawPixmap(dr, self._frame)
        else:
            p.setPen(QPen(QColor("#444")))
            p.drawRect(dr)

        box = self._box_screen()
        # dashed outline of subtitle area
        p.setPen(QPen(QColor("#00d0ff"), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box)

        # resize handle (bottom-right corner)
        hs = self._HANDLE
        br = box.bottomRight()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#00d0ff"))
        p.drawRect(br.x() - hs, br.y() - hs, hs, hs)

        self._draw_sample_text(p, box)

        if self._action == "new" and self._drag_start and self._drag_cur:
            p.setPen(QPen(QColor("#00ff88"), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRect(self._drag_start, self._drag_cur))

    def _draw_sample_text(self, p: QPainter, box: QRect) -> None:
        s = self._style
        # scale font: style font_size is in video px -> screen px
        scale = self._draw_rect().height() / self._video_h
        px = max(8, int(s.get("font_size", 24) * scale))
        font = QFont(s.get("font", "Arial"), px)
        font.setBold(bool(s.get("bold", False)))
        font.setPixelSize(px)
        p.setFont(font)

        # background box mode (BorderStyle=3)
        if int(s.get("border_style", 1)) == 3:
            bg = QColor(s.get("back_color", "#000000"))
            bg.setAlpha(200)
            metrics = p.fontMetrics()
            tw = metrics.horizontalAdvance(self.SAMPLE_TEXT)
            th = metrics.height()
            cx = box.center().x()
            bx = QRect(cx - tw // 2 - 8, box.bottom() - th - 12, tw + 16, th + 8)
            p.fillRect(bx, bg)

        # outline by drawing offset copies
        outline = int(s.get("outline", 2))
        oc = QColor(s.get("outline_color", "#000000"))
        flags = Qt.AlignHCenter | Qt.AlignBottom
        if outline > 0:
            p.setPen(oc)
            for dx in (-outline, 0, outline):
                for dy in (-outline, 0, outline):
                    if dx or dy:
                        p.drawText(box.translated(dx, dy), flags, self.SAMPLE_TEXT)
        p.setPen(QColor(s.get("primary", "#FFFFFF")))
        p.drawText(box, flags, self.SAMPLE_TEXT)

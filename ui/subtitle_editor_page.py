"""Subtitle editor page: edit segments, fix timing, wrap lines, import/export."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from core import database as db
from core.logger import get_logger
from services.subtitle_service import SubtitleService
from ui.app_state import AppState
from ui.widgets.subtitle_table_widget import SubtitleTableWidget

logger = get_logger(__name__)


class SubtitleEditorPage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        for label, slot in [
            ("Add", self._add), ("Delete", self._delete),
            ("Merge ↑", self._merge_up), ("Split", self._split),
            ("Fix overlaps", self._fix_overlaps),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)

        toolbar.addWidget(QLabel("Shift (s):"))
        self.shift_spin = QDoubleSpinBox()
        self.shift_spin.setRange(-3600, 3600)
        self.shift_spin.setSingleStep(0.1)
        toolbar.addWidget(self.shift_spin)
        shift_btn = QPushButton("Apply shift")
        shift_btn.clicked.connect(self._shift)
        toolbar.addWidget(shift_btn)

        toolbar.addWidget(QLabel("Max chars/line:"))
        self.max_chars = QSpinBox()
        self.max_chars.setRange(10, 120)
        self.max_chars.setValue(self.state.config.get("subtitle_style.max_chars_per_line", 42))
        toolbar.addWidget(self.max_chars)
        wrap_btn = QPushButton("Wrap long lines")
        wrap_btn.clicked.connect(self._wrap)
        toolbar.addWidget(wrap_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.table = SubtitleTableWidget()
        self.table.segments_changed.connect(self._persist)
        root.addWidget(self.table, 1)

        io_row = QHBoxLayout()
        for label, slot in [
            ("Import SRT", self._import), ("Export SRT", self._export_srt),
            ("Export VTT", self._export_vtt), ("Export JSON", self._export_json),
            ("Save to DB", self._persist),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            io_row.addWidget(btn)
        io_row.addStretch(1)
        root.addLayout(io_row)

        self.state.segments_changed.connect(self._reload)
        self.state.project_changed.connect(lambda _p: self._reload())

    def _reload(self) -> None:
        self.table.set_segments(self.state.segments)

    def _persist(self) -> None:
        if self.state.project:
            db.save_segments(self.state.project.id, self.table.segments())

    # ---- edit ops ----------------------------------------------------
    def _add(self) -> None:
        from models.subtitle_segment import SubtitleSegment
        segs = self.table.segments()
        last_end = segs[-1].end if segs else 0.0
        segs.append(SubtitleSegment(index=len(segs) + 1, start=last_end, end=last_end + 2.0))
        self.table.set_segments(segs)
        self._persist()

    def _delete(self) -> None:
        row = self.table.selected_row()
        segs = self.table.segments()
        if 0 <= row < len(segs):
            del segs[row]
            SubtitleService.reindex(segs)
            self.table.set_segments(segs)
            self._persist()

    def _merge_up(self) -> None:
        row = self.table.selected_row()
        if row > 0:
            segs = SubtitleService.merge(self.table.segments(), row - 1, row)
            self.table.set_segments(segs)
            self._persist()

    def _split(self) -> None:
        row = self.table.selected_row()
        if row >= 0:
            segs = SubtitleService.split(self.table.segments(), row)
            self.table.set_segments(segs)
            self._persist()

    def _fix_overlaps(self) -> None:
        segs = SubtitleService.fix_overlaps(self.table.segments())
        self.table.set_segments(segs)
        self._persist()

    def _shift(self) -> None:
        segs = SubtitleService.shift_timing(self.table.segments(), self.shift_spin.value())
        self.table.set_segments(segs)
        self._persist()

    def _wrap(self) -> None:
        segs = SubtitleService.wrap_long_lines(self.table.segments(), self.max_chars.value())
        self.table.set_segments(segs)
        self._persist()

    # ---- IO ----------------------------------------------------------
    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import subtitle", "",
                                              "Subtitles (*.srt *.vtt *.json)")
        if path:
            segs = SubtitleService.load(path)
            self.state.set_segments(segs)
            self._persist()

    def _export(self, default_name: str, filt: str, saver) -> None:
        if not self.state.project:
            return
        default = str(self.state.project.subdir("subtitles") / default_name)
        path, _ = QFileDialog.getSaveFileName(self, "Export", default, filt)
        if path:
            saver(self.table.segments(), path)
            QMessageBox.information(self, "Export", f"Saved {path}")

    def _export_srt(self) -> None:
        self._export("vi.srt", "SRT (*.srt)",
                     lambda s, p: SubtitleService.save_srt(s, p, True))

    def _export_vtt(self) -> None:
        self._export("vi.vtt", "VTT (*.vtt)",
                     lambda s, p: SubtitleService.save_vtt(s, p, True))

    def _export_json(self) -> None:
        self._export("subtitles.json", "JSON (*.json)", SubtitleService.save_json)

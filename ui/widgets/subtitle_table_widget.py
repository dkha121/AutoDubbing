"""Editable subtitle table widget.

Columns: index, start, end, source_text, vi_text, speaker, voice, status.
Edits to start/end/text/speaker/voice write back into the SubtitleSegment list.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
)

from models.subtitle_segment import SubtitleSegment
from utils.time_utils import seconds_to_srt, srt_to_seconds

_COLUMNS = ["#", "Start", "End", "Source", "Vietnamese", "Speaker", "Voice", "Status"]
_EDITABLE = {1, 2, 3, 4, 5, 6}  # start,end,source,vi,speaker,voice


class SubtitleTableWidget(QTableWidget):
    segment_selected = Signal(int)  # row index
    segments_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._segments: list[SubtitleSegment] = []
        self._loading = False
        self.setColumnCount(len(_COLUMNS))
        self.setHorizontalHeaderLabels(_COLUMNS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        header = self.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.itemChanged.connect(self._on_item_changed)
        self.itemSelectionChanged.connect(self._on_selection)

    def set_segments(self, segments: list[SubtitleSegment]) -> None:
        self._segments = segments
        self._loading = True
        self.setRowCount(len(segments))
        for row, seg in enumerate(segments):
            self._set_row(row, seg)
        self._loading = False

    def segments(self) -> list[SubtitleSegment]:
        return self._segments

    def _set_row(self, row: int, seg: SubtitleSegment) -> None:
        values = [
            str(seg.index), seconds_to_srt(seg.start), seconds_to_srt(seg.end),
            seg.source_text, seg.vi_text, seg.speaker or "", seg.voice or "", seg.status,
        ]
        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            if col not in _EDITABLE:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.setItem(row, col, item)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row, col = item.row(), item.column()
        if row >= len(self._segments):
            return
        seg = self._segments[row]
        text = item.text()
        try:
            if col == 1:
                seg.start = srt_to_seconds(text)
            elif col == 2:
                seg.end = srt_to_seconds(text)
            elif col == 3:
                seg.source_text = text
            elif col == 4:
                seg.vi_text = text
                seg.status = "edited"
            elif col == 5:
                seg.speaker = text or None
            elif col == 6:
                seg.voice = text or None
        except ValueError:
            # Revert invalid timestamp edits.
            self._loading = True
            self._set_row(row, seg)
            self._loading = False
            return
        self.segments_changed.emit()

    def _on_selection(self) -> None:
        rows = self.selectionModel().selectedRows()
        if rows:
            self.segment_selected.emit(rows[0].row())

    def selected_row(self) -> int:
        rows = self.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

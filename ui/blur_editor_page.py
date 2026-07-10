"""Blur & Logo editor page: draw regions over a frame, configure effect, save."""
from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from core import database as db
from core.constants import BlurEffect, BlurRegionType
from core.logger import get_logger
from models.blur_region import BlurRegion
from ui.app_state import AppState
from ui.widgets.blur_region_canvas import BlurRegionCanvas

logger = get_logger(__name__)


class BlurEditorPage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        root = QHBoxLayout(self)

        self.canvas = BlurRegionCanvas()
        self.canvas.region_added.connect(self._on_region_added)
        root.addWidget(self.canvas, 2)

        side = QVBoxLayout()
        side.addWidget(QLabel("<b>Regions</b>"))
        self.region_list = QListWidget()
        self.region_list.currentRowChanged.connect(self._on_select)
        side.addWidget(self.region_list, 1)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value for t in BlurRegionType])
        self.effect_combo = QComboBox()
        self.effect_combo.addItems([e.value for e in BlurEffect])
        self.strength = QSpinBox()
        self.strength.setRange(1, 50)
        self.strength.setValue(10)
        self.start_time = QDoubleSpinBox()
        self.start_time.setRange(0, 100000)
        self.end_time = QDoubleSpinBox()
        self.end_time.setRange(0, 100000)
        for label, w in [("Type", self.type_combo), ("Effect", self.effect_combo),
                         ("Strength", self.strength), ("Start (s)", self.start_time),
                         ("End (s, 0=all)", self.end_time)]:
            side.addWidget(QLabel(label))
            side.addWidget(w)
            w_changed = getattr(w, "currentIndexChanged", None) or getattr(w, "valueChanged")
            w_changed.connect(self._apply_to_selected)

        btn_row = QHBoxLayout()
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete)
        save_btn = QPushButton("Save regions")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(save_btn)
        side.addLayout(btn_row)
        root.addLayout(side, 1)

        self.state.project_changed.connect(lambda _p: self._load())

    def _load(self) -> None:
        if not self.state.project:
            return
        info = self.state.media_info
        if info:
            self.canvas.set_video_size(info.width or 1920, info.height or 1080)
        # try to load a poster frame from the original video's first frame
        regions = db.load_blur_regions(self.state.project.id)
        self.state.blur_regions = regions
        self.canvas.set_regions(regions)
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.region_list.clear()
        for r in self.canvas.regions():
            self.region_list.addItem(f"{r.type} [{r.effect}] {r.width}x{r.height}")

    def _on_region_added(self, region: BlurRegion) -> None:
        self._refresh_list()
        self.region_list.setCurrentRow(len(self.canvas.regions()) - 1)

    def _selected_region(self) -> BlurRegion | None:
        row = self.region_list.currentRow()
        regions = self.canvas.regions()
        return regions[row] if 0 <= row < len(regions) else None

    def _on_select(self, row: int) -> None:
        r = self._selected_region()
        if not r:
            return
        self.type_combo.setCurrentText(r.type)
        self.effect_combo.setCurrentText(r.effect)
        self.strength.setValue(r.strength)
        self.start_time.setValue(r.start_time)
        self.end_time.setValue(r.end_time)

    def _apply_to_selected(self) -> None:
        r = self._selected_region()
        if not r:
            return
        r.type = self.type_combo.currentText()
        r.effect = self.effect_combo.currentText()
        r.strength = self.strength.value()
        r.start_time = self.start_time.value()
        r.end_time = self.end_time.value()
        self._refresh_list()
        self.canvas.update()

    def _delete(self) -> None:
        row = self.region_list.currentRow()
        regions = self.canvas.regions()
        if 0 <= row < len(regions):
            del regions[row]
            self.canvas.set_regions(regions)
            self._refresh_list()

    def _save(self) -> None:
        if not self.state.project:
            return
        self.state.blur_regions = self.canvas.regions()
        db.save_blur_regions(self.state.project.id, self.state.blur_regions)
        QMessageBox.information(self, "Blur", f"Saved {len(self.state.blur_regions)} region(s).")

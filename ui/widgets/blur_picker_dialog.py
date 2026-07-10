"""Preview dialog: blur regions + subtitle layout & styling.

Two tabs over the same video frame:
  - "Làm mờ"  : drag rectangles to blur (subtitles/logos/watermarks)
  - "Phụ đề"  : drag the subtitle area + tune font/size/colour/outline/box,
                pick a style preset, and see a live WYSIWYG preview.

Returns (blur_regions, subtitle_style_dict, subtitle_box) on accept.
"""
from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QCheckBox, QHBoxLayout,
    QLabel, QListWidget, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from core.constants import BlurEffect
from models.blur_region import BlurRegion
from ui.widgets.blur_region_canvas import BlurRegionCanvas
from ui.widgets.subtitle_preview_canvas import SubtitlePreviewCanvas
from utils import subtitle_style_utils as ssu


class BlurPickerDialog(QDialog):
    def __init__(self, frame_path: str | None, video_w: int, video_h: int,
                 regions: list[BlurRegion] | None = None,
                 sub_style: dict | None = None, sub_box: QRect | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vùng làm mờ & Phụ đề")
        self.resize(1040, 660)
        self._video_w, self._video_h = video_w, video_h

        pix = QPixmap(frame_path) if frame_path else None
        if pix is not None and pix.isNull():
            pix = None

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_blur_tab(pix, video_w, video_h, regions), "Làm mờ")
        tabs.addTab(self._build_subtitle_tab(pix, video_w, video_h, sub_style, sub_box), "Phụ đề")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ===== Blur tab =================================================
    def _build_blur_tab(self, pix, vw, vh, regions) -> QWidget:
        w = QWidget()
        body = QHBoxLayout(w)
        self.canvas = BlurRegionCanvas()
        self.canvas.set_video_size(vw, vh)
        if pix:
            self.canvas.set_frame(pix)
        if regions:
            self.canvas.set_regions(list(regions))
        self.canvas.region_added.connect(lambda _r: self._refresh_regions())
        body.addWidget(self.canvas, 3)

        side = QVBoxLayout()
        side.addWidget(QLabel("<b>Vùng làm mờ</b> — kéo chuột để tạo"))
        self.region_list = QListWidget()
        self.region_list.currentRowChanged.connect(self._on_region_select)
        side.addWidget(self.region_list, 1)
        self.effect_combo = QComboBox()
        self.effect_combo.addItems([e.value for e in BlurEffect])
        self.effect_combo.currentIndexChanged.connect(self._apply_effect)
        side.addWidget(QLabel("Hiệu ứng"))
        side.addWidget(self.effect_combo)
        del_btn = QPushButton("Xóa vùng")
        del_btn.clicked.connect(self._delete_region)
        side.addWidget(del_btn)
        side.addStretch(1)
        body.addLayout(side, 1)
        self._refresh_regions()
        return w

    def _refresh_regions(self) -> None:
        self.region_list.clear()
        for r in self.canvas.regions():
            self.region_list.addItem(f"{r.type} [{r.effect}] {r.width}x{r.height}")

    def _sel_region(self):
        row = self.region_list.currentRow()
        rs = self.canvas.regions()
        return rs[row] if 0 <= row < len(rs) else None

    def _on_region_select(self, _row):
        r = self._sel_region()
        if r:
            self.effect_combo.setCurrentText(r.effect)

    def _apply_effect(self):
        r = self._sel_region()
        if r:
            r.effect = self.effect_combo.currentText()
            self._refresh_regions()

    def _delete_region(self):
        row = self.region_list.currentRow()
        rs = self.canvas.regions()
        if 0 <= row < len(rs):
            del rs[row]
            self.canvas.set_regions(rs)
            self._refresh_regions()

    # ===== Subtitle tab ============================================
    def _build_subtitle_tab(self, pix, vw, vh, sub_style, sub_box) -> QWidget:
        w = QWidget()
        body = QHBoxLayout(w)
        self.sub_canvas = SubtitlePreviewCanvas()
        self.sub_canvas.set_video_size(vw, vh)
        if pix:
            self.sub_canvas.set_frame(pix)
        if sub_box:
            self.sub_canvas.set_box(sub_box)
        body.addWidget(self.sub_canvas, 3)

        side = QVBoxLayout()
        side.addWidget(QLabel("<b>Phụ đề</b> — kéo chuột để chọn vùng đặt chữ"))

        side.addWidget(QLabel("Kiểu có sẵn"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(ssu.STYLE_PRESETS.keys())
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        side.addWidget(self.preset_combo)

        side.addWidget(QLabel("Font"))
        self.font_combo = QComboBox()
        self.font_combo.addItems(ssu.COMMON_FONTS)
        self.font_combo.currentTextChanged.connect(self._update_style)
        side.addWidget(self.font_combo)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Cỡ chữ"))
        self.size_spin = QSpinBox(); self.size_spin.setRange(10, 120); self.size_spin.setValue(28)
        self.size_spin.valueChanged.connect(self._update_style)
        row1.addWidget(self.size_spin)
        self.bold_check = QCheckBox("Đậm")
        self.bold_check.toggled.connect(self._update_style)
        row1.addWidget(self.bold_check)
        side.addLayout(row1)

        # colour pickers
        self._primary = "#FFFFFF"
        self._outline_c = "#000000"
        self.primary_btn = QPushButton("Màu chữ")
        self.primary_btn.clicked.connect(lambda: self._pick_color("primary"))
        self.outline_btn = QPushButton("Màu viền")
        self.outline_btn.clicked.connect(lambda: self._pick_color("outline"))
        crow = QHBoxLayout(); crow.addWidget(self.primary_btn); crow.addWidget(self.outline_btn)
        side.addLayout(crow)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Độ viền"))
        self.outline_spin = QSpinBox(); self.outline_spin.setRange(0, 8); self.outline_spin.setValue(2)
        self.outline_spin.valueChanged.connect(self._update_style)
        row2.addWidget(self.outline_spin)
        self.box_check = QCheckBox("Nền hộp")
        self.box_check.toggled.connect(self._update_style)
        row2.addWidget(self.box_check)
        side.addLayout(row2)

        side.addWidget(QLabel("Vị trí"))
        self.align_combo = QComboBox()
        self.align_combo.addItems(ssu.ALIGNMENTS.keys())
        self.align_combo.currentTextChanged.connect(self._update_style)
        side.addWidget(self.align_combo)

        side.addStretch(1)
        body.addLayout(side, 1)

        # init from incoming style or first preset
        if sub_style:
            self._load_existing_style(sub_style)
        else:
            self._apply_preset(self.preset_combo.currentText())
        return w

    def _swatch(self, btn, color: str) -> None:
        btn.setStyleSheet(f"background-color:{color}; color:{'#000' if color.upper()=='#FFFFFF' else '#fff'};")

    def _pick_color(self, which: str) -> None:
        start = self._primary if which == "primary" else self._outline_c
        c = QColorDialog.getColor(QColor(start), self, "Chọn màu")
        if c.isValid():
            if which == "primary":
                self._primary = c.name(); self._swatch(self.primary_btn, self._primary)
            else:
                self._outline_c = c.name(); self._swatch(self.outline_btn, self._outline_c)
            self._update_style()

    def _apply_preset(self, name: str) -> None:
        p = ssu.STYLE_PRESETS.get(name)
        if not p:
            return
        self._primary = p["primary"]; self._outline_c = p["outline_color"]
        self._swatch(self.primary_btn, self._primary)
        self._swatch(self.outline_btn, self._outline_c)
        self.outline_spin.setValue(p["outline"])
        self.box_check.setChecked(p["border_style"] == 3)
        self._update_style()

    def _load_existing_style(self, style: dict) -> None:
        self.font_combo.setCurrentText(style.get("font", "Arial"))
        self.size_spin.setValue(int(style.get("font_size", 28)))
        self.bold_check.setChecked(bool(style.get("bold", 0)))
        self._primary = ssu.ass_to_rgb(style.get("primary_color", "&H00FFFFFF"))
        self._outline_c = ssu.ass_to_rgb(style.get("outline_color", "&H00000000"))
        self._swatch(self.primary_btn, self._primary)
        self._swatch(self.outline_btn, self._outline_c)
        self.outline_spin.setValue(int(style.get("outline", 2)))
        self.box_check.setChecked(int(style.get("border_style", 1)) == 3)
        self._update_style()

    def _update_style(self) -> None:
        # live preview uses plain hex; final dict uses ASS via build_style
        self.sub_canvas.set_style({
            "font": self.font_combo.currentText(),
            "font_size": self.size_spin.value(),
            "primary": self._primary,
            "outline_color": self._outline_c,
            "outline": self.outline_spin.value(),
            "bold": self.bold_check.isChecked(),
            "border_style": 3 if self.box_check.isChecked() else 1,
            "back_color": "#000000",
        })

    # ===== results =================================================
    def regions(self) -> list[BlurRegion]:
        return self.canvas.regions()

    def subtitle_style(self) -> dict:
        align = ssu.ALIGNMENTS.get(self.align_combo.currentText(), 2)
        box = self.sub_canvas.box()
        margin_v = 30
        margin_l = margin_r = 20
        if box is not None:
            # bottom margin = distance from box bottom to frame bottom
            margin_v = max(0, self._video_h - (box.y() + box.height()))
            margin_l = max(0, box.x())
            margin_r = max(0, self._video_w - (box.x() + box.width()))
        return ssu.build_style(
            font=self.font_combo.currentText(),
            font_size=self.size_spin.value(),
            primary=self._primary,
            outline_color=self._outline_c,
            outline=self.outline_spin.value(),
            shadow=0 if self.box_check.isChecked() else 1,
            border_style=3 if self.box_check.isChecked() else 1,
            alignment=align, margin_v=margin_v, margin_l=margin_l, margin_r=margin_r,
            bold=self.bold_check.isChecked(),
        )

    def subtitle_box(self) -> QRect | None:
        return self.sub_canvas.box()

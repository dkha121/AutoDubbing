"""Render page: configure preset, preview 10s, render final video."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from core import database as db
from core.constants import CPU_ENCODERS, GPU_ENCODERS, OUTPUT_FORMATS, RENDER_PRESETS
from core.logger import get_logger
from core.worker import Worker
from models.render_preset import RenderPreset
from services.render_service import RenderService
from ui.app_state import AppState
from utils import srt_utils

logger = get_logger(__name__)


class RenderPage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._worker: Worker | None = None

        root = QVBoxLayout(self)
        opts = QGroupBox("Render settings")
        form = QFormLayout(opts)

        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems(RENDER_PRESETS.keys())
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItems(list(CPU_ENCODERS) + list(GPU_ENCODERS))
        self.encoder_combo.setCurrentText(self.state.config.get("render.default_encoder", "libx264"))
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["original", "24", "30", "60"])
        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(self.state.config.get("render.default_crf", 20))
        self.bitrate = QLineEdit()
        self.bitrate.setPlaceholderText("e.g. 6M (optional)")
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(OUTPUT_FORMATS)
        self.burn_check = QCheckBox("Burn Vietnamese subtitle")
        self.burn_check.setChecked(True)
        self.dub_check = QCheckBox("Use generated dubbing audio (tts/dub.wav)")

        form.addRow("Resolution", self.aspect_combo)
        form.addRow("Encoder", self.encoder_combo)
        form.addRow("FPS", self.fps_combo)
        form.addRow("CRF/CQ", self.crf)
        form.addRow("Bitrate", self.bitrate)
        form.addRow("Format", self.fmt_combo)
        form.addRow("", self.burn_check)
        form.addRow("", self.dub_check)
        root.addWidget(opts)

        btn_row = QHBoxLayout()
        self.preview_btn = QPushButton("Render 10s Preview")
        self.preview_btn.clicked.connect(lambda: self._render(preview=True))
        self.render_btn = QPushButton("Render Final")
        self.render_btn.clicked.connect(lambda: self._render(preview=False))
        btn_row.addWidget(self.preview_btn)
        btn_row.addWidget(self.render_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.progress = QProgressBar()
        root.addWidget(self.progress)
        self.status = QLabel("Idle")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

    def _build_preset(self) -> RenderPreset:
        size = RENDER_PRESETS[self.aspect_combo.currentText()]
        fps_text = self.fps_combo.currentText()
        return RenderPreset(
            name=self.aspect_combo.currentText(),
            width=size[0] if size else None,
            height=size[1] if size else None,
            fps=None if fps_text == "original" else int(fps_text),
            encoder=self.encoder_combo.currentText(),
            crf=self.crf.value(),
            preset=self.state.config.get("render.default_preset", "medium"),
            bitrate=self.bitrate.text().strip() or None,
            audio_codec=self.state.config.get("render.default_audio_codec", "aac"),
            output_format=self.fmt_combo.currentText(),
            burn_subtitle=self.burn_check.isChecked(),
        )

    def _render(self, preview: bool) -> None:
        project = self.state.require_project()
        if not project:
            QMessageBox.information(self, "Render", "Import a video first.")
            return
        preset = self._build_preset()
        segments = self.state.segments
        duration = self.state.media_info.duration if self.state.media_info else 0.0

        vi_srt = None
        if preset.burn_subtitle and segments:
            vi_srt = str(project.subdir("subtitles") / "vi.srt")
            srt_utils.save_srt(segments, vi_srt, use_vietnamese=True)

        audio_path = None
        if self.dub_check.isChecked():
            cand = project.subdir("tts") / "dub.wav"
            if cand.exists():
                audio_path = str(cand)
            else:
                QMessageBox.warning(self, "Render", "No dubbing audio found; rendering original audio.")

        blur_regions = db.load_blur_regions(project.id) or None
        suffix = "preview" if preview else "final"
        out_path = str(project.subdir("render") / f"{project.id}_{suffix}.{preset.output_format}")

        def task(ctx):
            svc = RenderService(self.state.config)
            kwargs = dict(video_path=project.source_video, output_path=out_path, preset=preset,
                          srt_path=vi_srt, blur_regions=blur_regions, audio_path=audio_path,
                          total_duration=duration,
                          progress_cb=lambda p, m: ctx.progress(p, m))
            if preview:
                return svc.render_preview(seconds=10, **kwargs)
            return svc.render(**kwargs)

        self._set_running(True)
        self._worker = Worker(task)
        self._worker.signals.progress.connect(lambda p, m: (self.progress.setValue(int(p)), self.status.setText(m)))
        self._worker.signals.finished.connect(self._on_done)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, out_path: str) -> None:
        self.status.setText(f"Rendered: {out_path}")
        self._set_running(False)
        QMessageBox.information(self, "Render", f"Done:\n{out_path}")

    def _on_failed(self, err: str) -> None:
        QMessageBox.critical(self, "Render failed", err.split("\n")[0])
        self.status.setText(f"Failed: {err.split(chr(10))[0]}")
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.preview_btn.setEnabled(not running)
        self.render_btn.setEnabled(not running)

"""Transcribe page: extract audio + run faster-whisper, produce SRT."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from core import database as db
from core.constants import ASR_MODELS
from core.logger import get_logger
from core.worker import Worker
from services.asr_service import ASRService
from services.ffmpeg_service import FFmpegService
from ui.app_state import AppState
from utils import srt_utils

logger = get_logger(__name__)


class TranscribePage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._worker: Worker | None = None

        root = QVBoxLayout(self)

        opts = QGroupBox("ASR settings")
        form = QFormLayout(opts)
        self.model_combo = QComboBox()
        self.model_combo.addItems(ASR_MODELS)
        self.model_combo.setCurrentText(self.state.config.get("asr.default_model", "small"))
        self.device_combo = QComboBox()
        self.device_combo.addItems(["auto", "cuda", "cpu"])
        self.device_combo.setCurrentText(self.state.config.get("asr.device", "auto"))
        self.compute_combo = QComboBox()
        self.compute_combo.addItems(["auto", "float16", "int8_float16", "int8"])
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["auto", "en", "zh", "ja", "ko", "vi", "fr", "es", "de"])
        form.addRow("Model", self.model_combo)
        form.addRow("Device", self.device_combo)
        form.addRow("Compute type", self.compute_combo)
        form.addRow("Language", self.lang_combo)
        root.addWidget(opts)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Extract + Transcribe")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.progress = QProgressBar()
        root.addWidget(self.progress)
        self.status = QLabel("Idle")
        root.addWidget(self.status)
        root.addStretch(1)

    def _start(self) -> None:
        project = self.state.require_project()
        if not project:
            QMessageBox.information(self, "Transcribe", "Import a video first.")
            return
        ff = FFmpegService(self.state.config)
        if not ff.check_ffmpeg_available():
            QMessageBox.critical(self, "FFmpeg missing",
                                 "FFmpeg not found. Set its path in Settings.")
            return

        model = self.model_combo.currentText()
        device = self.device_combo.currentText()
        compute = self.compute_combo.currentText()
        language = self.lang_combo.currentText()
        duration = self.state.media_info.duration if self.state.media_info else 0.0

        def task(ctx):
            audio = str(project.subdir("audio") / "source.wav")
            ctx.progress(2, "Extracting audio")
            FFmpegService(self.state.config).extract_audio(
                project.source_video, audio, duration,
                lambda p, m: ctx.progress(2 + p * 0.18, m),
            )
            ctx.raise_if_cancelled()
            ctx.progress(20, "Loading model")
            asr = ASRService(self.state.config)
            asr.load_model(model, device, compute)
            segments, detected = asr.transcribe(
                audio, language, lambda p, m: ctx.progress(20 + p * 0.78, m)
            )
            srt_path = str(project.subdir("subtitles") / "source.srt")
            srt_utils.save_srt(segments, srt_path, use_vietnamese=False)
            db.save_segments(project.id, segments)
            return segments, detected, srt_path

        self._set_running(True)
        self._worker = Worker(task)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_done)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.status.setText("Cancelling…")

    def _on_progress(self, pct: float, msg: str) -> None:
        self.progress.setValue(int(pct))
        if msg:
            self.status.setText(msg)

    def _on_done(self, result) -> None:
        segments, detected, srt_path = result
        self.state.set_segments(segments)
        self.status.setText(f"Done: {len(segments)} segments (lang={detected}) -> {srt_path}")
        self._set_running(False)

    def _on_failed(self, err: str) -> None:
        first = err.split("\n")[0]
        self.status.setText(f"Failed: {first}")
        if "cuda" in err.lower() or "Whisper model" in err:
            if QMessageBox.question(
                self, "CUDA error",
                f"{first}\n\nRetry on CPU?",
            ) == QMessageBox.Yes:
                self.device_combo.setCurrentText("cpu")
                self.compute_combo.setCurrentText("int8")
                self._set_running(False)
                self._start()
                return
        else:
            QMessageBox.critical(self, "Transcribe failed", first)
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)

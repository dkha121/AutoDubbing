"""Translation page: translate segments to Vietnamese via selected engine."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from core import database as db
from core.constants import TRANSLATION_ENGINES, TRANSLATION_STYLES
from core.logger import get_logger
from core.worker import Worker
from services.subtitle_service import SubtitleService
from services.translation_service import get_provider
from ui.app_state import AppState

logger = get_logger(__name__)


class TranslationPage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._worker: Worker | None = None

        root = QVBoxLayout(self)
        opts = QGroupBox("Translation settings")
        form = QFormLayout(opts)
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(TRANSLATION_ENGINES)
        self.engine_combo.setCurrentText(self.state.config.get("translation.default_engine", "local"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(TRANSLATION_STYLES)
        self.style_combo.setCurrentText(self.state.config.get("translation.default_style", "Natural Vietnamese"))
        form.addRow("Engine", self.engine_combo)
        form.addRow("Style", self.style_combo)
        root.addWidget(opts)

        btn_row = QHBoxLayout()
        self.test_btn = QPushButton("Test connection")
        self.test_btn.clicked.connect(self._test)
        self.cost_btn = QPushButton("Estimate cost")
        self.cost_btn.clicked.connect(self._estimate)
        self.translate_btn = QPushButton("Translate")
        self.translate_btn.clicked.connect(lambda: self._run("translate"))
        self.improve_btn = QPushButton("Improve Vietnamese")
        self.improve_btn.clicked.connect(lambda: self._run("improve"))
        self.shorten_btn = QPushButton("Shorten Subtitle")
        self.shorten_btn.clicked.connect(lambda: self._run("shorten"))
        self.dub_btn = QPushButton("Make Dubbing Script")
        self.dub_btn.clicked.connect(lambda: self._run("dubbing"))
        for b in (self.test_btn, self.cost_btn, self.translate_btn,
                  self.improve_btn, self.shorten_btn, self.dub_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.progress = QProgressBar()
        root.addWidget(self.progress)
        self.status = QLabel("Idle")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

    def _provider(self):
        return get_provider(self.engine_combo.currentText(), self.state.config)

    def _test(self) -> None:
        ok, msg = self._provider().test_connection()
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Test connection", msg)

    def _estimate(self) -> None:
        if not self.state.segments:
            QMessageBox.information(self, "Cost", "No segments to translate.")
            return
        self.status.setText(self._provider().estimate_cost(self.state.segments))

    def _run(self, mode: str) -> None:
        if not self.state.segments:
            QMessageBox.information(self, "Translate", "Transcribe or import subtitles first.")
            return
        style = self.style_combo.currentText()
        if mode == "shorten":
            style = "Dubbing Script"
        elif mode == "dubbing":
            style = "Dubbing Script"
        provider = self._provider()
        segments = self.state.segments

        def task(ctx):
            result = provider.translate_segments(
                segments, self.state.project.source_language or "auto", "vi", style,
                progress_cb=lambda p, m: ctx.progress(p, m),
            )
            SubtitleService.fix_overlaps(result)
            if self.state.project:
                db.save_segments(self.state.project.id, result)
            return result

        self._set_running(True)
        self._worker = Worker(task)
        self._worker.signals.progress.connect(lambda p, m: (self.progress.setValue(int(p)), self.status.setText(m)))
        self._worker.signals.finished.connect(self._on_done)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, segments) -> None:
        self.state.set_segments(segments)
        self.status.setText(f"Translated {len(segments)} segments.")
        self._set_running(False)

    def _on_failed(self, err: str) -> None:
        QMessageBox.critical(self, "Translation failed", err.split("\n")[0])
        self.status.setText(f"Failed: {err.split(chr(10))[0]}")
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        for b in (self.translate_btn, self.improve_btn, self.shorten_btn, self.dub_btn):
            b.setEnabled(not running)

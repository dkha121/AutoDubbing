"""TTS / Dubbing page: generate per-segment audio and assemble timeline."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from core.constants import TTS_ENGINES
from core.logger import get_logger
from core.worker import Worker
from services.tts_service import TTSAssembler, get_tts_provider
from ui.app_state import AppState

logger = get_logger(__name__)


class TTSPage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._worker: Worker | None = None

        root = QVBoxLayout(self)
        opts = QGroupBox("TTS settings")
        form = QFormLayout(opts)
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(TTS_ENGINES)
        self.engine_combo.setCurrentText(self.state.config.get("tts.default_engine", "edge"))
        self.voice_male = QLineEdit(self.state.config.get("tts.default_voice_male", ""))
        self.voice_female = QLineEdit(self.state.config.get("tts.default_voice_female", ""))
        male_row = self._with_browse(self.voice_male)
        female_row = self._with_browse(self.voice_female)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.05)
        self.speed.setValue(self.state.config.get("tts.default_speed", 1.0))
        form.addRow("Engine", self.engine_combo)
        form.addRow("Male voice (Speaker 1)", male_row)
        form.addRow("Female voice (Speaker 2)", female_row)
        form.addRow("Speed", self.speed)
        root.addWidget(opts)

        btn_row = QHBoxLayout()
        self.gen_btn = QPushButton("Generate Dubbing")
        self.gen_btn.clicked.connect(self._generate)
        btn_row.addWidget(self.gen_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.progress = QProgressBar()
        root.addWidget(self.progress)
        self.status = QLabel("Idle")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

    def _with_browse(self, line: QLineEdit) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(line, 1)
        btn = QPushButton("…")
        btn.setMaximumWidth(32)
        btn.clicked.connect(lambda: self._pick_voice(line))
        lay.addWidget(btn)
        return w

    def _pick_voice(self, line: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select voice model", "",
                                              "Models (*.onnx *.pth *.wav);;All (*.*)")
        if path:
            line.setText(path)

    def _generate(self) -> None:
        project = self.state.require_project()
        if not project or not self.state.segments:
            QMessageBox.information(self, "TTS", "Need a project with subtitles first.")
            return
        provider = get_tts_provider(self.engine_combo.currentText(), self.state.config)
        ok, msg = provider.is_available()
        if not ok:
            QMessageBox.warning(self, "TTS engine", msg)
            return

        voice_map = {
            "Speaker 1": self.voice_male.text(),
            "Speaker 2": self.voice_female.text(),
            "": self.voice_male.text(),
        }
        speed = self.speed.value()
        segments = self.state.segments
        duration = self.state.media_info.duration if self.state.media_info else 0.0

        def task(ctx):
            clip_dir = str(project.subdir("tts"))
            clips = provider.synthesize_segments(
                segments, voice_map, clip_dir, speed,
                lambda p, m: ctx.progress(p * 0.8, m),
            )
            ctx.progress(82, "Assembling timeline")
            out_wav = str(project.subdir("tts") / "dub.wav")
            TTSAssembler(self.state.config).assemble(segments, clips, out_wav, duration)
            ctx.progress(100, "Done")
            return out_wav

        self.gen_btn.setEnabled(False)
        self._worker = Worker(task)
        self._worker.signals.progress.connect(lambda p, m: (self.progress.setValue(int(p)), self.status.setText(m)))
        self._worker.signals.finished.connect(self._on_done)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, out_wav: str) -> None:
        self.status.setText(f"Dubbing audio: {out_wav}")
        self.gen_btn.setEnabled(True)

    def _on_failed(self, err: str) -> None:
        QMessageBox.critical(self, "TTS failed", err.split("\n")[0])
        self.gen_btn.setEnabled(True)

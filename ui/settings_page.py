"""Settings page: edit and persist application configuration to config.json."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from core.app_config import AppConfig
from core.constants import ASR_MODELS, TRANSLATION_ENGINES, TTS_ENGINES
from core.logger import get_logger
from services.ffmpeg_service import FFmpegService

logger = get_logger(__name__)


class SettingsPage(QWidget):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        scroll.setWidget(container)
        outer.addWidget(scroll)
        root = QVBoxLayout(container)

        # ---- paths ----
        paths = QGroupBox("Paths")
        pform = QFormLayout(paths)
        self.ffmpeg_path = self._path_field(pform, "FFmpeg path", config.ffmpeg_path())
        self.ffprobe_path = self._path_field(pform, "FFprobe path", config.ffprobe_path())
        self.output_folder = self._path_field(pform, "Output folder",
                                               config.get("default_output_folder", "./data/outputs"), dir_mode=True)
        check_btn = QPushButton("Check FFmpeg/FFprobe")
        check_btn.clicked.connect(self._check_ffmpeg)
        pform.addRow("", check_btn)
        root.addWidget(paths)

        # ---- ASR ----
        asr = QGroupBox("ASR")
        aform = QFormLayout(asr)
        self.asr_model = QComboBox(); self.asr_model.addItems(ASR_MODELS)
        self.asr_model.setCurrentText(config.get("asr.default_model", "small"))
        self.asr_device = QComboBox(); self.asr_device.addItems(["auto", "cuda", "cpu"])
        self.asr_device.setCurrentText(config.get("asr.device", "auto"))
        aform.addRow("Default model", self.asr_model)
        aform.addRow("Device", self.asr_device)
        root.addWidget(asr)

        # ---- translation / API keys ----
        tr = QGroupBox("Translation & API keys")
        tform = QFormLayout(tr)
        self.tr_engine = QComboBox(); self.tr_engine.addItems(TRANSLATION_ENGINES)
        self.tr_engine.setCurrentText(config.get("translation.default_engine", "local"))
        self.openai_key = QLineEdit(config.get("api_keys.openai_api_key", ""))
        self.openai_key.setEchoMode(QLineEdit.Password)
        self.gemini_key = QLineEdit(config.get("api_keys.gemini_api_key", ""))
        self.gemini_key.setEchoMode(QLineEdit.Password)
        tform.addRow("Default engine", self.tr_engine)
        tform.addRow("OpenAI API key", self.openai_key)
        tform.addRow("Gemini API key", self.gemini_key)
        tform.addRow("", QLabel("Keys are stored in config.json (gitignored) "
                                "or read from env OPENAI_API_KEY / GEMINI_API_KEY."))
        root.addWidget(tr)

        # ---- router (OpenAI-compatible proxy, e.g. 9router) ----
        rt = QGroupBox("Router (OpenAI-compatible LLM, e.g. 9router)")
        rtform = QFormLayout(rt)
        self.router_base = QLineEdit(config.get("router.base_url", ""))
        self.router_base.setPlaceholderText("https://9router.huygia.site/v1")
        self.router_token = QLineEdit(config.get("router.token", ""))
        self.router_token.setEchoMode(QLineEdit.Password)
        self.router_model = QLineEdit(config.get("router.model", "ag/gemini-3.1-pro-low"))
        rtform.addRow("Base URL", self.router_base)
        rtform.addRow("Token", self.router_token)
        rtform.addRow("Model", self.router_model)
        rt_test = QPushButton("Test router connection")
        rt_test.clicked.connect(self._test_router)
        rtform.addRow("", rt_test)
        rtform.addRow("", QLabel("Engine 'router' dùng endpoint này để dịch. "
                                 "Model gợi ý: ag/gemini-3.1-pro-low, ag/gemini-3-flash."))
        root.addWidget(rt)

        # ---- TTS ----
        tts = QGroupBox("TTS")
        ttsform = QFormLayout(tts)
        self.tts_engine = QComboBox(); self.tts_engine.addItems(TTS_ENGINES)
        self.tts_engine.setCurrentText(config.get("tts.default_engine", "edge"))
        ttsform.addRow("Default engine", self.tts_engine)
        root.addWidget(tts)

        # ---- render ----
        rnd = QGroupBox("Render")
        rform = QFormLayout(rnd)
        self.enable_cuda = QCheckBox(); self.enable_cuda.setChecked(config.get("render.enable_cuda", False))
        self.max_jobs = QSpinBox(); self.max_jobs.setRange(1, 8)
        self.max_jobs.setValue(config.get("batch.max_concurrent_jobs", 1))
        self.theme = QComboBox(); self.theme.addItems(["dark", "light"])
        self.theme.setCurrentText(config.get("ui.theme", "dark"))
        rform.addRow("Enable CUDA", self.enable_cuda)
        rform.addRow("Max concurrent jobs", self.max_jobs)
        rform.addRow("Theme", self.theme)
        root.addWidget(rnd)

        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self._save)
        root.addWidget(save_btn)
        root.addStretch(1)

    def _path_field(self, form: QFormLayout, label: str, value: str, dir_mode: bool = False) -> QLineEdit:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit(value)
        lay.addWidget(line, 1)
        btn = QPushButton("…")
        btn.setMaximumWidth(32)
        btn.clicked.connect(lambda: self._browse(line, dir_mode))
        lay.addWidget(btn)
        form.addRow(label, w)
        return line

    def _browse(self, line: QLineEdit, dir_mode: bool) -> None:
        if dir_mode:
            path = QFileDialog.getExistingDirectory(self, "Select folder")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Select binary")
        if path:
            line.setText(path)

    def _check_ffmpeg(self) -> None:
        self.config.set("ffmpeg_path", self.ffmpeg_path.text())
        self.config.set("ffprobe_path", self.ffprobe_path.text())
        ff = FFmpegService(self.config)
        ok = ff.check_ffmpeg_available()
        ok2 = ff.check_ffprobe_available()
        msg = f"FFmpeg: {'OK' if ok else 'NOT FOUND'}\nFFprobe: {'OK' if ok2 else 'NOT FOUND'}"
        if not (ok and ok2):
            msg += ("\n\nInstall FFmpeg and set the full path here, e.g.\n"
                    "C:\\ffmpeg\\bin\\ffmpeg.exe")
        (QMessageBox.information if ok and ok2 else QMessageBox.warning)(self, "FFmpeg check", msg)

    def _test_router(self) -> None:
        # Persist current router fields first so the provider reads them.
        self.config.set("router.base_url", self.router_base.text().strip())
        self.config.set("router.token", self.router_token.text().strip())
        self.config.set("router.model", self.router_model.text().strip())
        from services.router_translation_provider import RouterTranslationProvider
        ok, msg = RouterTranslationProvider(self.config).test_connection()
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Router", msg)

    def _save(self) -> None:
        self.config.set("ffmpeg_path", self.ffmpeg_path.text())
        self.config.set("ffprobe_path", self.ffprobe_path.text())
        self.config.set("default_output_folder", self.output_folder.text())
        self.config.set("asr.default_model", self.asr_model.currentText())
        self.config.set("asr.device", self.asr_device.currentText())
        self.config.set("translation.default_engine", self.tr_engine.currentText())
        self.config.set("api_keys.openai_api_key", self.openai_key.text())
        self.config.set("api_keys.gemini_api_key", self.gemini_key.text())
        self.config.set("router.base_url", self.router_base.text().strip())
        self.config.set("router.token", self.router_token.text().strip())
        self.config.set("router.model", self.router_model.text().strip())
        self.config.set("tts.default_engine", self.tts_engine.currentText())
        self.config.set("render.enable_cuda", self.enable_cuda.isChecked())
        self.config.set("batch.max_concurrent_jobs", self.max_jobs.value())
        self.config.set("ui.theme", self.theme.currentText())
        self.config.save()
        QMessageBox.information(self, "Settings", "Saved to config.json")

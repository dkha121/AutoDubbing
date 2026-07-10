"""Auto Dubbing page — the all-in-one screen.

Drop or browse a video, pick a few options, press START, and the app runs the
whole pipeline (transcribe -> translate -> Vietnamese voice -> burn subtitle ->
render) and produces a finished dubbed video. This is the default landing page.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget, QGridLayout,
)
from ui.widgets.video_preview_widget import VideoPreviewWidget

from core import database as db
from core.constants import (
    ASR_MODELS, EDGE_VI_VOICES, RENDER_PRESETS, TRANSLATION_ENGINES,
    TRANSLATION_STYLES, TTS_ENGINES,
)
from core.logger import get_logger
from core.worker import Worker
from models.project import Project
from models.render_preset import RenderPreset
from models.video_job import VideoJob
from services.auto_dubbing_service import AutoDubbingOptions, AutoDubbingService
from services.ffmpeg_service import FFmpegService
from services.media_info_service import MediaInfoService
from ui.app_state import AppState
from utils.path_utils import safe_filename
from utils.time_utils import format_duration
from utils.validation_utils import is_supported_video

logger = get_logger(__name__)

_KEEP_ORIGINAL = {
    "Mute original (pure dub)": 0.0,
    "Keep original at 10%": 0.10,
    "Keep original at 20%": 0.20,
    "Keep original at 30%": 0.30,
}


class AutoDubbingPage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._worker: Worker | None = None
        self._video_path: str | None = None
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(QLabel("<h2>Auto Dubbing — Vietsub & Lồng tiếng tự động</h2>"))

        # Main horizontal layout dividing Left (Preview/Status) and Right (Options Grid)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)

        # ==================== LEFT COLUMN (40% width) ====================
        left_panel = QVBoxLayout()
        left_panel.setSpacing(10)

        # Video File Picker
        file_box = QHBoxLayout()
        self.file_line = QLineEdit()
        self.file_line.setPlaceholderText("Kéo thả video vào đây hoặc bấm Chọn video…")
        self.file_line.setReadOnly(True)
        browse = QPushButton("Chọn video…")
        browse.clicked.connect(self._browse)
        file_box.addWidget(self.file_line, 1)
        file_box.addWidget(browse)
        left_panel.addLayout(file_box)

        # Video info metadata
        self.meta_label = QLabel("Chưa chọn video.")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color: #888888; font-style: italic;")
        left_panel.addWidget(self.meta_label)

        # Video Preview Player Panel
        self.preview_box = QGroupBox("Xem trước Video")
        preview_lay = QVBoxLayout(self.preview_box)
        preview_lay.setContentsMargins(5, 10, 5, 5)
        self.preview = VideoPreviewWidget()
        self.preview.setMinimumHeight(280)
        preview_lay.addWidget(self.preview)
        left_panel.addWidget(self.preview_box, 1)

        # Progress Status & Action Controls
        status_box = QGroupBox("Trạng thái & Tiến hành")
        status_lay = QVBoxLayout(status_box)
        status_lay.setSpacing(8)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(18)
        status_lay.addWidget(self.progress)

        self.status = QLabel("Sẵn sàng.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #aaaaaa;")
        status_lay.addWidget(self.status)

        # Control Action Buttons Row
        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("▶  START — Dub toàn bộ")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.clicked.connect(self._start)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a7bd5;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border: none;
                padding: 6px 12px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #4a8be5;
            }
            QPushButton:pressed {
                background-color: #2c62ab;
            }
            QPushButton:disabled {
                background-color: #1e3552;
                color: #7792b5;
            }
        """)

        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)

        self.open_btn = QPushButton("Mở thư mục kết quả")
        self.open_btn.setMinimumHeight(38)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output)

        ctrl.addWidget(self.start_btn, 2)
        ctrl.addWidget(self.cancel_btn)
        ctrl.addWidget(self.open_btn)
        status_lay.addLayout(ctrl)

        left_panel.addWidget(status_box)
        main_layout.addLayout(left_panel, 2)

        # ==================== RIGHT COLUMN (60% width) ====================
        right_panel = QVBoxLayout()
        grid = QGridLayout()
        grid.setSpacing(12)

        # Groupbox 1: Chinese SRT source
        asr_box = QGroupBox("Phụ đề Tiếng Trung gốc (CapCut SRT)")
        af = QFormLayout(asr_box)
        self.chinese_srt_line = QLineEdit()
        self.chinese_srt_line.setPlaceholderText("Chọn file .srt Tiếng Trung từ CapCut…")
        chinese_srt_w = QWidget()
        chinese_srt_l = QHBoxLayout(chinese_srt_w)
        chinese_srt_l.setContentsMargins(0, 0, 0, 0)
        chinese_srt_l.addWidget(self.chinese_srt_line, 1)
        chinese_srt_btn = QPushButton("…")
        chinese_srt_btn.setMaximumWidth(32)
        chinese_srt_btn.clicked.connect(self._pick_chinese_srt)
        chinese_srt_l.addWidget(chinese_srt_btn)
        af.addRow("File SRT Trung", chinese_srt_w)
        grid.addWidget(asr_box, 0, 0)

        # Groupbox 2: Vietnamese Translation
        tr_box = QGroupBox("Dịch thuật & Phụ đề Tiếng Việt")
        tf = QFormLayout(tr_box)
        self.tr_mode_auto = QRadioButton("Dịch tự động bằng AI")
        self.tr_mode_import = QRadioButton("Nhập file dịch có sẵn")
        self.tr_mode_auto.setChecked(True)
        self.tr_mode_auto.toggled.connect(self._update_tr_mode_visibility)
        tf.addRow(self.tr_mode_auto)
        tf.addRow(self.tr_mode_import)

        # Container for auto translate options
        self._w_tr_auto = QWidget()
        tr_auto_l = QFormLayout(self._w_tr_auto)
        tr_auto_l.setContentsMargins(0, 0, 0, 0)
        self.engine_combo = QComboBox(); self.engine_combo.addItems(TRANSLATION_ENGINES)
        self.engine_combo.setCurrentText(self.state.config.get("translation.default_engine", "google"))
        self.style_combo = QComboBox(); self.style_combo.addItems(TRANSLATION_STYLES)
        self.style_combo.setCurrentText(self.state.config.get("translation.default_style", "Natural Vietnamese"))
        tr_auto_l.addRow("Engine", self.engine_combo)
        tr_auto_l.addRow("Phong cách", self.style_combo)

        self.custom_check = QCheckBox("Mô tả ngữ cảnh dịch")
        self.custom_check.toggled.connect(self._toggle_custom)
        self.custom_text = QTextEdit()
        self.custom_text.setPlaceholderText("VD: Dịch theo văn phong trẻ trung, bắt trend...")
        self.custom_text.setMaximumHeight(60)
        self.custom_text.setEnabled(False)
        tr_auto_l.addRow(self.custom_check)
        tr_auto_l.addRow(self.custom_text)
        tf.addRow(self._w_tr_auto)

        # Container for import translate option
        self._w_tr_import = QWidget()
        tr_import_l = QFormLayout(self._w_tr_import)
        tr_import_l.setContentsMargins(0, 0, 0, 0)
        self.vi_srt_line = QLineEdit()
        self.vi_srt_line.setPlaceholderText("Chọn file .srt tiếng Việt đã dịch sẵn…")
        vi_srt_w = QWidget()
        vi_srt_lh = QHBoxLayout(vi_srt_w)
        vi_srt_lh.setContentsMargins(0, 0, 0, 0)
        vi_srt_lh.addWidget(self.vi_srt_line, 1)
        vi_srt_btn = QPushButton("…")
        vi_srt_btn.setMaximumWidth(32)
        vi_srt_btn.clicked.connect(self._pick_vi_srt)
        vi_srt_lh.addWidget(vi_srt_btn)
        tr_import_l.addRow("File SRT Việt", vi_srt_w)
        tf.addRow(self._w_tr_import)

        self._update_tr_mode_visibility()
        grid.addWidget(tr_box, 0, 1)

        # Groupbox 3: TTS Settings
        tts_box = QGroupBox("Lồng tiếng (TTS)")
        ttf = QFormLayout(tts_box)
        self.dub_check = QCheckBox("Tạo giọng lồng tiếng"); self.dub_check.setChecked(True)
        self.tts_engine_combo = QComboBox(); self.tts_engine_combo.addItems(TTS_ENGINES)
        self.tts_engine_combo.setCurrentText(self.state.config.get("tts.default_engine", "edge"))
        self.tts_engine_combo.currentTextChanged.connect(lambda _t: self._update_tts_visibility())
        self.voice_combo = QComboBox(); self.voice_combo.addItems(EDGE_VI_VOICES.keys())
        self.speed_spin = QDoubleSpinBox(); self.speed_spin.setRange(0.5, 2.0)
        self.speed_spin.setSingleStep(0.05); self.speed_spin.setValue(self.state.config.get("tts.default_speed", 1.2))
        self.keep_combo = QComboBox(); self.keep_combo.addItems(_KEEP_ORIGINAL.keys())
        self.fit_check = QCheckBox("Tự khớp timeline (chống lệch tiếng)")
        self.fit_check.setChecked(True)
        self.fit_speed = QComboBox()
        self.fit_speed.addItems(["1.5x", "2.0x", "2.5x", "3.0x", "3.5x"])
        self.fit_speed.setCurrentText("2.5x")

        # VoxCPM specific controls
        self.vox_mode_combo = QComboBox()
        self.vox_mode_combo.addItems([
            "Giọng nữ (cố định)", "Giọng nam (cố định)",
            "Mặc định (cố định)", "Clone giọng Review Phim (cc.wav)", "Clone từ file mẫu", "Tự mô tả giọng",
        ])
        self.vox_mode_combo.currentTextChanged.connect(lambda _t: self._update_tts_visibility())
        self.vox_ref_line = QLineEdit()
        self.vox_ref_line.setPlaceholderText("Chọn file giọng mẫu .wav để clone…")
        vox_ref_w = QWidget()
        vox_ref_l = QHBoxLayout(vox_ref_w); vox_ref_l.setContentsMargins(0, 0, 0, 0)
        vox_ref_l.addWidget(self.vox_ref_line, 1)
        vox_ref_btn = QPushButton("…"); vox_ref_btn.setMaximumWidth(32)
        vox_ref_btn.clicked.connect(self._pick_voice_sample)
        vox_ref_l.addWidget(vox_ref_btn)
        self.vox_design_line = QLineEdit()
        self.vox_design_line.setPlaceholderText("VD: nam, trẻ tuổi, giọng trầm ấm, vui vẻ")

        ttf.addRow("", self.dub_check)
        self._lbl_engine = QLabel("Engine"); ttf.addRow(self._lbl_engine, self.tts_engine_combo)
        self._lbl_voice = QLabel("Giọng đọc"); ttf.addRow(self._lbl_voice, self.voice_combo)
        self._lbl_speed = QLabel("Tốc độ"); ttf.addRow(self._lbl_speed, self.speed_spin)
        self._lbl_vox_mode = QLabel("VoxCPM chế độ"); ttf.addRow(self._lbl_vox_mode, self.vox_mode_combo)
        self._lbl_vox_ref = QLabel("Giọng mẫu (clone)"); ttf.addRow(self._lbl_vox_ref, vox_ref_w)
        self._w_vox_ref = vox_ref_w
        self._lbl_vox_design = QLabel("Mô tả giọng"); ttf.addRow(self._lbl_vox_design, self.vox_design_line)
        self._lbl_keep = QLabel("Tiếng gốc"); ttf.addRow(self._lbl_keep, self.keep_combo)
        ttf.addRow("", self.fit_check)
        self._lbl_fit = QLabel("Tăng tốc tối đa"); ttf.addRow(self._lbl_fit, self.fit_speed)
        self._update_tts_visibility()
        grid.addWidget(tts_box, 1, 0)

        # Groupbox 4: Video Export settings
        out_box = QGroupBox("Xuất video")
        of = QFormLayout(out_box)
        self.burn_check = QCheckBox("Ghi phụ đề tiếng Việt"); self.burn_check.setChecked(True)
        self.wordbyword_check = QCheckBox("Hiện từng chữ theo lời nói (kiểu TikTok)")
        self.aspect_combo = QComboBox(); self.aspect_combo.addItems(RENDER_PRESETS.keys())
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItems(["libx264", "libx265", "h264_nvenc", "hevc_nvenc"])
        self.encoder_combo.setCurrentText(self.state.config.get("render.default_encoder", "libx264"))

        self.mode_auto_radio = QRadioButton("Tự động (làm mờ + sub, chỉ chọn cỡ chữ)")
        self.mode_custom_radio = QRadioButton("Tùy chỉnh (preview, kéo thả vị trí & kiểu chữ)")
        self.mode_auto_radio.setChecked(True)
        self.mode_auto_radio.toggled.connect(lambda _c: self._update_sub_mode())

        self.autoblur_check = QCheckBox("Tự làm mờ chữ gốc (dải dưới video)")
        self.autoblur_check.setChecked(True)
        self.font_size = QSpinBox(); self.font_size.setRange(10, 96)
        self.font_size.setValue(self.state.config.get("subtitle_style.font_size", 24))
        self.blur_btn = QPushButton("Preview: vùng mờ & kiểu phụ đề…")
        self.blur_btn.clicked.connect(self._open_blur_editor)

        of.addRow("", self.burn_check)
        of.addRow("", self.wordbyword_check)
        of.addRow("Khung hình", self.aspect_combo)
        of.addRow("Encoder", self.encoder_combo)
        of.addRow(QLabel("<b>Chế độ phụ đề</b>"))
        of.addRow(self.mode_auto_radio)
        of.addRow(self.mode_custom_radio)
        self._lbl_autoblur = QLabel("Làm mờ gốc"); of.addRow(self._lbl_autoblur, self.autoblur_check)
        self._lbl_fontsize = QLabel("Cỡ chữ phụ đề"); of.addRow(self._lbl_fontsize, self.font_size)
        of.addRow(self.blur_btn)
        self._update_sub_mode()
        grid.addWidget(out_box, 1, 1)

        right_panel.addLayout(grid)
        main_layout.addLayout(right_panel, 3)

        root.addLayout(main_layout)
        root.addStretch(1)

        self._output_path: str | None = None
        self._blur_regions: list = []
        self._sub_style: dict | None = None
        self._sub_box = None

    def _update_sub_mode(self) -> None:
        """Auto mode = font size only; Custom mode = Preview dialog."""
        auto = self.mode_auto_radio.isChecked()
        # Auto: enable font size + auto-blur checkbox, disable Preview button.
        self._lbl_fontsize.setEnabled(auto)
        self.font_size.setEnabled(auto)
        self._lbl_autoblur.setEnabled(auto)
        self.autoblur_check.setEnabled(auto)
        # Custom: enable Preview button, disable font size (style comes from dialog).
        self.blur_btn.setEnabled(not auto)
        if auto:
            # leaving custom mode: drop the per-style override so font size wins
            self._sub_style = None

    def _toggle_custom(self, on: bool) -> None:
        self.custom_text.setEnabled(on)

    def _update_tts_visibility(self) -> None:
        """Show edge-style voice picker OR VoxCPM controls based on engine."""
        engine = self.tts_engine_combo.currentText()
        is_vox = engine in ("voxcpm", "voxcpm2")
        mode = self.vox_mode_combo.currentText()

        # Edge/Piper use the preset voice dropdown; VoxCPM uses its own controls.
        self._lbl_voice.setEnabled(not is_vox)
        self.voice_combo.setEnabled(not is_vox)

        self._lbl_vox_mode.setEnabled(is_vox)
        self.vox_mode_combo.setEnabled(is_vox)
        mode_label = self.vox_mode_combo.currentText()
        show_ref = is_vox and mode_label == "Clone từ file mẫu"
        show_design = is_vox and mode_label == "Tự mô tả giọng"
        self._lbl_vox_ref.setEnabled(show_ref)
        self._w_vox_ref.setEnabled(show_ref)
        self._lbl_vox_design.setEnabled(show_design)
        self.vox_design_line.setEnabled(show_design)

    def _update_tr_mode_visibility(self) -> None:
        auto = self.tr_mode_auto.isChecked()
        self._w_tr_auto.setEnabled(auto)
        self._w_tr_import.setEnabled(not auto)

    def _pick_chinese_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file phụ đề Tiếng Trung", "", "Subtitles (*.srt *.vtt *.json)")
        if path:
            self.chinese_srt_line.setText(path)

    def _pick_vi_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file phụ đề Tiếng Việt", "", "Subtitles (*.srt *.vtt *.json)")
        if path:
            self.vi_srt_line.setText(path)

    def _pick_voice_sample(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file giọng mẫu", "", "Audio (*.wav *.mp3 *.flac *.m4a)")
        if path:
            self.vox_ref_line.setText(path)

    def _open_blur_editor(self) -> None:
        if not self._video_path:
            QMessageBox.information(self, "Làm mờ", "Chọn video trước đã.")
            return
        info = getattr(self, "_media_info", None)
        vw = info.width if info else 1920
        vh = info.height if info else 1080
        frame_path = None
        try:
            ff = FFmpegService(self.state.config)
            frame_path = str(self.state.config.temp_folder() / "blur_frame.png")
            ff.extract_frame(self._video_path, frame_path, at_seconds=1.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Không trích được frame preview: %s", exc)
            frame_path = None
        from ui.widgets.blur_picker_dialog import BlurPickerDialog
        dlg = BlurPickerDialog(
            frame_path, vw, vh, self._blur_regions,
            sub_style=self._sub_style, sub_box=self._sub_box, parent=self)
        if dlg.exec():
            self._blur_regions = dlg.regions()
            self._sub_style = dlg.subtitle_style()
            self._sub_box = dlg.subtitle_box()
            self.status.setText(
                f"Đã lưu: {len(self._blur_regions)} vùng mờ + kiểu phụ đề tùy chỉnh.")

    # ---- drag & drop -------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if is_supported_video(path):
                self._set_video(path)
                break

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video", "", "Videos (*.mp4 *.mkv *.mov *.avi *.webm)")
        if path:
            self._set_video(path)

    def _set_video(self, path: str) -> None:
        self._video_path = path
        self.file_line.setText(path)
        self.meta_label.setText("Đang đọc thông tin video…")
        try:
            self.preview.load(path)
        except Exception as exc:
            logger.warning("Failed to load video preview: %s", exc)
        try:
            info = MediaInfoService(self.state.config).get_media_info(path)
            self._media_info = info
            self.meta_label.setText(
                f"<b>{Path(path).name}</b> — {format_duration(info.duration)}, "
                f"{info.width}x{info.height} @ {info.fps:.0f}fps, "
                f"audio: {info.audio_codec or 'none'}"
            )
        except Exception as exc:  # noqa: BLE001
            self._media_info = None
            self.meta_label.setText(f"Không đọc được metadata: {exc}")

    # ---- run ---------------------------------------------------------
    def _start(self) -> None:
        if not self._video_path:
            QMessageBox.information(self, "Auto Dubbing", "Chọn video trước đã.")
            return

        chinese_srt = self.chinese_srt_line.text().strip()
        if not chinese_srt:
            QMessageBox.information(self, "Auto Dubbing", "Hãy chọn file SRT tiếng Trung từ CapCut.")
            return

        import_vi = self.tr_mode_import.isChecked()
        vi_srt = self.vi_srt_line.text().strip()
        if import_vi and not vi_srt:
            QMessageBox.information(self, "Auto Dubbing", "Hãy chọn file SRT tiếng Việt đã dịch.")
            return

        ff = FFmpegService(self.state.config)
        if not ff.check_ffmpeg_available():
            QMessageBox.critical(self, "FFmpeg", "Không tìm thấy FFmpeg. Vào Settings để cấu hình.")
            return

        project = Project(id=uuid.uuid4().hex[:12],
                          name=safe_filename(Path(self._video_path).name),
                          source_video=self._video_path)
        db.create_project(project)
        info = getattr(self, "_media_info", None)
        db.upsert_job(VideoJob(id=project.id, project_id=project.id,
                               source_video=self._video_path, media_info=info))
        self.state.set_project(project, info)

        size = RENDER_PRESETS[self.aspect_combo.currentText()]
        preset = RenderPreset(
            width=size[0] if size else None,
            height=size[1] if size else None,
            encoder=self.encoder_combo.currentText(),
            crf=self.state.config.get("render.default_crf", 20),
            preset=self.state.config.get("render.default_preset", "medium"),
        )
        tts_engine = self.tts_engine_combo.currentText()
        if tts_engine in ("voxcpm", "voxcpm2"):
            mode = self.vox_mode_combo.currentText()
            if mode == "Clone từ file mẫu":
                voice = f"clone:{self.vox_ref_line.text().strip()}"
            elif mode == "Clone giọng Review Phim (cc.wav)":
                models_folder = self.state.config.get("models_folder", "./data/models")
                from utils.path_utils import resolve_path
                cc_path = str(resolve_path(models_folder) / "voxcpm" / "cc.wav")
                voice = f"clone:{cc_path}"
            elif mode == "Tự mô tả giọng":
                voice = f"design:{self.vox_design_line.text().strip()}"
            elif mode == "Giọng nữ (cố định)":
                voice = "design:a warm, natural young female voice, clear and friendly"
            elif mode == "Giọng nam (cố định)":
                voice = "design:a warm, natural adult male voice, clear and steady"
            else:  # "Mặc định (cố định)"
                voice = ""
        else:
            voice = EDGE_VI_VOICES[self.voice_combo.currentText()]

        # Subtitle mode: Auto = font size + auto-blur; Custom = preview dialog.
        auto_sub = self.mode_auto_radio.isChecked()
        if auto_sub:
            blur_regions = []
            auto_blur = self.autoblur_check.isChecked()
            sub_style = None
            sub_font_size = self.font_size.value()
        else:
            blur_regions = self._blur_regions
            auto_blur = False
            sub_style = self._sub_style
            sub_font_size = None

        opts = AutoDubbingOptions(
            chinese_srt_path=chinese_srt,
            import_vi_srt=import_vi,
            vi_srt_path=vi_srt,
            translation_engine=self.engine_combo.currentText(),
            translation_style=self.style_combo.currentText(),
            custom_context=(self.custom_text.toPlainText()
                            if self.custom_check.isChecked() else ""),
            tts_engine=tts_engine,
            voice=voice,
            speed=self.speed_spin.value(),
            do_dubbing=self.dub_check.isChecked(),
            burn_subtitle=self.burn_check.isChecked(),
            keep_original_volume=_KEEP_ORIGINAL[self.keep_combo.currentText()],
            fit_timeline=self.fit_check.isChecked(),
            max_fit_speed=float(self.fit_speed.currentText().rstrip("x")),
            blur_regions=blur_regions,
            auto_blur_subtitle=auto_blur,
            sub_font_size=sub_font_size,
            sub_style=sub_style,
            word_by_word=self.wordbyword_check.isChecked(),
            preset=preset,
        )

        def task(ctx):
            return AutoDubbingService(self.state.config).run(ctx, project, opts)

        self._set_running(True)
        self._worker = Worker(task)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_done)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.status.setText("Đang hủy…")

    def _on_progress(self, pct: float, msg: str) -> None:
        self.progress.setValue(int(pct))
        if msg:
            self.status.setText(msg)

    def _on_done(self, out_path: str) -> None:
        self._output_path = out_path
        self.progress.setValue(100)
        self.status.setText(f"✅ Hoàn tất: {out_path}")
        self._set_running(False)
        self.open_btn.setEnabled(True)
        self.state.set_segments(db.load_segments(self.state.project.id))
        QMessageBox.information(self, "Xong", f"Video lồng tiếng đã tạo:\n{out_path}")

    def _on_failed(self, err: str) -> None:
        first = err.split("\n")[0]
        self.status.setText(f"❌ Lỗi: {first}")
        self._set_running(False)
        QMessageBox.critical(self, "Auto Dubbing thất bại", first)

    def _open_output(self) -> None:
        if self._output_path:
            folder = str(Path(self._output_path).parent)
            import os
            os.startfile(folder)  # Windows

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)

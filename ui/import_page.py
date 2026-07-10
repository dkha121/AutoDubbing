"""Import page: drag & drop video, read metadata, create a project."""
from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QLabel, QHBoxLayout, QListWidget,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core import database as db
from core.logger import get_logger
from core.worker import Worker
from models.project import Project
from models.video_job import VideoJob
from services.media_info_service import MediaInfoService
from ui.app_state import AppState
from ui.widgets.video_preview_widget import VideoPreviewWidget
from utils.path_utils import safe_filename
from utils.time_utils import format_duration
from utils.validation_utils import is_supported_video

logger = get_logger(__name__)


class ImportPage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._worker: Worker | None = None
        self.setAcceptDrops(True)

        root = QHBoxLayout(self)

        # Left: file list + buttons
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Videos</b> (drag & drop or browse)"))
        self.file_list = QListWidget()
        left.addWidget(self.file_list, 1)
        btn_row = QHBoxLayout()
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse)
        self.import_btn = QPushButton("Import Selected")
        self.import_btn.clicked.connect(self._import_selected)
        btn_row.addWidget(self.browse_btn)
        btn_row.addWidget(self.import_btn)
        left.addLayout(btn_row)
        root.addLayout(left, 1)

        # Right: preview + metadata
        right = QVBoxLayout()
        self.preview = VideoPreviewWidget()
        right.addWidget(self.preview, 1)
        self.meta_label = QLabel("No media info")
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.meta_label)
        root.addLayout(right, 2)

        self.file_list.itemSelectionChanged.connect(self._on_select)

    # ---- drag & drop -------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if is_supported_video(path):
                self._add_file(path)
            else:
                logger.warning("Unsupported file dropped: %s", path)

    def _browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select video(s)", "",
            "Videos (*.mp4 *.mkv *.mov *.avi *.webm);;All files (*.*)",
        )
        for f in files:
            self._add_file(f)

    def _add_file(self, path: str) -> None:
        existing = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        if path not in existing:
            self.file_list.addItem(path)

    def _on_select(self) -> None:
        items = self.file_list.selectedItems()
        if items:
            self.preview.load(items[0].text())

    def _import_selected(self) -> None:
        items = self.file_list.selectedItems()
        if not items:
            QMessageBox.information(self, "Import", "Select a video first.")
            return
        path = items[0].text()
        self.meta_label.setText("Reading media info…")

        def task(ctx, video_path):
            return MediaInfoService(self.state.config).get_media_info(video_path)

        self._worker = Worker(task, path)
        self._worker.signals.finished.connect(lambda info: self._on_imported(path, info))
        self._worker.signals.failed.connect(
            lambda err: QMessageBox.critical(self, "Import failed", err.split("\n")[0])
        )
        self._worker.start()

    def _on_imported(self, path: str, info) -> None:
        project = Project(
            id=uuid.uuid4().hex[:12],
            name=safe_filename(Path(path).name),
            source_video=path,
        )
        db.create_project(project)
        job = VideoJob(id=uuid.uuid4().hex[:12], project_id=project.id,
                       source_video=path, media_info=info)
        db.upsert_job(job)
        self.state.set_project(project, info)

        self.meta_label.setText(
            f"<b>Project:</b> {project.name} ({project.id})<br>"
            f"<b>Duration:</b> {format_duration(info.duration)}<br>"
            f"<b>Resolution:</b> {info.width}x{info.height} @ {info.fps:.2f} fps<br>"
            f"<b>Bitrate:</b> {info.bitrate} bps<br>"
            f"<b>Video codec:</b> {info.video_codec}<br>"
            f"<b>Audio codec:</b> {info.audio_codec or 'none'}<br>"
            f"<b>Subtitle streams:</b> {', '.join(info.subtitle_streams) or 'none'}"
        )
        logger.info("Imported project %s from %s", project.id, path)

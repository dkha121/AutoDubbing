"""Batch Queue page: add multiple videos, run end-to-end pipeline sequentially."""
from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core import database as db
from core.constants import JobStatus
from core.logger import get_logger
from core.worker import Worker
from models.project import Project
from models.render_preset import RenderPreset
from models.video_job import VideoJob
from services.batch_service import BatchService
from services.media_info_service import MediaInfoService
from ui.app_state import AppState
from utils.path_utils import safe_filename
from utils.validation_utils import is_supported_video

logger = get_logger(__name__)

_COLS = ["Job", "Video", "Status", "Progress"]


class BatchQueuePage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._queue: list[VideoJob] = []
        self._worker: Worker | None = None
        self._running = False
        self._current = 0

        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        add_btn = QPushButton("Add videos")
        add_btn.clicked.connect(self._add)
        self.run_btn = QPushButton("Run queue")
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        self.retry_btn = QPushButton("Retry failed")
        self.retry_btn.clicked.connect(self._retry)
        self.translate_check = QCheckBox("Translate")
        self.translate_check.setChecked(True)
        self.burn_check = QCheckBox("Burn subtitle")
        self.burn_check.setChecked(True)
        for w in (add_btn, self.run_btn, self.stop_btn, self.retry_btn,
                  self.translate_check, self.burn_check):
            toolbar.addWidget(w)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        self.progress = QProgressBar()
        root.addWidget(self.progress)

    def _add(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add videos", "", "Videos (*.mp4 *.mkv *.mov *.avi *.webm)")
        for path in files:
            if not is_supported_video(path):
                continue
            project = Project(id=uuid.uuid4().hex[:12], name=safe_filename(Path(path).name),
                              source_video=path)
            db.create_project(project)
            job = VideoJob(id=uuid.uuid4().hex[:12], project_id=project.id, source_video=path)
            db.upsert_job(job)
            self._queue.append(job)
        self._refresh()

    def _refresh(self) -> None:
        self.table.setRowCount(len(self._queue))
        for row, job in enumerate(self._queue):
            self.table.setItem(row, 0, QTableWidgetItem(job.id))
            self.table.setItem(row, 1, QTableWidgetItem(Path(job.source_video).name))
            self.table.setItem(row, 2, QTableWidgetItem(job.status))
            self.table.setItem(row, 3, QTableWidgetItem(f"{job.progress:.0f}%"))

    def _run(self) -> None:
        if self._running or not self._queue:
            return
        self._current = 0
        self._running = True
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._run_next()

    def _run_next(self) -> None:
        if not self._running or self._current >= len(self._queue):
            self._finish_queue()
            return
        job = self._queue[self._current]
        if job.status == JobStatus.COMPLETED.value:
            self._current += 1
            self._run_next()
            return
        svc = BatchService(self.state.config)
        translate = self.translate_check.isChecked()
        burn = self.burn_check.isChecked()

        def task(ctx):
            return svc.run_job(ctx, job, translate=translate, burn_subtitle=burn,
                               preset=RenderPreset(burn_subtitle=burn))

        self._worker = Worker(task)
        self._worker.signals.progress.connect(lambda p, m: self._on_progress(job, p, m))
        self._worker.signals.finished.connect(lambda _r: self._on_job_done(job))
        self._worker.signals.failed.connect(lambda err: self._on_job_failed(job, err))
        self._worker.start()

    def _on_progress(self, job: VideoJob, pct: float, msg: str) -> None:
        job.progress = pct
        row = self._queue.index(job)
        self.table.setItem(row, 2, QTableWidgetItem(msg[:30]))
        self.table.setItem(row, 3, QTableWidgetItem(f"{pct:.0f}%"))
        overall = (self._current + pct / 100) / max(1, len(self._queue)) * 100
        self.progress.setValue(int(overall))

    def _on_job_done(self, job: VideoJob) -> None:
        job.status = JobStatus.COMPLETED.value
        self._refresh()
        self._current += 1
        self._run_next()

    def _on_job_failed(self, job: VideoJob, err: str) -> None:
        job.status = JobStatus.FAILED.value
        job.error = err.split("\n")[0]
        db.update_job_status(job.id, job.status, error=job.error)
        self._refresh()
        self._current += 1
        self._run_next()

    def _stop(self) -> None:
        self._running = False
        if self._worker:
            self._worker.cancel()
        self._finish_queue()

    def _retry(self) -> None:
        for job in self._queue:
            if job.status == JobStatus.FAILED.value:
                job.status = JobStatus.PENDING.value
                job.progress = 0.0
        self._refresh()

    def _finish_queue(self) -> None:
        self._running = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

"""Shared UI application state passed to all pages.

Holds the current project, segments, blur regions and the active worker so pages
can coordinate without tight coupling. Pages emit Qt signals through this hub.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from core.app_config import AppConfig
from models.blur_region import BlurRegion
from models.project import Project
from models.subtitle_segment import SubtitleSegment
from models.video_job import MediaInfo


class AppState(QObject):
    project_changed = Signal(object)       # Project
    segments_changed = Signal()            # current segments updated
    media_info_changed = Signal(object)    # MediaInfo

    def __init__(self) -> None:
        super().__init__()
        self.config = AppConfig.instance()
        self.project: Project | None = None
        self.media_info: MediaInfo | None = None
        self.segments: list[SubtitleSegment] = []
        self.blur_regions: list[BlurRegion] = []

    def set_project(self, project: Project, media_info: MediaInfo | None = None) -> None:
        self.project = project
        self.media_info = media_info
        self.segments = []
        self.blur_regions = []
        self.project_changed.emit(project)
        if media_info:
            self.media_info_changed.emit(media_info)

    def set_segments(self, segments: list[SubtitleSegment]) -> None:
        self.segments = segments
        self.segments_changed.emit()

    def require_project(self) -> Project | None:
        return self.project

"""Blur/logo obscuring service + inpaint provider placeholders.

Applies rectangular blur/box/delogo regions to a video via FFmpeg filters.
Inpaint providers (LaMa, ProPainter) are placeholders with a shared interface
for a future AI-based clean removal of subtitles/logos.
"""
from __future__ import annotations

import abc

from core.app_config import AppConfig
from core.logger import get_logger
from models.blur_region import BlurRegion
from services.ffmpeg_service import FFmpegService

logger = get_logger(__name__)


class BlurService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()
        self.ffmpeg = FFmpegService(self.config)

    def apply(self, video_path: str, regions: list[BlurRegion], output_path: str,
              encoder: str = "libx264", crf: int = 20, preset: str = "medium",
              total_duration: float = 0.0, progress_cb=None) -> str:
        if not regions:
            logger.info("No blur regions; skipping blur step")
            return video_path
        return self.ffmpeg.apply_blur_regions(
            video_path, regions, output_path, encoder, crf, preset, total_duration, progress_cb
        )


class InpaintProvider(abc.ABC):
    """Interface for future AI inpainting (clean removal instead of blur)."""

    @abc.abstractmethod
    def inpaint(self, video_path: str, regions: list[BlurRegion], output_path: str) -> str:
        raise NotImplementedError

    def is_available(self) -> tuple[bool, str]:
        return False, "Not implemented"


class LamaInpaintProvider(InpaintProvider):
    def inpaint(self, video_path, regions, output_path):
        raise NotImplementedError("LaMa inpaint is a placeholder.")


class ProPainterProvider(InpaintProvider):
    def inpaint(self, video_path, regions, output_path):
        raise NotImplementedError("ProPainter inpaint is a placeholder.")

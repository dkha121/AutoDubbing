"""Batch pipeline orchestration.

Runs the end-to-end dubbing pipeline for a single job and exposes a callable
suitable for running inside a core.worker.Worker. The batch queue UI feeds jobs
here one at a time (respecting max_concurrent_jobs).
"""
from __future__ import annotations

from pathlib import Path

from core.app_config import AppConfig
from core import database as db
from core.constants import JobStatus
from core.logger import get_logger
from models.project import Project
from models.render_preset import RenderPreset
from models.video_job import VideoJob
from services.asr_service import ASRService
from services.ffmpeg_service import FFmpegService
from services.media_info_service import MediaInfoService
from services.render_service import RenderService
from services.subtitle_service import SubtitleService
from services.translation_service import get_provider
from utils import srt_utils

logger = get_logger(__name__)


class BatchService:
    """Executes the full pipeline for a job. UI passes a TaskContext-like ctx
    with .progress(pct, msg), .log(msg), and .raise_if_cancelled()."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()
        self.media = MediaInfoService(self.config)
        self.ffmpeg = FFmpegService(self.config)
        self.asr = ASRService(self.config)
        self.render = RenderService(self.config)

    def run_job(self, ctx, job: VideoJob, *, translate: bool = True,
                burn_subtitle: bool = True, preset: RenderPreset | None = None) -> str:
        """Run import->...->render for one job. Returns output path."""
        project = db.get_project(job.project_id) or Project(id=job.project_id)
        project.ensure_layout()
        preset = preset or RenderPreset()

        def step(status: JobStatus, pct: float, msg: str) -> None:
            ctx.raise_if_cancelled()
            db.update_job_status(job.id, status.value, pct, msg)
            ctx.progress(pct, msg)
            ctx.log(f"[{job.id}] {msg}")

        # 1. Media info
        step(JobStatus.IMPORTING, 2, "Reading media info")
        info = self.media.get_media_info(job.source_video)
        job.media_info = info

        # 2. Extract audio
        step(JobStatus.EXTRACTING_AUDIO, 8, "Extracting audio")
        audio_wav = str(project.subdir("audio") / "source.wav")
        self.ffmpeg.extract_audio(job.source_video, audio_wav, info.duration,
                                  lambda p, m: ctx.progress(8 + p * 0.07, m))

        # 3. Transcribe
        step(JobStatus.TRANSCRIBING, 15, "Transcribing audio")
        segments, detected = self.asr.transcribe(
            audio_wav, self.config.get("asr.default_language", "auto"),
            lambda p, m: ctx.progress(15 + p * 0.30, m),
        )
        project.source_language = detected
        srt_path = str(project.subdir("subtitles") / "source.srt")
        srt_utils.save_srt(segments, srt_path, use_vietnamese=False)
        db.save_segments(project.id, segments)

        # 4. Translate
        if translate:
            step(JobStatus.TRANSLATING, 50, "Translating to Vietnamese")
            provider = get_provider(self.config.get("translation.default_engine", "local"), self.config)
            segments = provider.translate_segments(
                segments, detected, "vi",
                self.config.get("translation.default_style", "Natural Vietnamese"),
                progress_cb=lambda p, m: ctx.progress(50 + p * 0.20, m),
            )
            SubtitleService.fix_overlaps(segments)
            db.save_segments(project.id, segments)

        vi_srt = str(project.subdir("subtitles") / "vi.srt")
        srt_utils.save_srt(segments, vi_srt, use_vietnamese=True)

        # 5. Render
        step(JobStatus.RENDERING, 75, "Rendering final video")
        preset.burn_subtitle = burn_subtitle
        out_path = str(project.subdir("render") / f"{project.id}_final.{preset.output_format}")
        blur_regions = db.load_blur_regions(project.id)
        self.render.render(
            video_path=job.source_video, output_path=out_path, preset=preset,
            srt_path=vi_srt if burn_subtitle else None,
            blur_regions=blur_regions or None,
            total_duration=info.duration,
            progress_cb=lambda p, m: ctx.progress(75 + p * 0.24, m),
        )

        job.output_path = out_path
        db.update_job_status(job.id, JobStatus.COMPLETED.value, 100, "Completed")
        db.upsert_job(job)
        ctx.progress(100, "Completed")
        ctx.log(f"[{job.id}] Completed -> {out_path}")
        return out_path

"""FFmpeg/FFprobe wrapper service.

All subprocess calls are built from ffmpeg_cmd_builder (pure functions) and run
here with full logging, stderr capture and an optional progress callback parsed
from FFmpeg's '-progress' / time= output.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Sequence

from core.app_config import AppConfig
from core.logger import get_logger
from models.blur_region import BlurRegion
from utils import ffmpeg_cmd_builder as cb
from utils.validation_utils import binary_available

logger = get_logger(__name__)

ProgressCb = Callable[[float, str], None] | None

_TIME_RE = re.compile(r"time=(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,2})")


class FFmpegError(RuntimeError):
    pass


class FFmpegService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()

    @property
    def ffmpeg(self) -> str:
        return self.config.ffmpeg_path()

    @property
    def ffprobe(self) -> str:
        return self.config.ffprobe_path()

    # ---- availability -------------------------------------------------
    def check_ffmpeg_available(self) -> bool:
        return binary_available(self.ffmpeg)

    def check_ffprobe_available(self) -> bool:
        return binary_available(self.ffprobe)

    # ---- command runner ----------------------------------------------
    def _run(self, cmd: Sequence[str], total_duration: float = 0.0,
             progress_cb: ProgressCb = None) -> str:
        """Run an ffmpeg command, streaming stderr to parse progress.

        Returns the captured stderr text. Raises FFmpegError on non-zero exit.
        """
        logger.info("FFmpeg cmd: %s", " ".join(str(c) for c in cmd))
        proc = subprocess.Popen(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        captured: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            captured.append(line)
            if progress_cb and total_duration > 0:
                m = _TIME_RE.search(line)
                if m:
                    h, mn, s, cs = (int(x) for x in m.groups())
                    elapsed = h * 3600 + mn * 60 + s + cs / 100.0
                    pct = min(100.0, elapsed / total_duration * 100.0)
                    progress_cb(pct, f"{elapsed:.0f}s / {total_duration:.0f}s")
        proc.wait()
        stderr_text = "".join(captured)
        if proc.returncode != 0:
            logger.error("FFmpeg failed (%s): %s", proc.returncode, stderr_text[-2000:])
            raise FFmpegError(f"FFmpeg exited with code {proc.returncode}")
        return stderr_text

    def run_raw(self, cmd: Sequence[str]) -> subprocess.CompletedProcess:
        """Run a command and capture output (used by ffprobe queries)."""
        logger.debug("Run: %s", " ".join(str(c) for c in cmd))
        return subprocess.run(list(cmd), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    # ---- operations ---------------------------------------------------
    def extract_audio(self, video_path: str, output_wav: str,
                      total_duration: float = 0.0, progress_cb: ProgressCb = None) -> str:
        Path(output_wav).parent.mkdir(parents=True, exist_ok=True)
        cmd = cb.build_extract_audio_cmd(self.ffmpeg, video_path, output_wav)
        self._run(cmd, total_duration, progress_cb)
        return output_wav

    def convert_audio_to_wav(self, input_path: str, output_path: str) -> str:
        cmd = cb.build_convert_wav_cmd(self.ffmpeg, input_path, output_path)
        self._run(cmd)
        return output_path

    def extract_frame(self, video_path: str, output_png: str, at_seconds: float = 1.0) -> str:
        """Grab a single frame as PNG (used as the blur-editor background)."""
        from pathlib import Path as _P
        _P(output_png).parent.mkdir(parents=True, exist_ok=True)
        cmd = [self.ffmpeg, "-y", "-ss", str(max(0.0, at_seconds)),
               "-i", video_path, "-frames:v", "1", "-q:v", "2", output_png]
        result = self.run_raw(cmd)
        if result.returncode != 0:
            raise FFmpegError(f"extract_frame failed: {result.stderr[-300:]}")
        return output_png

    def mute_original_audio(self, video_path: str, output_path: str) -> str:
        cmd = cb.build_mute_audio_cmd(self.ffmpeg, video_path, output_path)
        self._run(cmd)
        return output_path

    def merge_video_audio(self, video_path: str, audio_path: str, output_path: str,
                          audio_codec: str = "aac") -> str:
        cmd = cb.build_merge_video_audio_cmd(self.ffmpeg, video_path, audio_path, output_path, audio_codec)
        self._run(cmd)
        return output_path

    def extract_soft_subtitles(self, video_path: str, output_folder: str) -> list[str]:
        """Dump any embedded subtitle streams to .srt files. Best-effort."""
        out = Path(output_folder)
        out.mkdir(parents=True, exist_ok=True)
        results: list[str] = []
        # Probe stream count via ffprobe-based MediaInfoService is cleaner, but
        # here we attempt index 0 of subtitle streams; callers can extend.
        target = out / "embedded_0.srt"
        cmd = [self.ffmpeg, "-y", "-i", video_path, "-map", "0:s:0", str(target)]
        result = self.run_raw(cmd)
        if result.returncode == 0 and target.exists():
            results.append(str(target))
        return results

    def burn_subtitle(self, video_path: str, srt_path: str, output_path: str,
                      style: dict | None = None, encoder: str = "libx264",
                      crf: int = 20, preset: str = "medium",
                      total_duration: float = 0.0, progress_cb: ProgressCb = None) -> str:
        cmd = cb.build_burn_subtitle_cmd(
            self.ffmpeg, video_path, srt_path, output_path, style, encoder, crf, preset
        )
        self._run(cmd, total_duration, progress_cb)
        return output_path

    def apply_blur_regions(self, video_path: str, regions: list[BlurRegion], output_path: str,
                           encoder: str = "libx264", crf: int = 20, preset: str = "medium",
                           total_duration: float = 0.0, progress_cb: ProgressCb = None) -> str:
        vf = cb.build_blur_filter(regions)
        cmd = cb.build_render_cmd(
            self.ffmpeg, video_path, output_path, vf_filters=vf,
            encoder=encoder, crf=crf, preset=preset,
        )
        self._run(cmd, total_duration, progress_cb)
        return output_path

    def render_final_video(self, *, video_path: str, output_path: str,
                           vf_filters: str = "", encoder: str = "libx264",
                           crf: int = 20, preset: str = "medium",
                           width: int | None = None, height: int | None = None,
                           fps: int | None = None, bitrate: str | None = None,
                           audio_path: str | None = None, audio_codec: str = "aac",
                           total_duration: float = 0.0, progress_cb: ProgressCb = None) -> str:
        cmd = cb.build_render_cmd(
            self.ffmpeg, video_path, output_path, vf_filters=vf_filters,
            encoder=encoder, crf=crf, preset=preset, width=width, height=height,
            fps=fps, bitrate=bitrate, audio_path=audio_path, audio_codec=audio_codec,
        )
        self._run(cmd, total_duration, progress_cb)
        return output_path

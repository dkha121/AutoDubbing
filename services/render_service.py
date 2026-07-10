"""Final render orchestration.

Combines the pipeline: blur/logo filters -> burn subtitle -> mix/replace audio
-> encode to the chosen resolution/fps/encoder. Also supports a short preview
render (first N seconds) for quick iteration.
"""
from __future__ import annotations

from pathlib import Path

from core.app_config import AppConfig
from core.logger import get_logger
from models.blur_region import BlurRegion
from models.render_preset import RenderPreset
from services.ffmpeg_service import FFmpegService
from utils import ffmpeg_cmd_builder as cb

logger = get_logger(__name__)


class RenderService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()
        self.ffmpeg = FFmpegService(self.config)

    def render(self, *, video_path: str, output_path: str,
               preset: RenderPreset,
               srt_path: str | None = None,
               ass_path: str | None = None,
               blur_regions: list[BlurRegion] | None = None,
               audio_path: str | None = None,
               total_duration: float = 0.0,
               preview_seconds: int = 0,
               style_override: dict | None = None,
               progress_cb=None) -> str:
        """Run the full render pipeline in a single FFmpeg invocation where
        possible (region-scoped blur + scale + subtitle).

        Subtitle source precedence: `ass_path` (preferred — it carries its own
        PlayResX/Y so font size and margins are true pixels) over `srt_path`
        (legacy, styled via libass force_style at default resolution).
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Build the "extra" video filters that apply to the whole frame AFTER
        # any region blur: scale + burned-in subtitle. These stay sharp on top.
        extra_parts: list[str] = []
        if preset.width and preset.height:
            extra_parts.append(f"scale={preset.width}:{preset.height}")
        if preset.burn_subtitle and ass_path:
            # ASS file already carries PlayResX/Y + full styling.
            extra_parts.append(f"ass='{cb._escape_subtitle_path(ass_path)}'")
        elif preset.burn_subtitle and srt_path:
            style = dict(self.config.get("subtitle_style", {}))
            if style_override:
                style.update({k: v for k, v in style_override.items() if v is not None})
            sub = f"subtitles='{cb._escape_subtitle_path(srt_path)}'"
            force_style = cb.build_subtitle_style(style)
            if force_style:
                sub += f":force_style='{force_style}'"
            extra_parts.append(sub)
        extra_vf = ",".join(extra_parts)

        cmd = [self.ffmpeg.ffmpeg, "-y"]
        if preview_seconds > 0:
            cmd += ["-t", str(preview_seconds)]
        cmd += ["-i", video_path]
        if audio_path:
            cmd += ["-i", audio_path]

        # Region-scoped blur needs filter_complex (crop -> blur -> overlay).
        complex_graph, out_label = cb.build_region_blur_complex(
            list(blur_regions or []), in_label="0:v", out_label="vout", extra_vf=extra_vf
        )
        if complex_graph:
            cmd += ["-filter_complex", complex_graph, "-map", f"[{out_label}]"]
            if audio_path:
                cmd += ["-map", "1:a:0"]
            else:
                cmd += ["-map", "0:a?"]
        else:
            if extra_vf:
                cmd += ["-vf", extra_vf]
            if audio_path:
                cmd += ["-map", "0:v:0", "-map", "1:a:0"]

        cmd += ["-c:v", preset.encoder]
        cmd += cb._video_quality_args(preset.encoder, preset.crf, preset.preset)
        if preset.fps:
            cmd += ["-r", str(preset.fps)]
        if preset.bitrate:
            cmd += ["-b:v", preset.bitrate]

        cmd += ["-c:a", preset.audio_codec]
        if audio_path:
            cmd += ["-shortest"]
        cmd.append(output_path)

        dur = min(total_duration, preview_seconds) if preview_seconds else total_duration
        self.ffmpeg._run(cmd, dur, progress_cb)
        return output_path

    def render_preview(self, *, video_path: str, output_path: str, preset: RenderPreset,
                       srt_path: str | None = None, blur_regions=None,
                       audio_path: str | None = None, seconds: int = 10,
                       progress_cb=None) -> str:
        return self.render(
            video_path=video_path, output_path=output_path, preset=preset,
            srt_path=srt_path, blur_regions=blur_regions, audio_path=audio_path,
            total_duration=seconds, preview_seconds=seconds, progress_cb=progress_cb,
        )

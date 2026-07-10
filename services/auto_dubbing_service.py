"""One-click auto-dubbing pipeline.

Runs the complete flow for a single video and produces a finished dubbed video:

  extract audio -> transcribe -> translate (VI) -> TTS dubbing audio
  -> (optional) keep original audio at low volume -> burn VI subtitle -> render

Designed to be called from a core.worker.Worker. `ctx` must expose
.progress(pct, msg), .log(msg) and .raise_if_cancelled().
"""
from __future__ import annotations

from pathlib import Path

from core.app_config import AppConfig
from core import database as db
from core.constants import JobStatus
from core.logger import get_logger
from models.project import Project
from models.render_preset import RenderPreset
from models.subtitle_segment import SubtitleSegment
from services.asr_service import ASRService
from services.ffmpeg_service import FFmpegService
from services.media_info_service import MediaInfoService
from services.render_service import RenderService
from services.subtitle_service import SubtitleService
from services.translation_service import get_provider
from services.tts_service import TTSAssembler, get_tts_provider
from utils import srt_utils

logger = get_logger(__name__)

# Human-readable names for languages Whisper commonly detects.
_LANG_NAMES = {
    "en": "Tiếng Anh", "zh": "Tiếng Trung", "ja": "Tiếng Nhật",
    "ko": "Tiếng Hàn", "vi": "Tiếng Việt", "fr": "Tiếng Pháp",
    "es": "Tiếng Tây Ban Nha", "de": "Tiếng Đức", "ru": "Tiếng Nga",
    "th": "Tiếng Thái", "id": "Tiếng Indonesia", "pt": "Tiếng Bồ Đào Nha",
}


class AutoDubbingOptions:
    """Bundle of user choices for the one-click flow."""

    def __init__(
        self,
        chinese_srt_path: str = "",
        import_vi_srt: bool = False,
        vi_srt_path: str = "",
        asr_model: str = "small",
        asr_device: str = "auto",
        source_language: str = "auto",
        translation_engine: str = "google",
        translation_style: str = "Natural Vietnamese",
        custom_context: str = "",
        tts_engine: str = "edge",
        voice: str = "vi-VN-HoaiMyNeural",
        speed: float = 1.0,
        do_dubbing: bool = True,
        burn_subtitle: bool = True,
        keep_original_volume: float = 0.0,   # 0.0 = mute original, 0.2 = 20%
        fit_timeline: bool = True,           # auto speed-up to remove drift
        max_fit_speed: float = 2.5,          # cap so lines fit their slot (up to ~2.5x)
        blur_regions: list | None = None,    # manual blur regions (BlurRegion)
        auto_blur_subtitle: bool = False,    # auto-blur the bottom subtitle band
        sub_font_size: int | None = None,    # override VI subtitle font size
        sub_style: dict | None = None,        # full subtitle style override (overrides font size)
        word_by_word: bool = False,           # TikTok-style: reveal one word at a time
        preset: RenderPreset | None = None,
    ) -> None:
        self.chinese_srt_path = chinese_srt_path
        self.import_vi_srt = import_vi_srt
        self.vi_srt_path = vi_srt_path
        self.asr_model = asr_model
        self.asr_device = asr_device
        self.source_language = source_language
        self.translation_engine = translation_engine
        self.translation_style = translation_style
        self.custom_context = custom_context
        self.tts_engine = tts_engine
        self.voice = voice
        self.speed = speed
        self.do_dubbing = do_dubbing
        self.burn_subtitle = burn_subtitle
        self.keep_original_volume = keep_original_volume
        self.fit_timeline = fit_timeline
        self.max_fit_speed = max_fit_speed
        self.blur_regions = blur_regions or []
        self.auto_blur_subtitle = auto_blur_subtitle
        self.sub_font_size = sub_font_size
        self.sub_style = sub_style
        self.word_by_word = word_by_word
        self.preset = preset or RenderPreset()


class AutoDubbingService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()
        self.media = MediaInfoService(self.config)
        self.ffmpeg = FFmpegService(self.config)
        self.render = RenderService(self.config)

    def run(self, ctx, project: Project, opts: AutoDubbingOptions) -> str:
        """Execute the full pipeline. Returns the final output video path."""
        project.ensure_layout()
        job_id = project.id

        def step(pct: float, msg: str, status: JobStatus | None = None) -> None:
            ctx.raise_if_cancelled()
            ctx.progress(pct, msg)
            ctx.log(msg)
            if status:
                db.update_job_status(job_id, status.value, pct, msg)

        if not self.ffmpeg.check_ffmpeg_available():
            raise RuntimeError("FFmpeg not found. Set its path in Settings.")

        # 1. media info
        step(2, "Reading media info", JobStatus.IMPORTING)
        info = self.media.get_media_info(project.source_video)
        duration = info.duration

        # 2. extract audio
        step(5, "Extracting audio", JobStatus.EXTRACTING_AUDIO)
        audio_wav = str(project.subdir("audio") / "source.wav")
        self.ffmpeg.extract_audio(
            project.source_video, audio_wav, duration,
            lambda p, m: ctx.progress(5 + p * 0.05, m),
        )

        # 3. Load Chinese SRT
        step(10, "Loading Chinese SRT", JobStatus.TRANSCRIBING)
        if not opts.chinese_srt_path or not Path(opts.chinese_srt_path).exists():
            raise RuntimeError(f"CapCut Chinese SRT file not found: {opts.chinese_srt_path}")

        segments = srt_utils.load_subtitle_file(opts.chinese_srt_path)
        if not segments:
            raise RuntimeError("Empty or invalid Chinese SRT file.")

        detected = "zh"
        project.source_language = detected
        db.create_project(project)

        srt_utils.save_srt(segments, str(project.subdir("subtitles") / "source.srt"), use_vietnamese=False)
        db.save_segments(project.id, segments)
        step(42, f"Loaded {len(segments)} Chinese segments from CapCut SRT.")

        # 4. translate or load Vietnamese SRT
        if opts.import_vi_srt:
            step(45, "Loading Vietnamese SRT", JobStatus.TRANSLATING)
            if not opts.vi_srt_path or not Path(opts.vi_srt_path).exists():
                raise RuntimeError(f"Vietnamese SRT file not found: {opts.vi_srt_path}")
            vi_segments = srt_utils.load_subtitle_file(opts.vi_srt_path)
            if not vi_segments:
                raise RuntimeError("Empty or invalid Vietnamese SRT file.")

            vi_by_idx = {s.index: s.source_text for s in vi_segments}
            for seg in segments:
                vi_text = vi_by_idx.get(seg.index, "")
                if not vi_text:
                    if seg.index - 1 < len(vi_segments):
                        vi_text = vi_segments[seg.index - 1].source_text
                seg.vi_text = vi_text
                seg.status = "translated"
        else:
            step(45, f"Translating to Vietnamese ({opts.translation_engine})",
                 JobStatus.TRANSLATING)
            provider = get_provider(opts.translation_engine, self.config)
            provider.translate_segments(
                segments, detected, "vi", opts.translation_style,
                progress_cb=lambda p, m: ctx.progress(45 + p * 0.15, f"Translating: {m}"),
                custom_context=opts.custom_context,
            )

        SubtitleService.fix_overlaps(segments)
        db.save_segments(project.id, segments)
        vi_srt = str(project.subdir("subtitles") / "vi.srt")
        srt_utils.save_srt(segments, vi_srt, use_vietnamese=True)
        step(60, "Subtitles ready")

        # 5. TTS dubbing audio (optional)
        dub_audio: str | None = None
        if opts.do_dubbing:
            step(62, f"Generating Vietnamese voice ({opts.tts_engine})",
                 JobStatus.TTS_GENERATING)
            tts = get_tts_provider(opts.tts_engine, self.config)
            ok, msg = tts.is_available()
            if not ok:
                raise RuntimeError(f"TTS unavailable: {msg}")
            voice_map = {"": opts.voice}
            clips = tts.synthesize_segments(
                segments, voice_map, str(project.subdir("tts")), opts.speed,
                lambda p, m: ctx.progress(62 + p * 0.18, f"Voice: {m}"),
            )
            step(80, "Assembling dubbing timeline")
            dub_track = str(project.subdir("tts") / "dub.wav")
            TTSAssembler(self.config).assemble(
                segments, clips, dub_track, duration,
                fit_timeline=opts.fit_timeline, max_speed=opts.max_fit_speed,
            )
            dub_audio = self._mix_with_original(
                project, dub_track, audio_wav, opts.keep_original_volume
            )

        # 6. render final
        step(85, "Rendering final video", JobStatus.RENDERING)
        preset = opts.preset
        preset.burn_subtitle = opts.burn_subtitle

        # Collect blur regions: manual ones from the UI/DB + an optional auto
        # band over the bottom of the frame to hide burned-in source subtitles.
        regions = list(opts.blur_regions) if opts.blur_regions else db.load_blur_regions(project.id)
        if opts.auto_blur_subtitle:
            regions = regions + [self._subtitle_band_region(info.width, info.height)]

        # Full custom style (from preview dialog) wins; else just a font-size bump.
        if opts.sub_style:
            style_override = dict(opts.sub_style)
        elif opts.sub_font_size:
            style_override = {"font_size": opts.sub_font_size}
        else:
            style_override = None

        # Build an ASS file with the real video resolution so font size and
        # margins are TRUE pixels (matches the preview, no vertical wrapping).
        ass_path = None
        if opts.burn_subtitle:
            from utils import ass_utils
            base_style = dict(self.config.get("subtitle_style", {}))
            if style_override:
                base_style.update({k: v for k, v in style_override.items() if v is not None})
            ass_path = str(project.subdir("subtitles") / "vi.ass")
            # VI output is space-delimited, so word_by_word splits on spaces.
            ass_utils.save_ass(segments, ass_path, base_style,
                               info.width or 1920, info.height or 1080,
                               use_vietnamese=True,
                               word_by_word=opts.word_by_word)

        out_path = str(project.subdir("render") / f"{project.id}_dubbed.{preset.output_format}")
        self.render.render(
            video_path=project.source_video, output_path=out_path, preset=preset,
            ass_path=ass_path,
            blur_regions=regions or None,
            audio_path=dub_audio,
            total_duration=duration,
            progress_cb=lambda p, m: ctx.progress(85 + p * 0.15, f"Rendering: {m}"),
        )

        db.update_job_status(job_id, JobStatus.COMPLETED.value, 100, "Completed")
        step(100, f"Done -> {out_path}")
        return out_path

    def _subtitle_band_region(self, width: int, height: int):
        """A blur band over the lower ~22% of the frame, where burned-in source
        subtitles usually sit. Uses video pixel coordinates."""
        from models.blur_region import BlurRegion
        w = width or 1920
        h = height or 1080
        band_h = int(h * 0.22)
        return BlurRegion(
            x=int(w * 0.05), y=h - band_h - int(h * 0.04),
            width=int(w * 0.90), height=band_h,
            start_time=0.0, end_time=0.0,  # whole video
            type="subtitle", effect="blur", strength=14,
        )

    def _mix_with_original(self, project: Project, dub_track: str, original_wav: str,
                           keep_volume: float) -> str:
        """Optionally mix the dub over the original audio at a low volume."""
        if keep_volume <= 0:
            return dub_track  # pure dub, original muted
        mixed = str(project.subdir("tts") / "dub_mixed.wav")
        cmd = [
            self.ffmpeg.ffmpeg, "-y",
            "-i", dub_track, "-i", original_wav,
            "-filter_complex",
            f"[1:a]volume={keep_volume}[bg];[0:a][bg]amix=inputs=2:duration=longest:normalize=0[out]",
            "-map", "[out]", "-acodec", "pcm_s16le", "-ar", "44100", mixed,
        ]
        self.ffmpeg._run(cmd)
        return mixed

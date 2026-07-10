"""Media metadata extraction via ffprobe (JSON output)."""
from __future__ import annotations

import json

from core.app_config import AppConfig
from core.logger import get_logger
from models.video_job import MediaInfo
from services.ffmpeg_service import FFmpegService

logger = get_logger(__name__)


def _parse_fraction(value: str) -> float:
    """Parse '30000/1001' style fractions into a float."""
    try:
        if "/" in value:
            num, den = value.split("/")
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(value)
    except (ValueError, ZeroDivisionError):
        return 0.0


class MediaInfoService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()
        self.ffmpeg = FFmpegService(self.config)

    def get_media_info(self, video_path: str) -> MediaInfo:
        cmd = [
            self.config.ffprobe_path(),
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]
        result = self.ffmpeg.run_raw(cmd)
        if result.returncode != 0:
            logger.error("ffprobe failed: %s", result.stderr)
            raise RuntimeError(f"ffprobe failed for {video_path}")

        data = json.loads(result.stdout or "{}")
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        info = MediaInfo()
        info.duration = float(fmt.get("duration", 0.0) or 0.0)
        info.bitrate = int(fmt.get("bit_rate", 0) or 0)

        sub_streams: list[str] = []
        for st in streams:
            codec_type = st.get("codec_type")
            if codec_type == "video" and not info.video_codec:
                info.video_codec = st.get("codec_name", "")
                info.width = int(st.get("width", 0) or 0)
                info.height = int(st.get("height", 0) or 0)
                info.fps = _parse_fraction(st.get("avg_frame_rate", "0") or "0") \
                    or _parse_fraction(st.get("r_frame_rate", "0") or "0")
            elif codec_type == "audio":
                info.has_audio = True
                if not info.audio_codec:
                    info.audio_codec = st.get("codec_name", "")
            elif codec_type == "subtitle":
                lang = st.get("tags", {}).get("language", f"stream_{st.get('index')}")
                sub_streams.append(str(lang))

        info.subtitle_streams = sub_streams
        return info

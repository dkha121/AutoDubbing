"""Application-wide constants and enums."""
from __future__ import annotations

from enum import Enum

APP_NAME = "Local Video Dubbing Studio"
APP_VERSION = "0.1.0"

SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm")

# faster-whisper model sizes
ASR_MODELS = ("tiny", "base", "small", "medium", "large-v3")

# Translation engines
TRANSLATION_ENGINES = ("router", "google", "local", "openai", "gemini", "hybrid")

TRANSLATION_STYLES = (
    "Accurate",
    "Natural Vietnamese",
    "TikTok/Reels",
    "Movie Review",
    "Storytelling",
    "Formal",
    "Funny",
    "Dubbing Script",
)

# TTS engines
TTS_ENGINES = ("edge", "voxcpm", "piper")

# Vietnamese Edge-TTS neural voices (free, online)
EDGE_VI_VOICES = {
    "Female - Hoài My": "vi-VN-HoaiMyNeural",
    "Male - Nam Minh": "vi-VN-NamMinhNeural",
}

# Render encoders
CPU_ENCODERS = ("libx264", "libx265")
GPU_ENCODERS = ("h264_nvenc", "hevc_nvenc")

OUTPUT_FORMATS = ("mp4", "mkv")


class JobStatus(str, Enum):
    PENDING = "pending"
    IMPORTING = "importing"
    EXTRACTING_AUDIO = "extracting_audio"
    DETECTING_LANGUAGE = "detecting_language"
    TRANSCRIBING = "transcribing"
    TRANSLATING = "translating"
    TTS_GENERATING = "tts_generating"
    BLURRING = "blurring"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BlurEffect(str, Enum):
    BLUR = "blur"
    MOSAIC = "mosaic"
    FROSTED = "frosted"      # blur + lớp phủ bán trong suốt (kính mờ)
    BLACK_BOX = "black_box"
    DELOGO = "delogo"


class BlurRegionType(str, Enum):
    SUBTITLE = "subtitle"
    LOGO = "logo"
    WATERMARK = "watermark"


# Render aspect presets -> (width, height) or None for original
RENDER_PRESETS = {
    "Original": None,
    "YouTube 16:9 (1920x1080)": (1920, 1080),
    "TikTok/Reels 9:16 (1080x1920)": (1080, 1920),
    "720p (1280x720)": (1280, 720),
}

# Subdirectories created inside each project folder
PROJECT_SUBDIRS = ("original", "audio", "subtitles", "tts", "render", "temp")

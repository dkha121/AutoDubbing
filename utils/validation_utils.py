"""Validation helpers used across services and UI."""
from __future__ import annotations

import shutil
from pathlib import Path

from core.constants import SUPPORTED_VIDEO_EXTENSIONS


def is_supported_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def file_exists(path: str | Path) -> bool:
    return Path(path).is_file()


def binary_available(name_or_path: str) -> bool:
    """Return True if a binary is on PATH or is an existing file."""
    if shutil.which(name_or_path):
        return True
    return Path(name_or_path).is_file()


def validate_blur_region(x: int, y: int, w: int, h: int) -> bool:
    return w > 0 and h > 0 and x >= 0 and y >= 0


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))

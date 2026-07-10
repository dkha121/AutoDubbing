"""Time conversion helpers for subtitles (seconds <-> SRT/VTT timestamps)."""
from __future__ import annotations


def seconds_to_srt(seconds: float) -> str:
    """Convert seconds (float) to an SRT timestamp 'HH:MM:SS,mmm'."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def seconds_to_vtt(seconds: float) -> str:
    """Convert seconds to a WebVTT timestamp 'HH:MM:SS.mmm'."""
    return seconds_to_srt(seconds).replace(",", ".")


def srt_to_seconds(timestamp: str) -> float:
    """Parse an SRT or VTT timestamp into seconds (float).

    Accepts 'HH:MM:SS,mmm', 'HH:MM:SS.mmm', or 'MM:SS,mmm'.
    """
    ts = timestamp.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        hours, minutes, sec = parts
    elif len(parts) == 2:
        hours, minutes, sec = "0", parts[0], parts[1]
    else:
        raise ValueError(f"Invalid timestamp: {timestamp!r}")
    return int(hours) * 3600 + int(minutes) * 60 + float(sec)


def format_duration(seconds: float) -> str:
    """Human-readable duration 'H:MM:SS' for UI display."""
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

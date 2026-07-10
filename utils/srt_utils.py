"""SRT/VTT/JSON serialization for subtitle segments.

Uses the `srt` library when available for robust parsing, but provides a
pure-Python fallback parser so the app works even before deps are installed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from models.subtitle_segment import SubtitleSegment
from utils.time_utils import seconds_to_srt, seconds_to_vtt, srt_to_seconds

_BLOCK_SEP = re.compile(r"\n\s*\n")
_TIME_LINE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)


def segments_to_srt(segments: list[SubtitleSegment], use_vietnamese: bool = True) -> str:
    """Serialize segments to SRT text."""
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        text = seg.display_text() if use_vietnamese else seg.source_text
        lines.append(str(i))
        lines.append(f"{seconds_to_srt(seg.start)} --> {seconds_to_srt(seg.end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def segments_to_vtt(segments: list[SubtitleSegment], use_vietnamese: bool = True) -> str:
    """Serialize segments to WebVTT text."""
    out = ["WEBVTT", ""]
    for seg in segments:
        text = seg.display_text() if use_vietnamese else seg.source_text
        out.append(f"{seconds_to_vtt(seg.start)} --> {seconds_to_vtt(seg.end)}")
        out.append(text)
        out.append("")
    return "\n".join(out).strip() + "\n"


def segments_to_json(segments: list[SubtitleSegment]) -> str:
    return json.dumps([s.to_dict() for s in segments], ensure_ascii=False, indent=2)


def parse_srt(text: str) -> list[SubtitleSegment]:
    """Parse SRT text into segments using a tolerant pure-Python parser."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    segments: list[SubtitleSegment] = []
    index = 0
    for block in _BLOCK_SEP.split(text.strip()):
        block = block.strip()
        if not block:
            continue
        block_lines = block.split("\n")
        time_match = None
        time_line_idx = -1
        for j, line in enumerate(block_lines):
            m = _TIME_LINE.search(line)
            if m:
                time_match = m
                time_line_idx = j
                break
        if not time_match:
            continue
        index += 1
        start = srt_to_seconds(time_match.group(1))
        end = srt_to_seconds(time_match.group(2))
        body = "\n".join(block_lines[time_line_idx + 1:]).strip()
        segments.append(
            SubtitleSegment(index=index, start=start, end=end, source_text=body)
        )
    return segments


def parse_vtt(text: str) -> list[SubtitleSegment]:
    """Parse WebVTT. The same block logic works after stripping the header."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    text = re.sub(r"^WEBVTT.*?\n", "", text, count=1, flags=re.DOTALL)
    return parse_srt(text)


def load_subtitle_file(path: str | Path) -> list[SubtitleSegment]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".vtt":
        return parse_vtt(text)
    if p.suffix.lower() == ".json":
        return [SubtitleSegment.from_dict(d) for d in json.loads(text)]
    return parse_srt(text)


def save_srt(segments: list[SubtitleSegment], path: str | Path, use_vietnamese: bool = True) -> None:
    Path(path).write_text(segments_to_srt(segments, use_vietnamese), encoding="utf-8")


def save_vtt(segments: list[SubtitleSegment], path: str | Path, use_vietnamese: bool = True) -> None:
    Path(path).write_text(segments_to_vtt(segments, use_vietnamese), encoding="utf-8")


def save_json(segments: list[SubtitleSegment], path: str | Path) -> None:
    Path(path).write_text(segments_to_json(segments), encoding="utf-8")

"""Subtitle editing operations (timing, splitting, merging, line wrapping).

These are pure list operations over SubtitleSegment so they are easy to test
and reuse from both the editor UI and batch pipeline.
"""
from __future__ import annotations

import textwrap

from core.logger import get_logger
from models.subtitle_segment import SubtitleSegment
from utils import srt_utils

logger = get_logger(__name__)


class SubtitleService:
    """Stateless helpers operating on lists of SubtitleSegment."""

    @staticmethod
    def reindex(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
        for i, seg in enumerate(segments, start=1):
            seg.index = i
        return segments

    @staticmethod
    def shift_timing(segments: list[SubtitleSegment], offset: float) -> list[SubtitleSegment]:
        """Shift all segments by `offset` seconds (negatives clamped at 0)."""
        for seg in segments:
            seg.start = max(0.0, seg.start + offset)
            seg.end = max(seg.start, seg.end + offset)
        return segments

    @staticmethod
    def fix_overlaps(segments: list[SubtitleSegment], min_gap: float = 0.001) -> list[SubtitleSegment]:
        """Ensure each segment starts at/after the previous one ends."""
        ordered = sorted(segments, key=lambda s: s.start)
        for prev, cur in zip(ordered, ordered[1:]):
            if cur.start < prev.end:
                cur.start = prev.end + min_gap
            if cur.end < cur.start:
                cur.end = cur.start + min_gap
        return SubtitleService.reindex(ordered)

    @staticmethod
    def merge(segments: list[SubtitleSegment], i: int, j: int) -> list[SubtitleSegment]:
        """Merge segment at index j into i (0-based list positions)."""
        if not (0 <= i < len(segments)) or not (0 <= j < len(segments)) or i == j:
            return segments
        a, b = sorted((i, j))
        first, second = segments[a], segments[b]
        first.end = max(first.end, second.end)
        first.source_text = f"{first.source_text} {second.source_text}".strip()
        first.vi_text = f"{first.vi_text} {second.vi_text}".strip()
        del segments[b]
        return SubtitleService.reindex(segments)

    @staticmethod
    def split(segments: list[SubtitleSegment], pos: int, at_fraction: float = 0.5) -> list[SubtitleSegment]:
        """Split the segment at list position `pos` into two halves in time."""
        if not (0 <= pos < len(segments)):
            return segments
        seg = segments[pos]
        mid = seg.start + seg.duration * at_fraction
        new = SubtitleSegment(
            index=seg.index + 1, start=mid, end=seg.end,
            source_text="", vi_text="", speaker=seg.speaker, voice=seg.voice,
        )
        seg.end = mid
        segments.insert(pos + 1, new)
        return SubtitleService.reindex(segments)

    @staticmethod
    def wrap_long_lines(segments: list[SubtitleSegment], max_chars: int = 42,
                        use_vietnamese: bool = True) -> list[SubtitleSegment]:
        """Balance long text across lines WITHOUT ever dropping words.

        Previously this used textwrap.fill(max_lines=2, placeholder='…') which
        TRUNCATED any text longer than two lines — losing the end of long
        sentences. We now wrap with no max_lines so every word is preserved.
        Rendering uses an ASS file with the real PlayResY, so libass also
        re-wraps to fit the frame width on top of this.
        """
        for seg in segments:
            text = seg.vi_text if use_vietnamese else seg.source_text
            if text and len(text) > max_chars:
                # wrap onto as many lines as needed; never break a word, never drop text
                wrapped = textwrap.fill(text, width=max_chars,
                                        break_long_words=False,
                                        break_on_hyphens=False)
                if use_vietnamese:
                    seg.vi_text = wrapped
                else:
                    seg.source_text = wrapped
        return segments

    # ---- IO passthrough ----------------------------------------------
    @staticmethod
    def load(path: str) -> list[SubtitleSegment]:
        return srt_utils.load_subtitle_file(path)

    @staticmethod
    def save_srt(segments: list[SubtitleSegment], path: str, use_vietnamese: bool = True) -> None:
        srt_utils.save_srt(segments, path, use_vietnamese)

    @staticmethod
    def save_vtt(segments: list[SubtitleSegment], path: str, use_vietnamese: bool = True) -> None:
        srt_utils.save_vtt(segments, path, use_vietnamese)

    @staticmethod
    def save_json(segments: list[SubtitleSegment], path: str) -> None:
        srt_utils.save_json(segments, path)

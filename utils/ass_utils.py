"""SRT -> ASS conversion with explicit play resolution.

Burning subtitles from an SRT via FFmpeg's `subtitles=` filter forces libass to
use its default canvas (PlayResY=288) and then scales the font up to the real
video height. For a 1080p/1920p video that magnifies a "size 20" font several
times, which also makes lines wrap word-by-word into a vertical column.

Rendering from an ASS file whose [Script Info] declares PlayResX/PlayResY equal
to the real video size makes FontSize and margins behave as true pixels — so the
burned result matches the WYSIWYG preview.
"""
from __future__ import annotations

from pathlib import Path

from models.subtitle_segment import SubtitleSegment
from utils.time_utils import seconds_to_srt


def _ass_time(seconds: float) -> str:
    """ASS timestamp: H:MM:SS.cc (centiseconds)."""
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cc = divmod(rem, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cc:02d}"


def _ass_text(text: str) -> str:
    """Escape subtitle text for an ASS dialogue line.

    Any stray newlines are turned into spaces (NOT hard '\\N' breaks) so libass
    re-wraps the line to fit the frame on its own, never splitting mid-phrase.
    """
    t = (text or "").replace("\\", "\\\\").replace("\r", " ").replace("\n", " ")
    while "  " in t:
        t = t.replace("  ", " ")
    return t.strip()


def build_ass(segments: list[SubtitleSegment], style: dict, video_w: int,
              video_h: int, use_vietnamese: bool = True) -> str:
    """Build a full ASS document string.

    `style` keys mirror utils.subtitle_style_utils.build_style() output:
    font, font_size, primary_color, outline_color, back_color, outline, shadow,
    border_style, bold, alignment, margin_v, margin_l, margin_r.
    Colours are already in ASS &HAABBGGRR form.
    """
    header = _ass_header(style, video_w, video_h)

    lines: list[str] = []
    for seg in segments:
        text = seg.display_text() if use_vietnamese else seg.source_text
        if not text.strip():
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Default,,"
            f"0,0,0,,{_ass_text(text)}"
        )
    return header + "\n".join(lines) + "\n"


def _split_words(text: str, lang_no_space: bool = False) -> list[str]:
    """Split a line into the units to reveal one at a time.

    For space-delimited languages (incl. Vietnamese, where each syllable is a
    space-separated token) we split on whitespace. For scripts without spaces
    (zh/ja/...) we fall back to one character per unit.
    """
    text = (text or "").strip()
    if not text:
        return []
    if lang_no_space:
        return [c for c in text if not c.isspace()]
    return text.split()


def build_ass_words(segments: list[SubtitleSegment], style: dict, video_w: int,
                    video_h: int, use_vietnamese: bool = True,
                    lang_no_space: bool = False, min_word_sec: float = 0.12) -> str:
    """Build an ASS where each word/syllable shows on its own (TikTok caption).

    Only the currently-spoken word is on screen. Since translated text has no
    per-word timing, each segment's [start, end] window is divided across its
    words proportionally to word length, so longer words linger longer.
    """
    header = _ass_header(style, video_w, video_h)

    lines: list[str] = []
    for seg in segments:
        text = seg.display_text() if use_vietnamese else seg.source_text
        words = _split_words(text, lang_no_space)
        if not words:
            continue
        span = max(0.0, seg.end - seg.start)
        weights = [max(1, len(w)) for w in words]
        total_w = sum(weights)
        # Each word gets a slice proportional to its length, with a small floor
        # so very short words are still readable.
        t = seg.start
        for w, wt in zip(words, weights):
            dur = span * (wt / total_w) if total_w else span
            if dur < min_word_sec:
                dur = min_word_sec
            w_start = t
            w_end = min(seg.end, t + dur) if seg.end > seg.start else t + dur
            if w_end <= w_start:
                w_end = w_start + min_word_sec
            lines.append(
                f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Default,,"
                f"0,0,0,,{_ass_text(w)}"
            )
            t = w_end
    return header + "\n".join(lines) + "\n"


def _ass_header(style: dict, video_w: int, video_h: int) -> str:
    font = style.get("font", "Arial")
    size = int(style.get("font_size", 24))
    primary = style.get("primary_color", "&H00FFFFFF")
    outline_c = style.get("outline_color", "&H00000000")
    back_c = style.get("back_color", "&H00000000")
    outline = int(style.get("outline", 2))
    shadow = int(style.get("shadow", 0))
    border_style = int(style.get("border_style", 1))
    bold = -1 if int(style.get("bold", 0)) else 0
    alignment = int(style.get("alignment", 2))
    margin_l = int(style.get("margin_l", 20))
    margin_r = int(style.get("margin_r", 20))
    margin_v = int(style.get("margin_v", 30))

    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {int(video_w)}\n"
        f"PlayResY: {int(video_h)}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{primary},&H000000FF,{outline_c},{back_c},"
        f"{bold},0,0,0,100,100,0,0,{border_style},{outline},{shadow},"
        f"{alignment},{margin_l},{margin_r},{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )


def save_ass(segments: list[SubtitleSegment], path: str | Path, style: dict,
             video_w: int, video_h: int, use_vietnamese: bool = True,
             word_by_word: bool = False, lang_no_space: bool = False) -> str:
    builder = build_ass_words if word_by_word else build_ass
    kwargs = {}
    if word_by_word:
        kwargs["lang_no_space"] = lang_no_space
    Path(path).write_text(
        builder(segments, style, video_w, video_h, use_vietnamese, **kwargs),
        encoding="utf-8",
    )
    return str(path)

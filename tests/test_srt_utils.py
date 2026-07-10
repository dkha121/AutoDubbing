"""Tests for srt_utils parsing and serialization."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.subtitle_segment import SubtitleSegment  # noqa: E402
from utils import srt_utils  # noqa: E402

SAMPLE_SRT = """1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:03,500 --> 00:00:05,000
Second line
across two rows
"""

SAMPLE_VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
Hello world

00:00:03.500 --> 00:00:05.000
Second line
"""


def test_parse_srt_count_and_text():
    segs = srt_utils.parse_srt(SAMPLE_SRT)
    assert len(segs) == 2
    assert segs[0].source_text == "Hello world"
    assert segs[0].start == 1.0
    assert segs[0].end == 3.0
    assert "across two rows" in segs[1].source_text


def test_parse_srt_handles_bom_and_crlf():
    text = "﻿" + SAMPLE_SRT.replace("\n", "\r\n")
    segs = srt_utils.parse_srt(text)
    assert len(segs) == 2


def test_parse_vtt():
    segs = srt_utils.parse_vtt(SAMPLE_VTT)
    assert len(segs) == 2
    assert segs[1].start == 3.5


def test_roundtrip_srt():
    segs = srt_utils.parse_srt(SAMPLE_SRT)
    out = srt_utils.segments_to_srt(segs, use_vietnamese=False)
    reparsed = srt_utils.parse_srt(out)
    assert len(reparsed) == 2
    assert reparsed[0].source_text == "Hello world"


def test_segments_to_json_and_back():
    segs = [SubtitleSegment(index=1, start=0.0, end=1.0, source_text="hi", vi_text="chào")]
    js = srt_utils.segments_to_json(segs)
    import json
    data = json.loads(js)
    assert data[0]["vi_text"] == "chào"


def test_display_text_prefers_vietnamese():
    seg = SubtitleSegment(index=1, start=0, end=1, source_text="hi", vi_text="chào")
    assert seg.display_text() == "chào"
    seg2 = SubtitleSegment(index=2, start=0, end=1, source_text="hi", vi_text="")
    assert seg2.display_text() == "hi"

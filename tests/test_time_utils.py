"""Tests for time_utils."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.time_utils import (  # noqa: E402
    format_duration, seconds_to_srt, seconds_to_vtt, srt_to_seconds,
)


def test_seconds_to_srt_basic():
    assert seconds_to_srt(0) == "00:00:00,000"
    assert seconds_to_srt(1.5) == "00:00:01,500"
    assert seconds_to_srt(3661.123) == "01:01:01,123"


def test_seconds_to_srt_negative_clamped():
    assert seconds_to_srt(-5) == "00:00:00,000"


def test_seconds_to_vtt_uses_dot():
    assert seconds_to_vtt(1.5) == "00:00:01.500"


def test_srt_to_seconds_roundtrip():
    for value in (0.0, 1.5, 61.25, 3661.123):
        ts = seconds_to_srt(value)
        assert abs(srt_to_seconds(ts) - value) < 0.002


def test_srt_to_seconds_accepts_dot_and_comma():
    assert abs(srt_to_seconds("00:00:01.500") - 1.5) < 1e-6
    assert abs(srt_to_seconds("00:00:01,500") - 1.5) < 1e-6


def test_srt_to_seconds_mmss():
    assert abs(srt_to_seconds("01:30,000") - 90.0) < 1e-6


def test_format_duration():
    assert format_duration(0) == "0:00"
    assert format_duration(65) == "1:05"
    assert format_duration(3661) == "1:01:01"

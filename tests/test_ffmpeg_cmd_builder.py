"""Tests for ffmpeg_cmd_builder pure functions."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.blur_region import BlurRegion  # noqa: E402
from utils import ffmpeg_cmd_builder as cb  # noqa: E402


def test_extract_audio_cmd():
    cmd = cb.build_extract_audio_cmd("ffmpeg", "in.mp4", "out.wav")
    assert cmd[0] == "ffmpeg"
    assert "in.mp4" in cmd
    assert "out.wav" in cmd
    assert "-ar" in cmd and "16000" in cmd
    assert "-ac" in cmd and "1" in cmd


def test_mute_audio_cmd():
    cmd = cb.build_mute_audio_cmd("ffmpeg", "in.mp4", "out.mp4")
    assert "-an" in cmd
    assert "copy" in cmd


def test_merge_video_audio_cmd():
    cmd = cb.build_merge_video_audio_cmd("ffmpeg", "v.mp4", "a.wav", "o.mp4")
    assert "0:v:0" in cmd
    assert "1:a:0" in cmd
    assert "-shortest" in cmd


def test_subtitle_style_string():
    style = {"font": "Arial", "font_size": 24, "outline": 2}
    s = cb.build_subtitle_style(style)
    assert "FontName=Arial" in s
    assert "FontSize=24" in s
    assert "Outline=2" in s


def test_burn_subtitle_cmd_has_filter():
    cmd = cb.build_burn_subtitle_cmd("ffmpeg", "in.mp4", "subs.srt", "out.mp4",
                                     style={"font_size": 20})
    vf_idx = cmd.index("-vf")
    assert "subtitles=" in cmd[vf_idx + 1]
    assert "force_style=" in cmd[vf_idx + 1]


def test_quality_args_cpu_vs_nvenc():
    cpu = cb._video_quality_args("libx264", 20, "medium")
    assert "-crf" in cpu and "20" in cpu
    gpu = cb._video_quality_args("h264_nvenc", 20, "medium")
    assert "-cq" in gpu


def test_blur_filter_box_is_inplace():
    """build_blur_filter only handles in-place ops (black_box/delogo); blur and
    mosaic are NOT here — they go through build_region_blur_complex."""
    regions = [
        BlurRegion(x=10, y=20, width=100, height=40, effect="black_box", start_time=1, end_time=5),
    ]
    vf = cb.build_blur_filter(regions)
    assert "drawbox=" in vf
    assert "between(t,1" in vf  # time-gated region


def test_region_blur_complex_blurs_only_region():
    regions = [
        BlurRegion(x=0, y=0, width=50, height=50, effect="blur", strength=8),
    ]
    graph, label = cb.build_region_blur_complex(regions)
    assert "boxblur=" in graph
    assert "crop=50:50:0:0" in graph
    assert "overlay=" in graph


def test_region_blur_complex_frosted_has_veil():
    regions = [
        BlurRegion(x=0, y=0, width=200, height=80, effect="frosted", strength=10),
    ]
    graph, label = cb.build_region_blur_complex(regions)
    assert "boxblur=" in graph
    # frosted lays a semi-transparent veil over the blurred crop
    assert "drawbox=" in graph and "@0.35" in graph


def test_render_cmd_with_scale_and_audio():
    cmd = cb.build_render_cmd(
        "ffmpeg", "in.mp4", "out.mp4", vf_filters="boxblur=5",
        width=1920, height=1080, fps=30, audio_path="a.wav",
    )
    vf_idx = cmd.index("-vf")
    assert "scale=1920:1080" in cmd[vf_idx + 1]
    assert "boxblur=5" in cmd[vf_idx + 1]
    assert "-r" in cmd and "30" in cmd
    assert "1:a:0" in cmd


def test_render_cmd_no_audio_uses_single_input():
    cmd = cb.build_render_cmd("ffmpeg", "in.mp4", "out.mp4")
    assert cmd.count("-i") == 1

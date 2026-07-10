"""Pure functions that build FFmpeg argument lists.

Kept free of side effects so they are easy to unit-test. The ffmpeg_service
layer is responsible for actually running these commands.
"""
from __future__ import annotations

from typing import Sequence

from models.blur_region import BlurRegion
from core.constants import BlurEffect


def build_extract_audio_cmd(
    ffmpeg: str,
    video_path: str,
    output_wav: str,
    sample_rate: int = 16000,
    channels: int = 1,
) -> list[str]:
    """Extract mono 16kHz PCM WAV (ideal input for Whisper)."""
    return [
        ffmpeg, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        output_wav,
    ]


def build_convert_wav_cmd(
    ffmpeg: str, input_path: str, output_path: str,
    sample_rate: int = 16000, channels: int = 1,
) -> list[str]:
    return [
        ffmpeg, "-y", "-i", input_path,
        "-acodec", "pcm_s16le", "-ar", str(sample_rate), "-ac", str(channels),
        output_path,
    ]


def build_mute_audio_cmd(ffmpeg: str, video_path: str, output_path: str) -> list[str]:
    return [ffmpeg, "-y", "-i", video_path, "-an", "-c:v", "copy", output_path]


def build_merge_video_audio_cmd(
    ffmpeg: str, video_path: str, audio_path: str, output_path: str,
    audio_codec: str = "aac",
) -> list[str]:
    return [
        ffmpeg, "-y",
        "-i", video_path, "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", audio_codec,
        "-shortest", output_path,
    ]


def _escape_subtitle_path(path: str) -> str:
    """Escape a path for use inside the FFmpeg 'subtitles=' filter.

    On Windows the drive colon and backslashes must be escaped.
    """
    p = path.replace("\\", "/")
    p = p.replace(":", "\\:")
    return p


def build_subtitle_style(style: dict | None) -> str:
    """Build a libass force_style string from a style dict."""
    if not style:
        return ""
    mapping = {
        "font": "FontName",
        "font_size": "FontSize",
        "primary_color": "PrimaryColour",
        "outline_color": "OutlineColour",
        "back_color": "BackColour",
        "outline": "Outline",
        "shadow": "Shadow",
        "border_style": "BorderStyle",
        "bold": "Bold",
        "alignment": "Alignment",
        "margin_v": "MarginV",
        "margin_l": "MarginL",
        "margin_r": "MarginR",
    }
    parts = [f"{ass_key}={style[k]}" for k, ass_key in mapping.items() if style.get(k) is not None]
    return ",".join(parts)


def build_burn_subtitle_cmd(
    ffmpeg: str, video_path: str, srt_path: str, output_path: str,
    style: dict | None = None, encoder: str = "libx264",
    crf: int = 20, preset: str = "medium", audio_codec: str = "aac",
) -> list[str]:
    sub_filter = f"subtitles='{_escape_subtitle_path(srt_path)}'"
    force_style = build_subtitle_style(style)
    if force_style:
        sub_filter += f":force_style='{force_style}'"
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vf", sub_filter,
        "-c:v", encoder,
    ]
    cmd += _video_quality_args(encoder, crf, preset)
    cmd += ["-c:a", audio_codec, output_path]
    return cmd


def _video_quality_args(encoder: str, crf: int, preset: str) -> list[str]:
    """Quality args differ between CPU (CRF) and NVENC (CQ) encoders."""
    if encoder.endswith("nvenc"):
        return ["-preset", "p5", "-rc", "vbr", "-cq", str(crf)]
    return ["-crf", str(crf), "-preset", preset]


def build_blur_filter(regions: Sequence[BlurRegion]) -> str:
    """Build a single -vf filter chain that applies all blur/box regions.

    Each region is gated by 'enable=between(t,start,end)' so it only affects
    its time window. Regions with end<=0 apply to the whole video.
    """
    filters: list[str] = []
    for r in regions:
        enable = ""
        if r.end_time and r.end_time > 0:
            enable = f":enable='between(t,{r.start_time},{r.end_time})'"
        x, y, w, h = int(r.x), int(r.y), int(r.width), int(r.height)
        # drawbox and delogo are inherently region-scoped (they take x/y/w/h),
        # so they can stay as simple -vf filters.
        if r.effect == BlurEffect.BLACK_BOX.value:
            filters.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color=black@1.0:t=fill{enable}")
        elif r.effect == BlurEffect.DELOGO.value:
            filters.append(f"delogo=x={x}:y={y}:w={w}:h={h}{enable}")
        # NOTE: blur/mosaic effects are NOT handled here — boxblur applies to the
        # whole frame. Region-scoped blur must use build_region_blur_complex()
        # via filter_complex (crop -> blur -> overlay).
    return ",".join(filters)


def build_region_blur_complex(
    regions: Sequence[BlurRegion], in_label: str = "0:v", out_label: str = "vout",
    extra_vf: str = "",
) -> tuple[str, str]:
    """Build a filter_complex graph that blurs ONLY the given regions.

    For each blur/mosaic region: crop that rectangle, blur the crop, then
    overlay it back at the same x/y. drawbox/delogo regions are appended as
    in-place ops. `extra_vf` (e.g. subtitles, scale) is applied after all
    blur overlays so the subtitle stays sharp on top.

    Returns (filter_complex_string, final_label). If there's nothing to do,
    returns ("", in_label).
    """
    blur_regions = [r for r in regions
                    if r.effect in (BlurEffect.BLUR.value, BlurEffect.MOSAIC.value,
                                    BlurEffect.FROSTED.value)]
    box_regions = [r for r in regions
                   if r.effect in (BlurEffect.BLACK_BOX.value, BlurEffect.DELOGO.value)]

    steps: list[str] = []
    cur = in_label  # current video stream label being chained

    for i, r in enumerate(blur_regions):
        x, y, w, h = int(r.x), int(r.y), int(r.width), int(r.height)
        if r.effect == BlurEffect.MOSAIC.value:
            # Pixelate: downscale the crop then upscale back (blocky look).
            factor = max(2, int(r.strength))
            dw, dh = max(1, w // factor), max(1, h // factor)
            crop_proc = (f"crop={w}:{h}:{x}:{y},scale={dw}:{dh}:flags=neighbor,"
                         f"scale={w}:{h}:flags=neighbor")
        elif r.effect == BlurEffect.FROSTED.value:
            # Frosted glass: heavily blur the crop, then lay a semi-transparent
            # white veil over it so the background is still faintly visible
            # (softer than an opaque box). `strength` drives the blur radius;
            # the veil opacity is fixed-ish and gentle.
            strength = max(2, int(r.strength))
            luma_max = max(1, (min(w, h) - 1) // 2)
            chroma_max = max(1, (min(w, h) // 2 - 1) // 2)
            luma_r = min(strength * 2, luma_max)
            chroma_r = min(strength * 2, chroma_max)
            crop_proc = (
                f"crop={w}:{h}:{x}:{y},"
                f"boxblur=luma_radius={luma_r}:luma_power=2"
                f":chroma_radius={chroma_r}:chroma_power=2,"
                f"drawbox=x=0:y=0:w={w}:h={h}:color=white@0.35:t=fill"
            )
        else:
            # boxblur radius must not exceed half the (sub)plane size. For
            # YUV420 the chroma plane is half-resolution, so its max radius is
            # smaller — clamp both to avoid "Invalid chroma_param radius".
            strength = max(1, int(r.strength))
            luma_max = max(1, (min(w, h) - 1) // 2)
            chroma_max = max(1, (min(w, h) // 2 - 1) // 2)
            luma_r = min(strength, luma_max)
            chroma_r = min(strength, chroma_max)
            crop_proc = (f"crop={w}:{h}:{x}:{y},"
                         f"boxblur=luma_radius={luma_r}:luma_power=2"
                         f":chroma_radius={chroma_r}:chroma_power=2")

        enable = ""
        if r.end_time and r.end_time > 0:
            enable = f":enable='between(t,{r.start_time},{r.end_time})'"

        # [cur] split into a passthrough base and a crop branch.
        base = f"b{i}"
        crop = f"c{i}"
        nxt = f"v{i}"
        steps.append(f"[{cur}]split=2[{base}][{base}src]")
        steps.append(f"[{base}src]{crop_proc}[{crop}]")
        steps.append(f"[{base}][{crop}]overlay={x}:{y}{enable}[{nxt}]")
        cur = nxt

    # In-place box/delogo ops chained after blur overlays.
    inplace: list[str] = []
    for r in box_regions:
        x, y, w, h = int(r.x), int(r.y), int(r.width), int(r.height)
        enable = ""
        if r.end_time and r.end_time > 0:
            enable = f":enable='between(t,{r.start_time},{r.end_time})'"
        if r.effect == BlurEffect.BLACK_BOX.value:
            inplace.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color=black@1.0:t=fill{enable}")
        else:
            inplace.append(f"delogo=x={x}:y={y}:w={w}:h={h}{enable}")

    tail = list(inplace)
    if extra_vf:
        tail.append(extra_vf)

    if not steps and not tail:
        return "", in_label

    if tail:
        steps.append(f"[{cur}]{','.join(tail)}[{out_label}]")
    else:
        # rename last label to out_label via a null filter
        steps.append(f"[{cur}]null[{out_label}]")

    return ";".join(steps), out_label


def build_render_cmd(
    ffmpeg: str, video_path: str, output_path: str,
    vf_filters: str = "", encoder: str = "libx264",
    crf: int = 20, preset: str = "medium",
    width: int | None = None, height: int | None = None,
    fps: int | None = None, bitrate: str | None = None,
    audio_path: str | None = None, audio_codec: str = "aac",
) -> list[str]:
    """Assemble a full render command with optional scaling, fps, filters, audio."""
    cmd = [ffmpeg, "-y", "-i", video_path]
    if audio_path:
        cmd += ["-i", audio_path]

    vf_parts = [f for f in [vf_filters] if f]
    if width and height:
        vf_parts.append(f"scale={width}:{height}")
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]

    cmd += ["-c:v", encoder]
    cmd += _video_quality_args(encoder, crf, preset)
    if fps:
        cmd += ["-r", str(fps)]
    if bitrate:
        cmd += ["-b:v", bitrate]

    if audio_path:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", audio_codec, "-shortest"]
    else:
        cmd += ["-c:a", audio_codec]

    cmd.append(output_path)
    return cmd

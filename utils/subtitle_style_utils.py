"""Subtitle style helpers: colour conversion, presets, and style-dict builder.

libass (FFmpeg `subtitles=force_style`) uses ASS colours in the form
&HAABBGGRR (alpha, blue, green, red — hex, AA=00 is fully opaque). This module
converts ordinary #RRGGBB colours to that form and provides ready-made style
presets so the UI can offer "nhiều kiểu chữ" without the user knowing ASS.
"""
from __future__ import annotations


def rgb_to_ass(hex_color: str, alpha: int = 0) -> str:
    """Convert '#RRGGBB' (or 'RRGGBB') to ASS '&HAABBGGRR'.

    alpha: 0 = opaque, 255 = fully transparent.
    """
    h = (hex_color or "").lstrip("#").strip()
    if len(h) == 8:  # already #RRGGBBAA -> take rgb
        h = h[:6]
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    aa = f"{max(0, min(255, alpha)):02X}"
    return f"&H{aa}{b}{g}{r}".upper()


def ass_to_rgb(ass_color: str) -> str:
    """Convert ASS '&HAABBGGRR' back to '#RRGGBB' for UI colour pickers."""
    s = (ass_color or "").upper().replace("&H", "").replace("&", "")
    if len(s) == 8:
        s = s[2:]  # drop alpha
    if len(s) != 6:
        return "#FFFFFF"
    b, g, r = s[0:2], s[2:4], s[4:6]
    return f"#{r}{g}{b}"


# Alignment (libass / ASS numpad layout):
#   7 8 9   (top)
#   4 5 6   (middle)
#   1 2 3   (bottom)
ALIGNMENTS = {
    "Dưới giữa": 2,
    "Dưới trái": 1,
    "Dưới phải": 3,
    "Giữa màn hình": 5,
    "Trên giữa": 8,
}

# Ready-made looks. Colours are plain hex; converted to ASS at build time.
STYLE_PRESETS = {
    "Trắng viền đen (mặc định)": {
        "primary": "#FFFFFF", "outline_color": "#000000",
        "outline": 2, "shadow": 1, "back_color": "#000000", "border_style": 1,
    },
    "Vàng viền đen": {
        "primary": "#FFE600", "outline_color": "#000000",
        "outline": 2, "shadow": 1, "back_color": "#000000", "border_style": 1,
    },
    "Trắng nền đen (hộp)": {
        "primary": "#FFFFFF", "outline_color": "#000000",
        "outline": 0, "shadow": 0, "back_color": "#000000", "border_style": 3,
    },
    "Xanh lá nổi bật": {
        "primary": "#00FF66", "outline_color": "#003300",
        "outline": 2, "shadow": 1, "back_color": "#000000", "border_style": 1,
    },
    "Hồng TikTok": {
        "primary": "#FF3DCB", "outline_color": "#FFFFFF",
        "outline": 3, "shadow": 0, "back_color": "#000000", "border_style": 1,
    },
}

COMMON_FONTS = ["Arial", "Tahoma", "Verdana", "Segoe UI", "Times New Roman", "Roboto"]


def build_style(font: str = "Arial", font_size: int = 24,
                primary: str = "#FFFFFF", outline_color: str = "#000000",
                outline: int = 2, shadow: int = 1, border_style: int = 1,
                back_color: str = "#000000",
                alignment: int = 2, margin_v: int = 30, margin_l: int = 20,
                margin_r: int = 20, bold: bool = False) -> dict:
    """Build a style dict consumed by ffmpeg_cmd_builder.build_subtitle_style().

    Keys mirror what the cmd builder maps to libass force_style fields.
    """
    return {
        "font": font,
        "font_size": int(font_size),
        "primary_color": rgb_to_ass(primary),
        "outline_color": rgb_to_ass(outline_color),
        "back_color": rgb_to_ass(back_color),
        "outline": int(outline),
        "shadow": int(shadow),
        "border_style": int(border_style),
        "alignment": int(alignment),
        "margin_v": int(margin_v),
        "margin_l": int(margin_l),
        "margin_r": int(margin_r),
        "bold": 1 if bold else 0,
    }

"""RenderPreset data model."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class RenderPreset:
    """Settings used to render the final video."""

    name: str = "Default"
    width: int | None = None       # None = keep original
    height: int | None = None
    fps: int | None = None
    encoder: str = "libx264"
    crf: int = 20
    preset: str = "medium"
    bitrate: str | None = None
    audio_codec: str = "aac"
    output_format: str = "mp4"
    burn_subtitle: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RenderPreset":
        return cls(
            name=data.get("name", "Default"),
            width=data.get("width"),
            height=data.get("height"),
            fps=data.get("fps"),
            encoder=data.get("encoder", "libx264"),
            crf=int(data.get("crf", 20)),
            preset=data.get("preset", "medium"),
            bitrate=data.get("bitrate"),
            audio_codec=data.get("audio_codec", "aac"),
            output_format=data.get("output_format", "mp4"),
            burn_subtitle=bool(data.get("burn_subtitle", True)),
        )

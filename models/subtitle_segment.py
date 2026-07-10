"""SubtitleSegment data model."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SubtitleSegment:
    """A single subtitle line with source + Vietnamese text and dubbing metadata."""

    index: int
    start: float
    end: float
    source_text: str = ""
    vi_text: str = ""
    speaker: str | None = None
    voice: str | None = None
    status: str = "new"  # new | translated | edited | tts_done

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubtitleSegment":
        return cls(
            index=int(data["index"]),
            start=float(data["start"]),
            end=float(data["end"]),
            source_text=data.get("source_text", ""),
            vi_text=data.get("vi_text", ""),
            speaker=data.get("speaker"),
            voice=data.get("voice"),
            status=data.get("status", "new"),
        )

    def display_text(self) -> str:
        """Text used for rendering subtitles (Vietnamese if present)."""
        return self.vi_text.strip() or self.source_text.strip()

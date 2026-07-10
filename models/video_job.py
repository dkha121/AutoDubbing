"""VideoJob data model + media info."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from core.constants import JobStatus


@dataclass
class MediaInfo:
    """Parsed ffprobe output for a media file."""

    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bitrate: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    has_audio: bool = False
    subtitle_streams: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MediaInfo":
        return cls(
            duration=float(data.get("duration", 0.0)),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            fps=float(data.get("fps", 0.0)),
            bitrate=int(data.get("bitrate", 0)),
            video_codec=data.get("video_codec", ""),
            audio_codec=data.get("audio_codec", ""),
            has_audio=bool(data.get("has_audio", False)),
            subtitle_streams=list(data.get("subtitle_streams", [])),
        )


@dataclass
class VideoJob:
    """A unit of work in the batch queue, tied to a project."""

    id: str = ""
    project_id: str = ""
    source_video: str = ""
    status: str = JobStatus.PENDING.value
    progress: float = 0.0
    message: str = ""
    media_info: MediaInfo | None = None
    output_path: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["media_info"] = self.media_info.to_dict() if self.media_info else None
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoJob":
        mi = data.get("media_info")
        return cls(
            id=data.get("id", ""),
            project_id=data.get("project_id", ""),
            source_video=data.get("source_video", ""),
            status=data.get("status", JobStatus.PENDING.value),
            progress=float(data.get("progress", 0.0)),
            message=data.get("message", ""),
            media_info=MediaInfo.from_dict(mi) if mi else None,
            output_path=data.get("output_path", ""),
            error=data.get("error", ""),
        )

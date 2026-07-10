"""Project data model."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from utils.path_utils import project_dir
from core.constants import PROJECT_SUBDIRS


@dataclass
class Project:
    """A dubbing project, one per source video."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "Untitled"
    source_video: str = ""
    created_at: str = ""
    source_language: str | None = None
    target_language: str = "vi"

    def folder(self) -> Path:
        return project_dir(self.id)

    def subdir(self, name: str) -> Path:
        from utils.path_utils import ensure_dir
        return ensure_dir(self.folder() / name)

    def ensure_layout(self) -> None:
        for sub in PROJECT_SUBDIRS:
            self.subdir(sub)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            name=data.get("name", "Untitled"),
            source_video=data.get("source_video", ""),
            created_at=data.get("created_at", ""),
            source_language=data.get("source_language"),
            target_language=data.get("target_language", "vi"),
        )

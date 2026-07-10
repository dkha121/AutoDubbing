"""BlurRegion data model for the blur/logo editor."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from core.constants import BlurEffect, BlurRegionType


@dataclass
class BlurRegion:
    """A rectangular region to obscure for part or all of the video."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    x: int = 0
    y: int = 0
    width: int = 100
    height: int = 50
    start_time: float = 0.0
    end_time: float = 0.0  # <=0 means whole video
    type: str = BlurRegionType.SUBTITLE.value
    effect: str = BlurEffect.BLUR.value
    strength: int = 10

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BlurRegion":
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            width=int(data.get("width", 100)),
            height=int(data.get("height", 50)),
            start_time=float(data.get("start_time", 0.0)),
            end_time=float(data.get("end_time", 0.0)),
            type=data.get("type", BlurRegionType.SUBTITLE.value),
            effect=data.get("effect", BlurEffect.BLUR.value),
            strength=int(data.get("strength", 10)),
        )

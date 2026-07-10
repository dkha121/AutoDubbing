"""Small JSON helpers with safe read/write."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: str | Path, data: Any) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_json_block(text: str) -> Any:
    """Extract the first JSON array/object from a string that may contain
    markdown fences or prose around it (common with LLM responses)."""
    text = text.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("```", 2)
        text = text[1] if len(text) > 1 else text[0]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    text = text.strip().strip("`").strip()
    start = min(
        [i for i in (text.find("["), text.find("{")) if i != -1],
        default=-1,
    )
    if start == -1:
        raise ValueError("No JSON found in text")
    end = max(text.rfind("]"), text.rfind("}"))
    return json.loads(text[start:end + 1])

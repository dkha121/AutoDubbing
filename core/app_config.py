"""Application configuration loader/saver.

Config precedence:
  1. config.json (local, gitignored)  -- created from config.example.json on first run
  2. config.example.json              -- defaults shipped with the repo
  3. Environment variables for API keys (override file values if set)

No API keys or paths are hard-coded. Keys may also live in env vars:
  OPENAI_API_KEY, GEMINI_API_KEY
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

from utils.path_utils import package_root, resolve_path

_CONFIG_FILENAME = "config.json"
_EXAMPLE_FILENAME = "config.example.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into a copy of base."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class AppConfig:
    """Thread-safe-ish singleton holding application configuration."""

    _instance: "AppConfig | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.config_path: Path = package_root() / _CONFIG_FILENAME
        self.example_path: Path = package_root() / _EXAMPLE_FILENAME
        self.load()

    @classmethod
    def instance(cls) -> "AppConfig":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---- load / save -------------------------------------------------
    def load(self) -> None:
        defaults: dict[str, Any] = {}
        if self.example_path.exists():
            defaults = json.loads(self.example_path.read_text(encoding="utf-8"))

        user_data: dict[str, Any] = {}
        if self.config_path.exists():
            try:
                user_data = json.loads(self.config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                user_data = {}

        self._data = _deep_merge(defaults, user_data)
        self._apply_env_overrides()

    def save(self) -> None:
        """Persist current config to config.json (never to the example file)."""
        self.config_path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _apply_env_overrides(self) -> None:
        api = self._data.setdefault("api_keys", {})
        if os.environ.get("OPENAI_API_KEY"):
            api["openai_api_key"] = os.environ["OPENAI_API_KEY"]
        if os.environ.get("GEMINI_API_KEY"):
            api["gemini_api_key"] = os.environ["GEMINI_API_KEY"]

    # ---- accessors ---------------------------------------------------
    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Read a value via a dotted path, e.g. config.get('asr.default_model')."""
        node: Any = self._data
        for part in dotted_key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    # ---- convenience resolved paths ----------------------------------
    def ffmpeg_path(self) -> str:
        return self.get("ffmpeg_path", "ffmpeg")

    def ffprobe_path(self) -> str:
        return self.get("ffprobe_path", "ffprobe")

    def output_folder(self) -> Path:
        return resolve_path(self.get("default_output_folder", "./data/outputs"))

    def temp_folder(self) -> Path:
        return resolve_path(self.get("temp_folder", "./data/temp"))

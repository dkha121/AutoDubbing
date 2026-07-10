"""Path helpers. No hard-coded absolute paths anywhere in the app."""
from __future__ import annotations

import os
import re
from pathlib import Path

# Project root = the package directory's parent (local_video_dubbing_studio/)
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def package_root() -> Path:
    """Return the root folder of the application package."""
    return PACKAGE_ROOT


def resolve_path(path: str | os.PathLike[str]) -> Path:
    """Resolve a path. Relative paths are resolved against the package root."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = PACKAGE_ROOT / p
    return p.resolve()


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    """Create a directory (and parents) if missing, return resolved Path."""
    p = resolve_path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, fallback: str = "untitled") -> str:
    """Turn an arbitrary string into a filesystem-safe filename component."""
    stem = Path(name).stem
    cleaned = _SLUG_RE.sub("_", stem).strip("_.")
    return cleaned or fallback


def data_dir() -> Path:
    return ensure_dir(PACKAGE_ROOT / "data")


def projects_dir() -> Path:
    return ensure_dir(data_dir() / "projects")


def project_dir(project_id: str) -> Path:
    return ensure_dir(projects_dir() / project_id)

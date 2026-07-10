"""SQLite persistence layer.

A single database file at data/dubbing_studio.db holds projects, jobs,
subtitle segments, blur regions, settings, render presets and logs.
All access goes through this module; connections are per-call and short-lived.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logger import get_logger
from models.blur_region import BlurRegion
from models.project import Project
from models.subtitle_segment import SubtitleSegment
from models.video_job import VideoJob
from utils.path_utils import data_dir

logger = get_logger(__name__)

_DB_LOCK = threading.Lock()


def _db_path() -> Path:
    return data_dir() / "dubbing_studio.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT,
    source_video TEXT,
    created_at TEXT,
    source_language TEXT,
    target_language TEXT
);

CREATE TABLE IF NOT EXISTS video_jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    source_video TEXT,
    status TEXT,
    progress REAL,
    message TEXT,
    media_info TEXT,
    output_path TEXT,
    error TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subtitle_segments (
    project_id TEXT,
    seg_index INTEGER,
    start REAL,
    end REAL,
    source_text TEXT,
    vi_text TEXT,
    speaker TEXT,
    voice TEXT,
    status TEXT,
    PRIMARY KEY (project_id, seg_index),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS blur_regions (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    data TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS render_presets (
    name TEXT PRIMARY KEY,
    data TEXT
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    level TEXT,
    message TEXT
);
"""


def init_db() -> None:
    """Create tables if they do not exist."""
    with _DB_LOCK, _connect() as conn:
        conn.executescript(_SCHEMA)
    logger.info("Database initialised at %s", _db_path())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- projects --------------------------------------------------------
def create_project(project: Project) -> Project:
    if not project.created_at:
        project.created_at = _now()
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO projects (id,name,source_video,created_at,source_language,target_language)"
            " VALUES (?,?,?,?,?,?)",
            (project.id, project.name, project.source_video, project.created_at,
             project.source_language, project.target_language),
        )
    project.ensure_layout()
    return project


def get_project(project_id: str) -> Project | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return Project.from_dict(dict(row)) if row else None


def list_projects() -> list[Project]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [Project.from_dict(dict(r)) for r in rows]


def delete_project(project_id: str) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


# ---- jobs ------------------------------------------------------------
def upsert_job(job: VideoJob) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO video_jobs (id,project_id,source_video,status,progress,message,media_info,output_path,error)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (job.id, job.project_id, job.source_video, job.status, job.progress, job.message,
             json.dumps(job.media_info.to_dict()) if job.media_info else None,
             job.output_path, job.error),
        )


def update_job_status(job_id: str, status: str, progress: float | None = None,
                      message: str | None = None, error: str | None = None) -> None:
    sets = ["status=?"]
    params: list[Any] = [status]
    if progress is not None:
        sets.append("progress=?"); params.append(progress)
    if message is not None:
        sets.append("message=?"); params.append(message)
    if error is not None:
        sets.append("error=?"); params.append(error)
    params.append(job_id)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE video_jobs SET {','.join(sets)} WHERE id=?", params)


def list_jobs() -> list[VideoJob]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM video_jobs").fetchall()
    jobs = []
    for r in rows:
        d = dict(r)
        d["media_info"] = json.loads(d["media_info"]) if d.get("media_info") else None
        jobs.append(VideoJob.from_dict(d))
    return jobs


# ---- segments --------------------------------------------------------
def save_segments(project_id: str, segments: list[SubtitleSegment]) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM subtitle_segments WHERE project_id=?", (project_id,))
        conn.executemany(
            "INSERT INTO subtitle_segments (project_id,seg_index,start,end,source_text,vi_text,speaker,voice,status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [(project_id, s.index, s.start, s.end, s.source_text, s.vi_text,
              s.speaker, s.voice, s.status) for s in segments],
        )


def load_segments(project_id: str) -> list[SubtitleSegment]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM subtitle_segments WHERE project_id=? ORDER BY seg_index", (project_id,)
        ).fetchall()
    return [
        SubtitleSegment(
            index=r["seg_index"], start=r["start"], end=r["end"],
            source_text=r["source_text"] or "", vi_text=r["vi_text"] or "",
            speaker=r["speaker"], voice=r["voice"], status=r["status"] or "new",
        )
        for r in rows
    ]


# ---- blur regions ----------------------------------------------------
def save_blur_regions(project_id: str, regions: list[BlurRegion]) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM blur_regions WHERE project_id=?", (project_id,))
        conn.executemany(
            "INSERT INTO blur_regions (id,project_id,data) VALUES (?,?,?)",
            [(r.id, project_id, json.dumps(r.to_dict())) for r in regions],
        )


def load_blur_regions(project_id: str) -> list[BlurRegion]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT data FROM blur_regions WHERE project_id=?", (project_id,)).fetchall()
    return [BlurRegion.from_dict(json.loads(r["data"])) for r in rows]


# ---- logs ------------------------------------------------------------
def add_log(level: str, message: str) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("INSERT INTO logs (ts,level,message) VALUES (?,?,?)", (_now(), level, message))

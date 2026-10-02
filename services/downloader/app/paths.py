"""Where things live, in development (run from the repo) and when packaged (PyInstaller folder).

Packaged, the program folder is read-only (Program Files or a ZIP the user unpacked anywhere),
so everything the app writes goes to the per-user data folder instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SERVICE_DIR.parents[1]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder that holds sifon.exe (packaged) or the repo root (development)."""
    return Path(sys.executable).resolve().parent if is_frozen() else REPO_DIR


def resource_dir() -> Path:
    """Where PyInstaller unpacked the bundled data files (`_internal`), or the repo root."""
    return Path(getattr(sys, "_MEIPASS", REPO_DIR)) if is_frozen() else REPO_DIR


def web_dir() -> Path:
    return resource_dir() / "web"


def bin_dir() -> Path | None:
    """Folder with the bundled ffmpeg, ffprobe and deno. Only exists in the packaged app."""
    candidate = app_dir() / "bin"
    return candidate if is_frozen() and candidate.is_dir() else None


def data_dir() -> Path:
    """Per-user writable folder: logs, state, downloaded yt-dlp updates. Created on demand.

    `SIFON_DATA_DIR` overrides it (used by tests and by portable setups).
    """
    override = os.environ.get("SIFON_DATA_DIR", "").strip()
    base = Path(override) if override else Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "sifon"
    base.mkdir(parents=True, exist_ok=True)
    return base


def jobs_log_path() -> Path:
    """Development keeps the log next to the service (as documented); the packaged app cannot."""
    return data_dir() / "jobs.log" if is_frozen() else SERVICE_DIR / "jobs.log"


def prepend_bin_to_path(env: dict | None = None) -> Path | None:
    """Make the bundled ffmpeg/ffprobe/deno win over whatever is installed on the machine."""
    env = os.environ if env is None else env
    folder = bin_dir()
    if folder is None:
        return None
    current = env.get("PATH", "")
    if str(folder) not in current.split(os.pathsep):
        env["PATH"] = str(folder) + os.pathsep + current
    return folder

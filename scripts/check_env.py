"""Environment checks shared by install.ps1, run.ps1 and update-ytdlp.ps1.

Standard library only, so it runs before anything is installed. Prints one line per check:

    OK    name: detail
    WARN  name: detail       (the app runs, with less)
    FAIL  name: detail       (the app cannot work; exit code 1)

Usage (from any directory):
    python scripts/check_env.py              # interpreter + libraries + programs + settings
    python scripts/check_env.py --libs-only  # only the libraries (used right after pip)
    python scripts/check_env.py --versions   # one line, e.g. "yt-dlp 2026.08.19, yt-dlp-ejs 0.8.0"
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT / "services" / "downloader"

MIN_PYTHON = (3, 10)
TESTED_PYTHON = (3, 12)

# import name -> pip distribution name
LIBRARIES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "yt_dlp": "yt-dlp",
    "curl_cffi": "curl-cffi",
    "yt_dlp_ejs": "yt-dlp-ejs",
}

Result = tuple[str, str, str]  # (level, name, detail)


def check_python(version: tuple[int, int] = sys.version_info[:2]) -> list[Result]:
    shown = f"{version[0]}.{version[1]}"
    if version < MIN_PYTHON:
        return [("FAIL", "python", f"{shown} es demasiado viejo; hace falta {MIN_PYTHON[0]}.{MIN_PYTHON[1]} o más nuevo")]
    if version != TESTED_PYTHON:
        return [("WARN", "python", f"{shown}; la versión probada es {TESTED_PYTHON[0]}.{TESTED_PYTHON[1]}")]
    return [("OK", "python", shown)]


def check_libraries(find_spec: Callable = importlib.util.find_spec) -> list[Result]:
    results: list[Result] = []
    for module, dist in LIBRARIES.items():
        if find_spec(module) is None:
            results.append(("FAIL", dist, "no está instalada en este entorno"))
        else:
            results.append(("OK", dist, _version(dist)))
    return results


def _version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "?"


def ejs_requirement(requires: Iterable[str] | None) -> str | None:
    """The exact yt-dlp-ejs version that yt-dlp's [default] extra pins, or None if it is not exact."""
    for line in requires or ():
        match = re.match(r"\s*yt-dlp-ejs\s*==\s*([\w.]+)", line)
        if match:
            return match.group(1)
    return None


def check_ejs_matches_ytdlp(
    requires: Callable[[str], list[str] | None] = importlib.metadata.requires,
    installed: Callable[[str], str] = _version,
) -> list[Result]:
    try:
        pinned = ejs_requirement(requires("yt-dlp"))
    except importlib.metadata.PackageNotFoundError:
        return []  # reported by check_libraries
    have = installed("yt-dlp-ejs")
    if pinned is None:
        return [("OK", "yt-dlp-ejs", f"{have} (yt-dlp no fija una versión exacta)")]
    if have != pinned:
        return [("FAIL", "yt-dlp-ejs", f"instalada {have}, pero esta versión de yt-dlp pide {pinned}")]
    return [("OK", "yt-dlp-ejs", f"{have} coincide con lo que pide yt-dlp")]


def check_programs(which: Callable[[str], str | None] = shutil.which) -> list[Result]:
    results: list[Result] = []
    if which("ffmpeg"):
        results.append(("OK", "ffmpeg", which("ffmpeg")))
    else:
        results.append(("FAIL", "ffmpeg", "no está en el PATH; sin él no se puede descargar ni convertir nada"))
    if which("ffprobe"):
        results.append(("OK", "ffprobe", which("ffprobe")))
    else:
        results.append(("WARN", "ffprobe", "no está en el PATH; es opcional, pero algunos videos HLS y el eval lo necesitan"))
    if which("deno"):
        results.append(("OK", "deno", which("deno")))
    elif which("node"):
        results.append(("WARN", "deno", "no está en el PATH; se usará node, que es menos probado. Se recomienda instalar Deno"))
    else:
        results.append(("WARN", "deno", "no está en el PATH; YouTube puede fallar o limitar las calidades. Se recomienda instalar Deno"))
    return results


def check_settings() -> list[Result]:
    sys.path.insert(0, str(SERVICE_DIR))
    try:
        from app.config import SettingsError, load_settings
    except ImportError as exc:  # service code not importable from here
        return [("FAIL", "settings", f"no se pudo cargar app.config: {exc}")]
    finally:
        sys.path.remove(str(SERVICE_DIR))
    try:
        s = load_settings()
    except SettingsError as exc:
        return [("FAIL", "settings", str(exc))]
    return [
        (
            "OK",
            "limites",
            f"{s.max_concurrent} simultáneas, cola {s.max_queue}, {s.max_filesize_mb} MB, "
            f"{s.max_duration_min} min, {s.min_free_disk_mb} MB libres",
        )
    ]


def render(results: list[Result]) -> str:
    return "\n".join(f"{level:<5} {name}: {detail}" for level, name, detail in results)


def versions_line() -> str:
    return ", ".join(f"{dist} {_version(dist)}" for dist in ("yt-dlp", "yt-dlp-ejs", "curl-cffi"))


def main(argv: list[str]) -> int:
    if "--versions" in argv:
        print(versions_line())
        return 0
    ejs = check_ejs_matches_ytdlp()
    # The ejs result already names the version, so it replaces the plain library line.
    libs = [r for r in check_libraries() if not (ejs and r[1] == "yt-dlp-ejs" and r[0] == "OK")]
    results = libs + ejs
    if "--libs-only" not in argv:
        results = check_python() + results + check_programs() + check_settings()
    print(render(results))
    return 1 if any(level == "FAIL" for level, _, _ in results) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))

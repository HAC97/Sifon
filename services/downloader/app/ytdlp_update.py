"""Keep yt-dlp fresh inside the packaged app, where there is no pip.

yt-dlp breaks every few weeks when a site changes. The packaged app ships one version; this
module downloads newer ones from PyPI into the user's data folder and loads them in front of
the bundled copy on the next start.

Safety, in order:
- the wheel must match the SHA-256 PyPI publishes for it (corruption, wrong file);
- only `yt_dlp/` and `yt_dlp_ejs/` are extracted, with path, size and count limits;
- the unpacked copy is imported in a throwaway process first; only then is it marked usable;
- at start-up a copy that fails to import is set aside and the bundled one is used;
- nothing here may raise into the app: every failure becomes an UpdateResult.

Trust: this runs code that comes from PyPI over HTTPS. That is the same trust `pip install` and
`update.cmd` already place in PyPI. `SIFON_NO_AUTO_UPDATE=1` or the window's checkbox turns the
automatic check off.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("videodownloader")

PYPI_JSON = "https://pypi.org/pypi/{name}/json"
OVERLAY_DIR = "ytdlp"
OK_MARKER = "ok.json"
PACKAGES = ("yt_dlp", "yt_dlp_ejs")
KEEP_VERSIONS = 2
CHECK_EVERY_SECONDS = 24 * 3600
MAX_WHEEL_BYTES = 40 * 1024 * 1024
MAX_UNPACKED_BYTES = 120 * 1024 * 1024
MAX_FILES = 6000
HTTP_TIMEOUT = 20

Fetch = Callable[[str], bytes]


@dataclass
class UpdateResult:
    status: str  # "updated" | "current" | "skipped" | "failed"
    detail: str = ""
    version: str | None = None


def version_key(version: str) -> tuple[int, ...]:
    """'2026.08.19' -> (2026, 8, 19); '2026.8.19.post1' -> (2026, 8, 19, 1). Unparseable -> ()."""
    parts = re.findall(r"\d+", version)
    return tuple(int(p) for p in parts)


def default_fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("only https downloads are allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "sifon-updater"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:  # noqa: S310 (https only, checked above)
        chunks, total = [], 0
        while chunk := response.read(1 << 16):
            total += len(chunk)
            if total > MAX_WHEEL_BYTES:
                raise ValueError("download is larger than the allowed size")
            chunks.append(chunk)
    return b"".join(chunks)


# --- what is installed --------------------------------------------------------------------------


def overlay_root(data_dir: Path) -> Path:
    return data_dir / OVERLAY_DIR


def usable_overlays(data_dir: Path) -> list[tuple[tuple[int, ...], Path]]:
    """Overlay folders that finished installing (they carry the marker), newest first."""
    root = overlay_root(data_dir)
    found = []
    if root.is_dir():
        for entry in root.iterdir():
            if entry.is_dir() and not entry.name.endswith((".tmp", ".bad")) and (entry / OK_MARKER).is_file():
                key = version_key(entry.name)
                if key:
                    found.append((key, entry))
    return sorted(found, reverse=True)


def apply_overlay(data_dir: Path, bundled_version: str | None = None) -> str | None:
    """Put the newest usable overlay in front of the bundled yt-dlp. Call BEFORE importing it.

    Returns the version that will be used, or None to keep the bundled one. A copy that does not
    import is renamed `.bad` and skipped.
    """
    if "yt_dlp" in sys.modules:
        return None
    for key, folder in usable_overlays(data_dir):
        if bundled_version and key <= version_key(bundled_version):
            return None  # the bundled one is as new or newer: the overlay is stale
        sys.path.insert(0, str(folder))
        try:
            import yt_dlp.version  # noqa: PLC0415
            import yt_dlp_ejs  # noqa: F401, PLC0415

            return yt_dlp.version.__version__
        except Exception:  # noqa: BLE001 - any failure means: do not use this copy
            log.exception("yt-dlp update %s does not load; using the bundled copy", folder.name)
            sys.path.remove(str(folder))
            for name in [m for m in sys.modules if m.split(".")[0] in PACKAGES]:
                del sys.modules[name]
            try:
                folder.rename(folder.with_name(folder.name + ".bad"))
            except OSError:
                pass
    return None


# --- PyPI ---------------------------------------------------------------------------------------


def _wheel(info: dict, version: str) -> dict:
    """The pure-python wheel entry (url, sha256) for `version` from a PyPI JSON document."""
    for entry in info.get("releases", {}).get(version, []) or info.get("urls", []):
        name = entry.get("filename", "")
        if entry.get("packagetype") == "bdist_wheel" and name.endswith("-py3-none-any.whl") and not entry.get("yanked"):
            return {"url": entry["url"], "sha256": entry["digests"]["sha256"], "filename": name}
    raise ValueError(f"no universal wheel published for {version}")


def _ejs_pin(requires_dist: list[str] | None) -> str | None:
    for line in requires_dist or ():
        match = re.match(r"\s*yt-dlp-ejs\s*==\s*([\w.]+)", line)
        if match:
            return match.group(1)
    return None


def plan_update(fetch: Fetch, installed: str) -> tuple[str, list[dict]] | None:
    """(new version, wheels to install) or None if `installed` is already the latest."""
    meta = json.loads(fetch(PYPI_JSON.format(name="yt-dlp")))
    latest = meta["info"]["version"]
    if version_key(latest) <= version_key(installed):
        return None
    wheels = [_wheel(meta, latest)]
    pin = _ejs_pin(meta["info"].get("requires_dist"))
    if pin:
        ejs_meta = json.loads(fetch(PYPI_JSON.format(name=f"yt-dlp-ejs/{pin}")))
        wheels.append(_wheel({"urls": ejs_meta["urls"]}, pin))
    return latest, wheels


# --- unpacking ----------------------------------------------------------------------------------


def safe_extract(wheel_bytes: bytes, target: Path) -> int:
    """Unpack `yt_dlp/` and `yt_dlp_ejs/` from a wheel. Returns the number of files written."""
    written, total = 0, 0
    root = target.resolve()
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        for info in archive.infolist():
            name = info.filename
            if info.is_dir() or name.split("/")[0] not in PACKAGES:
                continue
            if name.startswith("/") or "\\" in name or ".." in name.split("/") or ":" in name:
                raise ValueError(f"unsafe path in wheel: {name!r}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"symlink in wheel: {name!r}")
            destination = (root / name).resolve()
            if root not in destination.parents:
                raise ValueError(f"path escapes the target: {name!r}")
            total += info.file_size
            written += 1
            if written > MAX_FILES or total > MAX_UNPACKED_BYTES:
                raise ValueError("wheel is larger than the allowed size")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))
    return written


def selftest_command(folder: Path, expected: str) -> list[str]:
    """Command that imports the overlay in a fresh process and exits 0 only if it works."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--selftest-ytdlp", str(folder), expected]
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import yt_dlp.version as v, yt_dlp_ejs;"
        "assert v.__version__ == sys.argv[2], v.__version__; print(v.__version__)"
    )
    return [sys.executable, "-c", code, str(folder), expected]


def run_selftest(folder: Path, expected: str) -> bool:
    try:
        done = subprocess.run(selftest_command(folder, expected), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and done.stdout.strip().endswith(expected)


# --- the update itself -------------------------------------------------------------------------


def install_update(
    data_dir: Path,
    installed: str,
    fetch: Fetch = default_fetch,
    selftest: Callable[[Path, str], bool] = run_selftest,
) -> UpdateResult:
    try:
        plan = plan_update(fetch, installed)
        if plan is None:
            return UpdateResult("current", f"yt-dlp {installed} es la última versión publicada", installed)
        version, wheels = plan
        final = overlay_root(data_dir) / version
        if (final / OK_MARKER).is_file():
            return UpdateResult("updated", f"yt-dlp {version} ya estaba descargado; se aplica al reiniciar", version)
        staging = overlay_root(data_dir) / f"{version}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            for wheel in wheels:
                content = fetch(wheel["url"])
                if hashlib.sha256(content).hexdigest() != wheel["sha256"].lower():
                    raise ValueError(f"hash mismatch for {wheel['filename']}")
                safe_extract(content, staging)
            if not selftest(staging, version):
                raise ValueError("the downloaded yt-dlp does not start")
            (staging / OK_MARKER).write_text(json.dumps({"version": version, "installed_at": time.time()}), encoding="utf-8")
            shutil.rmtree(final, ignore_errors=True)
            staging.rename(final)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        prune(data_dir)
        return UpdateResult("updated", f"yt-dlp {version} descargado y verificado; se aplica al reiniciar", version)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raise"
        log.warning("yt-dlp update failed (%s)", type(exc).__name__)
        return UpdateResult("failed", f"No se pudo actualizar yt-dlp ({type(exc).__name__}: {exc})")


def prune(data_dir: Path) -> None:
    for _, folder in usable_overlays(data_dir)[KEEP_VERSIONS:]:
        shutil.rmtree(folder, ignore_errors=True)
    root = overlay_root(data_dir)
    if root.is_dir():
        for stale in root.glob("*.tmp"):
            shutil.rmtree(stale, ignore_errors=True)


# --- when to check ------------------------------------------------------------------------------


def _state_file(data_dir: Path) -> Path:
    return data_dir / "update_state.json"


def read_prefs(data_dir: Path) -> dict:
    try:
        return json.loads(_state_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_prefs(data_dir: Path, **changes) -> None:
    state = {**read_prefs(data_dir), **changes}
    try:
        _state_file(data_dir).write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        log.warning("could not save update preferences")


def auto_update_enabled(data_dir: Path, env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    if env.get("SIFON_NO_AUTO_UPDATE", "").strip() not in ("", "0"):
        return False
    return bool(read_prefs(data_dir).get("auto", True))


def check_due(data_dir: Path, now: float | None = None) -> bool:
    last = read_prefs(data_dir).get("last_check", 0)
    return (time.time() if now is None else now) - float(last or 0) >= CHECK_EVERY_SECONDS


def update_if_due(data_dir: Path, installed: str, fetch: Fetch = default_fetch, **kwargs) -> UpdateResult:
    """Background entry point: one check per day, never raises, remembers when it last asked."""
    if not auto_update_enabled(data_dir):
        return UpdateResult("skipped", "las actualizaciones automáticas están desactivadas")
    if not check_due(data_dir):
        return UpdateResult("skipped", "ya se buscó hoy")
    result = install_update(data_dir, installed, fetch, **kwargs)
    if result.status != "failed":  # a failed check (offline) is retried at the next start
        write_prefs(data_dir, last_check=time.time())
    return result

"""Download and verify the programs that ship inside the Windows package.

- FFmpeg + FFprobe: BtbN's LGPL "shared" build (no --enable-gpl, so it may be redistributed under
  the LGPL). It includes libmp3lame, libopus and aac, which is all sifón needs.
  BtbN publishes `checksums.sha256` next to the zip; the download must match it.
- Deno: a pinned release; the hash comes from the `.sha256sum` file of that release.

Nothing is trusted without a hash, and the hash is recorded in the package's BUNDLED.txt.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

FFMPEG_ZIP = "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip"
FFMPEG_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
DENO_VERSION = "2.9.7"
DENO_ZIP = "deno-x86_64-pc-windows-msvc.zip"
DENO_BASE = f"https://github.com/denoland/deno/releases/download/v{DENO_VERSION}/"
DENO_LICENSE = f"https://raw.githubusercontent.com/denoland/deno/v{DENO_VERSION}/LICENSE.md"


@dataclass
class Tool:
    name: str
    version: str
    sha256: str
    source: str


def download(url: str, target: Path, timeout: int = 300) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not url.startswith("https://"):
        raise ValueError("only https downloads are allowed")
    if target.is_file() and target.stat().st_size > 0 and not target.name.endswith((".sha", ".sha256")):
        return target  # cached; its hash is checked against the publisher's list right after
    request = urllib.request.Request(url, headers={"User-Agent": "sifon-build"})
    with urllib.request.urlopen(request, timeout=timeout) as response, target.open("wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out)
    return target


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_from_checksums(text: str, filename: str) -> str:
    """Hash for `filename` out of a `sha256sum`-style file ('<hash>  <name>')."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    raise ValueError(f"{filename} is not listed in the checksum file")


def expected_from_powershell_sum(text: str) -> str:
    """Deno publishes `Get-FileHash` output ('Hash : A0C3...')."""
    match = re.search(r"Hash\s*:\s*([0-9A-Fa-f]{64})", text)
    if not match:
        raise ValueError("no SHA-256 in the checksum file")
    return match.group(1).lower()


def verify(path: Path, expected: str) -> str:
    actual = sha256_of(path)
    if actual != expected.lower():
        raise ValueError(f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}")
    return actual


def safe_members(archive: zipfile.ZipFile, wanted: dict[str, str]) -> dict[str, zipfile.ZipInfo]:
    """Map output name -> member, for members whose basename is in `wanted` (no path tricks)."""
    found = {}
    for info in archive.infolist():
        base = info.filename.rsplit("/", 1)[-1]
        if info.is_dir() or base not in wanted:
            continue
        if ".." in info.filename.split("/") or info.filename.startswith("/") or ":" in info.filename:
            raise ValueError(f"unsafe path in archive: {info.filename!r}")
        found[wanted[base]] = info
    return found


def fetch_ffmpeg(cache: Path, bin_dir: Path, licenses_dir: Path) -> Tool:
    archive_path = download(FFMPEG_BASE + FFMPEG_ZIP, cache / FFMPEG_ZIP)
    checksums = download(FFMPEG_BASE + "checksums.sha256", cache / "checksums.sha256").read_text(encoding="utf-8")
    actual = verify(archive_path, expected_from_checksums(checksums, FFMPEG_ZIP))
    bin_dir.mkdir(parents=True, exist_ok=True)
    licenses_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as z:
        names = z.namelist()
        dlls = {n.rsplit("/", 1)[-1]: n.rsplit("/", 1)[-1] for n in names if n.endswith(".dll") and "/bin/" in n}
        wanted = {"ffmpeg.exe": "ffmpeg.exe", "ffprobe.exe": "ffprobe.exe", **dlls}
        members = safe_members(z, wanted)
        if "ffmpeg.exe" not in members or "ffprobe.exe" not in members:
            raise ValueError("ffmpeg.exe or ffprobe.exe is missing from the archive")
        for out_name, info in members.items():
            (bin_dir / out_name).write_bytes(z.read(info))
        lic = [n for n in names if n.endswith("/LICENSE.txt") and n.count("/") == 1]
        if lic:
            (licenses_dir / "FFmpeg-LICENSE.txt").write_bytes(z.read(lic[0]))
    return Tool("FFmpeg (LGPL, BtbN build)", FFMPEG_ZIP, actual, FFMPEG_BASE + FFMPEG_ZIP)


def fetch_deno(cache: Path, bin_dir: Path, licenses_dir: Path) -> Tool:
    archive_path = download(DENO_BASE + DENO_ZIP, cache / f"deno-{DENO_VERSION}.zip")
    sums = download(DENO_BASE + DENO_ZIP + ".sha256sum", cache / f"deno-{DENO_VERSION}.sha").read_text(encoding="utf-8")
    actual = verify(archive_path, expected_from_powershell_sum(sums))
    bin_dir.mkdir(parents=True, exist_ok=True)
    licenses_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as z:
        members = safe_members(z, {"deno.exe": "deno.exe"})
        if "deno.exe" not in members:
            raise ValueError("deno.exe is missing from the archive")
        (bin_dir / "deno.exe").write_bytes(z.read(members["deno.exe"]))
    download(DENO_LICENSE, licenses_dir / "Deno-LICENSE.md")
    return Tool("Deno (MIT)", DENO_VERSION, actual, DENO_BASE + DENO_ZIP)


def fetch_all(cache: Path, bin_dir: Path, licenses_dir: Path) -> list[Tool]:
    return [fetch_ffmpeg(cache, bin_dir, licenses_dir), fetch_deno(cache, bin_dir, licenses_dir)]

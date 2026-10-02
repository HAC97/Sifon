from __future__ import annotations

import shutil
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode, map_error
from app.formats import OUTTMPL, ytdlp_options

_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp")


def find_output(job_dir: Path) -> Path:
    candidates = [
        p for p in job_dir.iterdir() if p.is_file() and not p.name.endswith(_PARTIAL_SUFFIXES)
    ]
    if not candidates:
        raise DownloadFailure(ErrorCode.UNKNOWN)
    return max(candidates, key=lambda p: p.stat().st_size)


def run_download(job, on_progress, ytdlp_cls=yt_dlp.YoutubeDL, which=shutil.which) -> Path:
    if which("ffmpeg") is None:
        raise DownloadFailure(ErrorCode.FFMPEG_MISSING)

    def postprocessor_hook(data: dict) -> None:
        if data.get("status") == "started":
            on_progress({"status": "processing"})

    opts = ytdlp_options(
        job.mode,
        job.height,
        job.audio_format,
        str(job.dir / OUTTMPL),
        on_progress,
        postprocessor_hook,
    )
    try:
        with ytdlp_cls(opts) as ydl:
            ydl.download([job.url])
    except DownloadError as error:
        raise DownloadFailure(map_error(str(error))) from error
    return find_output(job.dir)

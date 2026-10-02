from __future__ import annotations

import shutil
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode, map_error
from app.formats import OUTTMPL, ytdlp_options
from app.mp4_repair import repair_mp4
from app.runtimes import js_runtimes_option

_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp")


def find_output(job_dir: Path) -> Path:
    candidates = [
        p for p in job_dir.iterdir() if p.is_file() and not p.name.endswith(_PARTIAL_SUFFIXES)
    ]
    if not candidates:
        raise DownloadFailure(ErrorCode.UNKNOWN)
    return max(candidates, key=lambda p: p.stat().st_size)


def run_download(
    job,
    on_progress,
    ytdlp_cls=yt_dlp.YoutubeDL,
    which=shutil.which,
    proxy: str | None = None,
    max_duration_s: float | None = None,
) -> Path:
    if which("ffmpeg") is None:
        raise DownloadFailure(ErrorCode.FFMPEG_MISSING)

    rejected: list[str] = []

    def match_filter(info: dict, *, incomplete: bool = False):
        # yt-dlp skips a rejected video without raising; `rejected` is how we notice afterwards.
        if info.get("is_live"):
            rejected.append("live")
            return "live stream"
        duration = info.get("duration")
        if max_duration_s and duration and duration > max_duration_s:
            rejected.append("long")
            return "too long"
        return None

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
        proxy=proxy,
        match_filter=match_filter,
        js_runtimes=js_runtimes_option(which),
    )
    try:
        with ytdlp_cls(opts) as ydl:
            ydl.download([job.url])
    except DownloadError as error:
        raise DownloadFailure(map_error(str(error))) from error
    if rejected:
        raise DownloadFailure(ErrorCode.TOO_LONG)
    output = find_output(job.dir)
    if job.mode == "video":
        repair_mp4(output)
    return output

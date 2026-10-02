"""Turn an HLS download that is really MPEG-TS (with junk in front) into a real mp4.

Some sites hide their HLS segments behind a fake 1x1 PNG. yt-dlp saves the stream as `.mp4`, and its
own fixup (`FFmpegFixupM3u8PP`) only runs when ffprobe reports `mpegts`. Behind the PNG ffprobe
says `png_pipe`, so the fixup is skipped without a word and the user gets a file Google Drive and
most players reject. This module reads the bytes itself (ffprobe is optional in this app), finds
where the TS starts and remuxes it with ffmpeg, no re-encoding.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.errors import DownloadFailure, ErrorCode

_HEAD_BYTES = 64 * 1024
_TS_PACKET = 188
_TS_SYNC = 0x47
_REMUX_TIMEOUT_S = 30 * 60
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def is_mp4(head: bytes) -> bool:
    return head[4:8] == b"ftyp"


def find_ts_offset(head: bytes) -> int | None:
    """Offset of the first MPEG-TS packet: three sync bytes in a row, one packet apart."""
    for i in range(len(head) - 2 * _TS_PACKET):
        if head[i] == _TS_SYNC and head[i + _TS_PACKET] == _TS_SYNC and head[i + 2 * _TS_PACKET] == _TS_SYNC:
            return i
    return None


def _remux_command(ffmpeg: str, source: Path, skip: int, target: Path, adts_fix: bool) -> list[str]:
    return [
        ffmpeg, "-v", "error", "-y",
        "-skip_initial_bytes", str(skip), "-f", "mpegts", "-i", str(source),
        "-c", "copy", *(["-bsf:a", "aac_adtstoasc"] if adts_fix else []),
        "-movflags", "+faststart", "-f", "mp4", str(target),
    ]


def repair_mp4(path: Path, run=subprocess.run, ffmpeg: str = "ffmpeg") -> None:
    """Replace `path` in place by a real mp4 when it holds MPEG-TS. Anything else is left alone."""
    with path.open("rb") as handle:
        head = handle.read(_HEAD_BYTES)
    if is_mp4(head):
        return
    offset = find_ts_offset(head)
    if offset is None:
        return

    # ".part" keeps find_output from picking the half-written file if we are interrupted.
    target = path.with_name(path.name + ".repair.part")
    try:
        # aac_adtstoasc is needed for AAC and errors out on any other audio codec, hence the retry.
        for adts_fix in (True, False):
            done = run(
                _remux_command(ffmpeg, path, offset, target, adts_fix),
                capture_output=True, timeout=_REMUX_TIMEOUT_S, creationflags=_NO_WINDOW,
            )
            if done.returncode == 0:
                os.replace(target, path)
                return
        raise DownloadFailure(ErrorCode.UNKNOWN)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DownloadFailure(ErrorCode.UNKNOWN) from error
    finally:
        target.unlink(missing_ok=True)

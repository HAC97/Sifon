from __future__ import annotations

import yt_dlp
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode, map_error


def summarize_info(raw: dict) -> dict:
    if raw.get("_type") == "playlist" or "entries" in raw:
        entries = [entry for entry in (raw.get("entries") or []) if entry]
        if not entries:
            raise DownloadFailure(ErrorCode.UNKNOWN)
        raw = entries[0]
    heights = sorted(
        {
            int(fmt["height"])
            for fmt in raw.get("formats") or []
            if fmt.get("height") and fmt.get("vcodec") != "none"
        },
        reverse=True,
    )
    return {
        "title": raw.get("title") or "video",
        "thumbnail": raw.get("thumbnail"),
        "duration": raw.get("duration"),
        "uploader": raw.get("uploader") or raw.get("channel"),
        "heights": heights,
    }


def fetch_info(url: str, ytdlp_cls=yt_dlp.YoutubeDL, proxy: str | None = None, js_runtimes: dict | None = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlist_items": "1",
        "skip_download": True,
        "socket_timeout": 20,
    }
    if proxy:
        opts["proxy"] = proxy
    if js_runtimes is not None:
        opts["js_runtimes"] = js_runtimes
    try:
        with ytdlp_cls(opts) as ydl:
            raw = ydl.extract_info(url, download=False)
            if raw is None:
                raise DownloadFailure(ErrorCode.UNKNOWN)
            return summarize_info(ydl.sanitize_info(raw))
    except DownloadError as error:
        raise DownloadFailure(map_error(str(error))) from error

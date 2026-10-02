HEIGHTS = ("360", "480", "720", "1080", "1440", "2160")
AUDIO_CODECS = {"mp3": "mp3", "m4a": "m4a", "opus": "opus"}

# 120 chars keeps the full path under Windows' 260 limit even inside the temp dir.
OUTTMPL = "%(title).120s [%(id)s].%(ext)s"


def video_selector(height: str = "best") -> str:
    if height == "best":
        return "bv*+ba/b"
    if height not in HEIGHTS:
        raise ValueError(f"invalid height: {height!r}")
    cap = f"[height<={height}]"
    return f"bv*{cap}+ba/b{cap}"


def ytdlp_options(
    mode: str,
    height: str,
    audio_format: str,
    outtmpl: str,
    progress_hook,
    postprocessor_hook=None,
    proxy: str | None = None,
    match_filter=None,
    js_runtimes: dict | None = None,
) -> dict:
    opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
        "socket_timeout": 20,
        "retries": 3,
        "progress_hooks": [progress_hook],
    }
    if postprocessor_hook is not None:
        opts["postprocessor_hooks"] = [postprocessor_hook]
    if proxy:
        opts["proxy"] = proxy
    if match_filter is not None:
        opts["match_filter"] = match_filter
    if js_runtimes is not None:
        opts["js_runtimes"] = js_runtimes

    if mode == "video":
        opts["format"] = video_selector(height)
        # Resolution first, then prefer mp4/m4a so the mp4 merge is a plain remux when possible.
        opts["format_sort"] = ["res", "ext:mp4:m4a"]
        opts["merge_output_format"] = "mp4"
    elif mode == "audio":
        if audio_format not in AUDIO_CODECS:
            raise ValueError(f"invalid audio format: {audio_format!r}")
        opts["format"] = "bestaudio/best"
        processor = {"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_CODECS[audio_format]}
        if audio_format == "mp3":
            processor["preferredquality"] = "192"
        opts["postprocessors"] = [processor]
    else:
        raise ValueError(f"invalid mode: {mode!r}")
    return opts

"""External programs the app depends on, looked up on PATH."""
from __future__ import annotations

import shutil
from typing import Callable

Which = Callable[[str], "str | None"]


def detect_js_runtime(which: Which = shutil.which) -> str | None:
    """JavaScript engine yt-dlp uses to solve YouTube's player challenges. Deno is preferred."""
    for name in ("deno", "node"):
        if which(name):
            return name
    return None


def js_runtimes_option(which: Which = shutil.which) -> dict:
    """Value for yt-dlp's `js_runtimes` option: only the engine that is actually installed."""
    name = detect_js_runtime(which)
    return {name: {}} if name else {}

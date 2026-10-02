import json
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from app.extractor import fetch_info
from app.jobs import Job
from app.ytdlp_runner import run_download

pytestmark = pytest.mark.eval

THRESHOLD = 0.8
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# URLs verified on 2026-10-01, see URL_VERIFICATION.md
YOUTUBE = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
VIMEO = "https://vimeo.com/56015672"
SOUNDCLOUD = "https://soundcloud.com/ethmusic/lostin-powers-she-so-heavy"
ARCHIVE = "https://archive.org/details/Popeye_forPresident"
DAILYMOTION = "http://www.dailymotion.com/video/x5kesuj"

# (site, url, mode, audio_format)
CASES = [
    ("youtube", YOUTUBE, "video", "mp3"),
    ("youtube", YOUTUBE, "audio", "mp3"),
    ("youtube", YOUTUBE, "audio", "m4a"),
    ("youtube", YOUTUBE, "audio", "opus"),
    ("vimeo", VIMEO, "video", "mp3"),
    ("vimeo", VIMEO, "audio", "mp3"),
    ("soundcloud", SOUNDCLOUD, "audio", "mp3"),
    ("archive", ARCHIVE, "video", "mp3"),
    ("archive", ARCHIVE, "audio", "mp3"),
    ("dailymotion", DAILYMOTION, "video", "mp3"),
    ("dailymotion", DAILYMOTION, "audio", "mp3"),
]

AUDIO_CODEC = {"mp3": "mp3", "m4a": "aac", "opus": "opus"}


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def verify(path: Path, mode: str, audio_format: str, expected_duration) -> str | None:
    """Return None when the file is valid, otherwise the reason it is not."""
    data = probe(path)
    kinds = {s["codec_type"] for s in data["streams"]}
    duration = float(data["format"]["duration"])
    if expected_duration and abs(duration - expected_duration) > max(2.0, 0.05 * expected_duration):
        return f"duration {duration:.1f}s vs expected {expected_duration}s"
    if mode == "video":
        return None if {"video", "audio"} <= kinds else f"streams {sorted(kinds)}"
    if kinds != {"audio"}:
        return f"streams {sorted(kinds)}"
    codec = next(s["codec_name"] for s in data["streams"] if s["codec_type"] == "audio")
    return None if codec == AUDIO_CODEC[audio_format] else f"codec {codec}"


def run_case(site, url, mode, audio_format) -> dict:
    started = time.time()
    try:
        info = fetch_info(url)
        with tempfile.TemporaryDirectory(prefix="vd-eval-") as tmp:
            job = Job(
                id="eval",
                url=url,
                mode=mode,
                height="360" if mode == "video" else "best",
                audio_format=audio_format,
                dir=Path(tmp),
            )
            path = run_download(job, lambda data: None)
            reason = verify(path, mode, audio_format, info.get("duration"))
    except Exception as error:  # noqa: BLE001 - any failure is a failed case
        reason = f"{type(error).__name__}: {error}"
    return {
        "site": site,
        "mode": mode,
        "audio_format": audio_format,
        "ok": reason is None,
        "reason": reason,
        "seconds": round(time.time() - started, 1),
    }


def test_download_success_rate_meets_threshold():
    results = [run_case(*case) for case in CASES]
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "last_run.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['site']:12} {r['mode']:6} {r['audio_format']:5} {r['seconds']:6}s  {r['reason'] or ''}")
    rate = sum(r["ok"] for r in results) / len(results)
    print(f"success rate: {rate:.0%} (threshold {THRESHOLD:.0%})")
    assert rate >= THRESHOLD

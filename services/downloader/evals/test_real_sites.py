import json
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from app.extractor import fetch_info
from app.jobs import Job
from app.ytdlp_runner import run_download
from evals.scoring import (
    DEAD_VIMEO_URL,
    FAIL,
    KNOWN_DEAD,
    KNOWN_DEAD_CASES,
    NETWORK,
    NETWORK_SHARE_LIMIT,
    PASS,
    THRESHOLD,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    classify_exception,
    finalize_kind,
    run_with_retry,
    summarize,
)

pytestmark = pytest.mark.eval

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# URLs verified on 2026-10-01, see URL_VERIFICATION.md
YOUTUBE = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
VIMEO = DEAD_VIMEO_URL  # known dead, see KNOWN_DEAD_CASES
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
        kind = PASS if reason is None else FAIL  # a bad file is a product failure
    except Exception as error:  # noqa: BLE001 - classified: network/timeout vs product failure
        reason = f"{type(error).__name__}: {error}"
        kind = classify_exception(error)
    return {
        "site": site,
        "mode": mode,
        "audio_format": audio_format,
        "kind": kind,
        "reason": reason,
        "seconds": round(time.time() - started, 1),
    }


def run_and_classify(site, url, mode, audio_format) -> dict:
    result = run_with_retry(lambda: run_case(site, url, mode, audio_format))
    result["kind"], result["promote"] = finalize_kind(result["kind"], (url, mode) in KNOWN_DEAD_CASES)
    return result


LABEL = {PASS: "PASS", FAIL: "FAIL", NETWORK: "NETWORK", KNOWN_DEAD: "KNOWN_DEAD"}


def test_download_success_rate_meets_threshold():
    results = [run_and_classify(*case) for case in CASES]
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "last_run.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    for r in results:
        promote = "  PROMOTE" if r["promote"] else ""
        print(
            f"{LABEL[r['kind']]:10} {r['site']:12} {r['mode']:6} {r['audio_format']:5} "
            f"{r['seconds']:6}s  {r['reason'] or ''}{promote}"
        )
    summary = summarize(results)
    print("counts: " + ", ".join(f"{LABEL[k]}={summary.counts[k]}" for k in summary.counts))
    rate = "n/a" if summary.rate is None else f"{summary.rate:.0%}"
    print(f"success rate (pass / (pass + fail)): {rate} (threshold {THRESHOLD:.0%})")
    print(f"network share of active cases: {summary.network_share:.0%} (limit {NETWORK_SHARE_LIMIT:.0%})")
    print(f"verdict: {summary.verdict}")

    assert not summary.promote, (
        "known-dead case(s) passed: move them back to the active cases and drop them from KNOWN_DEAD_CASES: "
        + ", ".join(f"{r['site']}/{r['mode']}" for r in summary.promote)
    )
    assert summary.verdict != VERDICT_INCONCLUSIVE, (
        f"INCONCLUSIVE: network results are {summary.network_share:.0%} of the active cases "
        f"(limit {NETWORK_SHARE_LIMIT:.0%}). The sites were not reachable, so this run says nothing "
        "about the product. Re-run when the network is fine."
    )
    assert summary.verdict == VERDICT_PASS, f"success rate {rate} is below the {THRESHOLD:.0%} threshold"

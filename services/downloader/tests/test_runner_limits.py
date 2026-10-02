"""run_download: duration/live filter, proxy and JS runtime plumbing (yt-dlp is faked)."""
from pathlib import Path

import pytest

from app.errors import DownloadFailure, ErrorCode
from app.jobs import Job
from app.ytdlp_runner import run_download


def make_job(tmp_path):
    return Job(id="j", url="https://example.com/v", mode="video", height="best", audio_format="mp3", dir=tmp_path)


def fake_ydl(info):
    """A yt-dlp stand-in that applies the configured match_filter to `info` like the real one."""

    class FakeYDL:
        instances = []

        def __init__(self, opts):
            self.opts = opts
            FakeYDL.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            if self.opts["match_filter"](info, incomplete=False) is None:
                (Path(self.opts["outtmpl"]).parent / "Title [abc].mp4").write_bytes(b"x")

    return FakeYDL


def has_everything(_name):
    return "/bin/tool"


def test_proxy_and_js_runtime_reach_yt_dlp(tmp_path):
    cls = fake_ydl({"duration": 10})
    run_download(make_job(tmp_path), lambda d: None, ytdlp_cls=cls, which=has_everything, proxy="http://127.0.0.1:9")
    opts = cls.instances[0].opts
    assert opts["proxy"] == "http://127.0.0.1:9"
    assert opts["js_runtimes"] == {"deno": {}}


def test_video_within_the_duration_limit_downloads(tmp_path):
    path = run_download(
        make_job(tmp_path), lambda d: None, ytdlp_cls=fake_ydl({"duration": 600}), which=has_everything, max_duration_s=600
    )
    assert path.name == "Title [abc].mp4"


def test_video_over_the_duration_limit_fails_with_too_long(tmp_path):
    with pytest.raises(DownloadFailure) as exc:
        run_download(
            make_job(tmp_path), lambda d: None, ytdlp_cls=fake_ydl({"duration": 601}), which=has_everything, max_duration_s=600
        )
    assert exc.value.code == ErrorCode.TOO_LONG
    assert list(tmp_path.iterdir()) == []


def test_live_streams_are_rejected(tmp_path):
    with pytest.raises(DownloadFailure) as exc:
        run_download(
            make_job(tmp_path), lambda d: None, ytdlp_cls=fake_ydl({"is_live": True}), which=has_everything, max_duration_s=600
        )
    assert exc.value.code == ErrorCode.TOO_LONG


def test_unknown_duration_is_allowed(tmp_path):
    path = run_download(
        make_job(tmp_path), lambda d: None, ytdlp_cls=fake_ydl({}), which=has_everything, max_duration_s=600
    )
    assert path.exists()

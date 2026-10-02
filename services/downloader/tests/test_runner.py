from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode
from app.jobs import Job
from app.ytdlp_runner import find_output, run_download


def make_job(tmp_path, mode="video"):
    return Job(id="j", url="https://example.com/v", mode=mode, height="best", audio_format="mp3", dir=tmp_path)


def fake_ydl(error=None):
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
            if error is not None:
                raise error
            out = Path(self.opts["outtmpl"]).parent / "Title [abc].mp4"
            self.opts["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})
            self.opts["postprocessor_hooks"][0]({"status": "started"})
            out.write_bytes(b"x")

    return FakeYDL


def has_ffmpeg(_name):
    return "ffmpeg"


def test_run_download_returns_output_and_forwards_progress(tmp_path):
    events = []
    cls = fake_ydl()
    path = run_download(make_job(tmp_path), events.append, ytdlp_cls=cls, which=has_ffmpeg)
    assert path == tmp_path / "Title [abc].mp4"
    assert [e["status"] for e in events] == ["downloading", "processing"]
    assert cls.instances[0].opts["outtmpl"].startswith(str(tmp_path))


def test_missing_ffmpeg_fails_before_touching_yt_dlp(tmp_path):
    cls = fake_ydl()
    with pytest.raises(DownloadFailure) as exc:
        run_download(make_job(tmp_path), lambda d: None, ytdlp_cls=cls, which=lambda _n: None)
    assert exc.value.code == ErrorCode.FFMPEG_MISSING
    assert cls.instances == []


def test_download_error_is_mapped(tmp_path):
    cls = fake_ydl(DownloadError("ERROR: Unsupported URL: https://example.com/v"))
    with pytest.raises(DownloadFailure) as exc:
        run_download(make_job(tmp_path), lambda d: None, ytdlp_cls=cls, which=has_ffmpeg)
    assert exc.value.code == ErrorCode.UNSUPPORTED_SITE


def test_audio_job_passes_audio_options(tmp_path):
    cls = fake_ydl()
    run_download(make_job(tmp_path, "audio"), lambda d: None, ytdlp_cls=cls, which=has_ffmpeg)
    assert cls.instances[0].opts["postprocessors"][0]["preferredcodec"] == "mp3"


def test_find_output_ignores_partial_files_and_picks_largest(tmp_path):
    (tmp_path / "a.mp4.part").write_bytes(b"x" * 500)
    (tmp_path / "a.ytdl").write_bytes(b"x" * 500)
    (tmp_path / "small.mp4").write_bytes(b"x")
    (tmp_path / "big.mp4").write_bytes(b"xxxx")
    assert find_output(tmp_path) == tmp_path / "big.mp4"


def test_find_output_without_files_is_unknown_failure(tmp_path):
    (tmp_path / "only.part").write_bytes(b"x")
    with pytest.raises(DownloadFailure) as exc:
        find_output(tmp_path)
    assert exc.value.code == ErrorCode.UNKNOWN

"""Regression: HLS streams disguised behind a fake PNG were delivered as a .mp4 that Drive rejects.

yt-dlp only remuxes MPEG-TS to mp4 when ffprobe reports `mpegts`; with a 1x1 PNG glued in front,
ffprobe reports `png_pipe`, the fixup is skipped silently and the TS bytes stay in a `.mp4` file.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from app.errors import DownloadFailure, ErrorCode
from app.mp4_repair import find_ts_offset, is_mp4, repair_mp4

FAKE_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c636060606000000005 0001a5f6454000000000".replace(" ", "")
    + "49454e44ae426082"
)
TS_PACKET = b"\x47\x40\x00\x10" + b"\xff" * 184

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def make_ts(path: Path) -> bytes:
    """A real 1 s H.264+AAC MPEG-TS clip."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1",
         "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "libx264", "-c:a", "aac", "-f", "mpegts", str(path)],
        check=True,
    )
    return path.read_bytes()


def probe_format(path: Path) -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_find_ts_offset_skips_the_fake_png():
    assert find_ts_offset(FAKE_PNG + TS_PACKET * 5) == len(FAKE_PNG)


def test_find_ts_offset_is_zero_for_plain_ts():
    assert find_ts_offset(TS_PACKET * 5) == 0


def test_find_ts_offset_ignores_a_lone_sync_byte():
    assert find_ts_offset(b"\x47" + b"\x00" * 2000) is None


def test_is_mp4_checks_the_ftyp_box():
    assert is_mp4(b"\x00\x00\x00\x20ftypisom")
    assert not is_mp4(FAKE_PNG + TS_PACKET)


def test_a_real_mp4_is_left_untouched(tmp_path):
    f = tmp_path / "ok.mp4"
    f.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
    before = f.read_bytes()
    repair_mp4(f, run=lambda *a, **k: pytest.fail("ffmpeg must not run"))
    assert f.read_bytes() == before


def test_unknown_content_is_left_untouched(tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"x" * 5000)
    repair_mp4(f, run=lambda *a, **k: pytest.fail("ffmpeg must not run"))
    assert f.read_bytes() == b"x" * 5000


@needs_ffmpeg
def test_fake_png_plus_ts_becomes_a_real_mp4(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(FAKE_PNG + make_ts(tmp_path / "src.ts"))
    assert not is_mp4(f.read_bytes()[:16])
    repair_mp4(f)
    assert is_mp4(f.read_bytes()[:16])
    if shutil.which("ffprobe"):
        assert "mp4" in probe_format(f)
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".mp4"] == ["clip.mp4"]


@needs_ffmpeg
def test_plain_ts_in_mp4_name_is_also_repaired(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(make_ts(tmp_path / "src.ts"))
    repair_mp4(f)
    assert is_mp4(f.read_bytes()[:16])


@needs_ffmpeg
def test_failed_remux_raises_and_keeps_the_original(tmp_path):
    f = tmp_path / "clip.mp4"
    data = FAKE_PNG + TS_PACKET * 50  # valid sync pattern, no real streams: ffmpeg cannot build an mp4
    f.write_bytes(data)
    with pytest.raises(DownloadFailure) as exc:
        repair_mp4(f)
    assert exc.value.code == ErrorCode.UNKNOWN
    assert f.read_bytes() == data
    assert [p.name for p in tmp_path.iterdir()] == ["clip.mp4"]


def _runner_with_output(tmp_path, content: bytes, mode: str):
    from app.jobs import Job
    from app.ytdlp_runner import run_download

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            (Path(self.opts["outtmpl"]).parent / "Title [abc].mp4").write_bytes(content)

    job = Job(id="j", url="https://example.com/v", mode=mode, height="best", audio_format="mp3", dir=tmp_path)
    return run_download(job, lambda d: None, ytdlp_cls=FakeYDL, which=lambda _n: "ffmpeg")


@needs_ffmpeg
def test_run_download_delivers_a_real_mp4_for_video_jobs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    out_dir = tmp_path / "job"
    out_dir.mkdir()
    out = _runner_with_output(out_dir, FAKE_PNG + make_ts(src / "src.ts"), "video")
    assert out.name == "Title [abc].mp4"
    assert is_mp4(out.read_bytes()[:16])


@needs_ffmpeg
def test_run_download_leaves_audio_jobs_alone(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    out_dir = tmp_path / "job"
    out_dir.mkdir()
    data = FAKE_PNG + make_ts(src / "src.ts")
    out = _runner_with_output(out_dir, data, "audio")
    assert out.read_bytes() == data

import json
import threading
import time

import pytest

from app.errors import DownloadFailure, ErrorCode
from app.jobs import JobManager


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for condition")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def make_manager(tmp_path):
    made = []

    def _make(runner, **kwargs):
        manager = JobManager(tmp_path / f"base{len(made)}", runner, **kwargs)
        made.append(manager)
        return manager

    yield _make
    for manager in made:
        manager.shutdown()


def ok_runner(job, on_progress):
    path = job.dir / "out.mp4"
    path.write_bytes(b"x")
    return path


def test_successful_job_ends_done_with_file(make_manager):
    manager = make_manager(ok_runner)
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "done")
    assert job.filename == "out.mp4"
    assert job.percent == 100.0
    assert job.file_path.read_bytes() == b"x"
    assert job.snapshot()["error_code"] is None


def test_download_failure_is_reported_with_its_code(make_manager):
    def runner(job, on_progress):
        raise DownloadFailure(ErrorCode.GEO_BLOCKED)

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "error")
    assert job.error_code == "GEO_BLOCKED"
    assert job.error_message


def test_unexpected_exception_becomes_unknown_error(make_manager):
    def runner(job, on_progress):
        raise RuntimeError("boom")

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "audio")
    wait_for(lambda: job.status == "error")
    assert job.error_code == "UNKNOWN"


def test_progress_is_mapped_and_percent_never_goes_back(make_manager):
    mid, first, second = threading.Event(), threading.Event(), threading.Event()

    def runner(job, on_progress):
        on_progress({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 10.0, "eta": 5})
        on_progress({"status": "downloading", "downloaded_bytes": 20, "total_bytes": 100, "speed": 8.0, "eta": 9})
        mid.set()
        first.wait(3)
        on_progress({"status": "processing"})
        second.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    assert mid.wait(3)
    snap = job.snapshot()
    assert snap["status"] == "downloading"
    assert snap["percent"] == 50.0
    assert snap["speed"] == 8.0
    assert snap["eta"] == 9
    first.set()
    wait_for(lambda: job.status == "processing")
    assert job.speed is None
    second.set()
    wait_for(lambda: job.status == "done")
    assert job.percent == 100.0


def test_estimated_total_is_used_and_percent_is_capped_below_100(make_manager):
    mid, release = threading.Event(), threading.Event()

    def runner(job, on_progress):
        on_progress({"status": "downloading", "downloaded_bytes": 100, "total_bytes_estimate": 100})
        mid.set()
        release.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    assert mid.wait(3)
    assert job.percent < 100.0
    release.set()
    wait_for(lambda: job.status == "done")


def test_at_most_max_workers_run_at_once(make_manager):
    release = threading.Event()

    def runner(job, on_progress):
        release.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner, max_workers=2)
    jobs = [manager.create(f"https://example.com/{i}", "video") for i in range(3)]
    wait_for(lambda: sorted(j.status for j in jobs) == ["downloading", "downloading", "queued"])
    assert len({j.dir for j in jobs}) == 3
    release.set()
    wait_for(lambda: all(j.status == "done" for j in jobs))


def test_cleanup_removes_only_expired_finished_jobs(make_manager):
    clock = Clock()
    hold = threading.Event()

    def runner(job, on_progress):
        if job.url.endswith("/slow"):
            hold.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner, ttl_seconds=100, clock=clock)
    fast = manager.create("https://example.com/fast", "video")
    slow = manager.create("https://example.com/slow", "audio")
    wait_for(lambda: fast.status == "done")

    clock.t += 99
    assert manager.cleanup() == 0
    assert fast.dir.exists()

    clock.t += 2
    assert manager.cleanup() == 1
    assert manager.get(fast.id) is None
    assert not fast.dir.exists()
    assert manager.get(slow.id) is not None
    assert slow.dir.exists()
    hold.set()


def test_get_unknown_job_returns_none(make_manager):
    assert make_manager(ok_runner).get("nope") is None


def test_finished_job_is_logged_without_the_full_url(make_manager, tmp_path):
    log = tmp_path / "jobs.log"
    manager = make_manager(ok_runner, log_path=log)
    job = manager.create("https://example.com/watch?v=secret", "video")
    wait_for(lambda: job.status == "done")
    text = log.read_text(encoding="utf-8")
    entry = json.loads(text.splitlines()[0])
    assert entry["host"] == "example.com"
    assert entry["status"] == "done"
    assert entry["mode"] == "video"
    assert entry["job_id"] == job.id
    assert "duration_s" in entry
    assert "secret" not in text


def test_failed_job_log_has_error_code(make_manager, tmp_path):
    def runner(job, on_progress):
        raise DownloadFailure(ErrorCode.NETWORK)

    log = tmp_path / "jobs.log"
    manager = make_manager(runner, log_path=log)
    job = manager.create("https://example.com/v", "audio")
    wait_for(lambda: job.status == "error")
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert entry["status"] == "error"
    assert entry["error_code"] == "NETWORK"


def test_crash_log_never_contains_the_url(make_manager, caplog):
    def leaking(job, on_progress):
        raise RuntimeError("https://secret.example/x?token=abc")

    manager = make_manager(leaking)
    with caplog.at_level("DEBUG"):
        job = manager.create("https://secret.example/x?token=abc", "video")
        wait_for(lambda: job.status == "error")
    assert "secret.example" not in caplog.text
    assert "token=abc" not in caplog.text
    assert "RuntimeError" in caplog.text

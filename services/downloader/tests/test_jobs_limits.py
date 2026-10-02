"""Queue cap, size and disk limits, cancellation and immediate cleanup of failed jobs."""
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


def blocking_runner(release):
    def runner(job, on_progress):
        release.wait(3)
        return ok_runner(job, on_progress)

    return runner


class Usage:
    def __init__(self, free):
        self.free = free


def test_queue_cap_rejects_the_next_job_with_queue_full(make_manager):
    release = threading.Event()
    manager = make_manager(blocking_runner(release), max_workers=1, max_queue=2)
    manager.create("https://example.com/1", "video")
    manager.create("https://example.com/2", "video")
    with pytest.raises(DownloadFailure) as exc:
        manager.create("https://example.com/3", "video")
    assert exc.value.code == ErrorCode.QUEUE_FULL
    release.set()


def test_a_finished_job_frees_its_queue_slot(make_manager):
    manager = make_manager(ok_runner, max_workers=1, max_queue=1)
    first = manager.create("https://example.com/1", "video")
    wait_for(lambda: first.status == "done")
    second = manager.create("https://example.com/2", "video")
    wait_for(lambda: second.status == "done")


def test_queue_cap_holds_under_concurrent_creates(make_manager):
    release = threading.Event()
    manager = make_manager(blocking_runner(release), max_workers=2, max_queue=5)
    accepted, rejected = [], []

    def attempt(i):
        try:
            accepted.append(manager.create(f"https://example.com/{i}", "video"))
        except DownloadFailure as failure:
            rejected.append(failure.code)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(accepted) == 5
    assert set(rejected) == {ErrorCode.QUEUE_FULL} and len(rejected) == 15
    release.set()


def test_create_is_refused_when_free_disk_is_below_the_minimum(make_manager):
    manager = make_manager(ok_runner, min_free_disk_bytes=1000, disk_usage=lambda _p: Usage(999))
    with pytest.raises(DownloadFailure) as exc:
        manager.create("https://example.com/v", "video")
    assert exc.value.code == ErrorCode.DISK_FULL
    assert list(manager.base_dir.iterdir()) == []  # nothing was created


def test_disk_running_out_mid_download_stops_the_job_and_frees_its_files(make_manager):
    free = {"value": 5000}

    def runner(job, on_progress):
        (job.dir / "partial.part").write_bytes(b"x")
        free["value"] = 10
        on_progress({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 100})
        raise AssertionError("must have been aborted by the progress hook")

    manager = make_manager(runner, min_free_disk_bytes=1000, disk_usage=lambda _p: Usage(free["value"]))
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "error")
    assert job.error_code == "DISK_FULL"
    assert not job.dir.exists()


@pytest.mark.parametrize("field", ["total_bytes", "total_bytes_estimate", "downloaded_bytes"])
def test_file_larger_than_the_limit_is_aborted(make_manager, field):
    def runner(job, on_progress):
        on_progress({"status": "downloading", field: 5000})
        raise AssertionError("must have been aborted by the progress hook")

    manager = make_manager(runner, max_filesize_bytes=1000)
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "error")
    assert job.error_code == "TOO_LARGE"


def test_file_within_the_limit_is_not_touched(make_manager):
    def runner(job, on_progress):
        on_progress({"status": "downloading", "downloaded_bytes": 1000, "total_bytes": 1000})
        return ok_runner(job, on_progress)

    manager = make_manager(runner, max_filesize_bytes=1000)
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "done")


def test_cancel_a_running_job(make_manager):
    started = threading.Event()

    def runner(job, on_progress):
        (job.dir / "partial.part").write_bytes(b"x")
        started.set()
        while True:
            time.sleep(0.01)
            on_progress({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 100})

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    assert started.wait(3)
    assert manager.cancel(job.id) is job
    wait_for(lambda: job.status == "cancelled")
    assert job.error_code == "CANCELLED"
    assert not job.dir.exists()


def test_cancel_a_queued_job_means_it_never_runs(make_manager):
    release = threading.Event()
    ran = []

    def runner(job, on_progress):
        ran.append(job.url)
        release.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner, max_workers=1)
    first = manager.create("https://example.com/first", "video")
    wait_for(lambda: first.status == "downloading")
    queued = manager.create("https://example.com/queued", "video")
    manager.cancel(queued.id)
    wait_for(lambda: queued.status == "cancelled")
    assert not queued.dir.exists()
    release.set()
    wait_for(lambda: first.status == "done")
    assert ran == ["https://example.com/first"]


def test_cancel_during_post_processing_discards_the_result(make_manager):
    reached, go = threading.Event(), threading.Event()

    def runner(job, on_progress):
        on_progress({"status": "processing"})
        reached.set()
        go.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    assert reached.wait(3)
    manager.cancel(job.id)
    go.set()
    wait_for(lambda: job.status == "cancelled")
    assert not job.dir.exists()


def test_cancel_a_finished_job_discards_it_and_its_file(make_manager):
    manager = make_manager(ok_runner)
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "done")
    assert manager.cancel(job.id) is job
    assert manager.get(job.id) is None
    assert not job.dir.exists()


def test_cancel_unknown_job_returns_none(make_manager):
    assert make_manager(ok_runner).cancel("nope") is None


def test_failed_job_deletes_its_partial_files_immediately(make_manager):
    def runner(job, on_progress):
        (job.dir / "video.mp4.part").write_bytes(b"x" * 10)
        raise DownloadFailure(ErrorCode.NETWORK)

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "error")
    assert not job.dir.exists()
    assert manager.get(job.id) is job  # the record stays so the page can read the error

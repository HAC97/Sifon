"""HTTP surface of the limits: 429 queue full, 507 disk full, DELETE to cancel, health values."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import JobManager
from app.main import create_app


def fake_info(url):
    return {"title": "T", "thumbnail": None, "duration": 12, "uploader": "U", "heights": [720]}


class Usage:
    def __init__(self, free):
        self.free = free


@pytest.fixture
def make_client(tmp_path):
    managers = []

    def _make(runner, **manager_kwargs):
        manager = JobManager(tmp_path / f"jobs{len(managers)}", runner, **manager_kwargs)
        managers.append(manager)
        app = create_app(
            manager=manager,
            info_fetcher=fake_info,
            url_validator=lambda u: u,
            serve_web=False,
            settings=Settings(max_filesize_mb=5, max_duration_min=7, max_concurrent=1, max_queue=2),
        )
        return TestClient(app, base_url="http://127.0.0.1")

    yield _make
    for manager in managers:
        manager.shutdown()


def done_runner(job, on_progress):
    path = job.dir / "out.mp4"
    path.write_bytes(b"x")
    return path


def wait_status(client, job_id, wanted, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] == wanted:
            return body
        time.sleep(0.01)
    raise AssertionError(f"job never reached {wanted}")


def start(client, name="a"):
    return client.post("/api/jobs", json={"url": f"https://example.com/{name}", "mode": "video"})


def test_health_reports_version_tools_and_limits(make_client):
    body = make_client(done_runner).get("/api/health").json()
    assert body["version"]
    assert isinstance(body["ffprobe"], bool)
    assert body["js_runtime"] in (None, "deno", "node")
    assert (body["max_filesize_mb"], body["max_duration_min"]) == (5, 7)
    assert (body["max_concurrent"], body["max_queue"]) == (1, 2)


def test_queue_full_is_429_with_its_code(make_client):
    release = threading.Event()

    def blocked(job, on_progress):
        release.wait(3)
        return done_runner(job, on_progress)

    client = make_client(blocked, max_workers=1, max_queue=2)
    assert start(client, "1").status_code == 202
    assert start(client, "2").status_code == 202
    res = start(client, "3")
    assert res.status_code == 429
    assert res.json()["error_code"] == "QUEUE_FULL"
    release.set()


def test_disk_full_is_507_with_its_code(make_client):
    client = make_client(done_runner, min_free_disk_bytes=1000, disk_usage=lambda _p: Usage(1))
    res = start(client)
    assert res.status_code == 507
    assert res.json()["error_code"] == "DISK_FULL"


def test_delete_cancels_a_running_job(make_client):
    started = threading.Event()

    def forever(job, on_progress):
        started.set()
        while True:
            time.sleep(0.01)
            on_progress({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 9})

    client = make_client(forever)
    job_id = start(client).json()["job_id"]
    assert started.wait(3)
    res = client.delete(f"/api/jobs/{job_id}")
    assert res.status_code == 200
    body = wait_status(client, job_id, "cancelled")
    assert body["error_code"] == "CANCELLED"
    assert client.get(f"/api/jobs/{job_id}/file").status_code == 409


def test_delete_a_finished_job_removes_it(make_client):
    client = make_client(done_runner)
    job_id = start(client).json()["job_id"]
    wait_status(client, job_id, "done")
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/file").status_code == 404


def test_delete_unknown_job_is_404(make_client):
    assert make_client(done_runner).delete("/api/jobs/nope").status_code == 404


def test_delete_from_another_origin_is_403_and_cancels_nothing(make_client):
    started = threading.Event()
    release = threading.Event()

    def runner(job, on_progress):
        started.set()
        release.wait(3)
        return done_runner(job, on_progress)

    client = make_client(runner)
    job_id = start(client).json()["job_id"]
    assert started.wait(3)
    res = client.delete(f"/api/jobs/{job_id}", headers={"Origin": "http://evil.example"})
    assert res.status_code == 403
    release.set()
    wait_status(client, job_id, "done")

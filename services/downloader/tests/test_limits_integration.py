"""Limits and the egress block exercised with the real yt-dlp against a local slow server.

No internet involved. The generic extractor downloads a direct .mp4 link, which needs no ffmpeg
(single format, no merge), so run_download is given a `which` that pretends ffmpeg exists.
"""
import http.server
import shutil
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobManager
from app.main import create_app
from app.ytdlp_runner import run_download

TOTAL = 40 * 1024 * 1024
CHUNK = b"\0" * 65536


class _SlowHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _head(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(TOTAL))
        self.end_headers()

    def do_HEAD(self):
        self._head()

    def do_GET(self):
        self._head()
        sent = 0
        try:
            while sent < TOTAL:
                self.wfile.write(CHUNK)
                sent += len(CHUNK)
                time.sleep(0.005)
        except OSError:
            pass  # the client gave up (cancelled or over the limit)

    def log_message(self, *args):
        pass


class _Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # a client that disconnects mid-stream is the point of these tests

    def server_bind(self):
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = self.server_address[0], self.server_address[1]


@pytest.fixture
def slow_url():
    httpd = _Server(("127.0.0.1", 0), _SlowHandler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/big.mp4"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def make_manager(tmp_path):
    made = []

    def _make(**kwargs):
        def runner(job, on_progress):
            return run_download(job, on_progress, which=lambda _n: "ffmpeg")

        manager = JobManager(tmp_path / f"base{len(made)}", runner, **kwargs)
        made.append(manager)
        return manager

    yield _make
    for manager in made:
        manager.shutdown()


def wait_for(predicate, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for condition")


def test_real_download_completes_without_limits(make_manager, slow_url):
    manager = make_manager()
    job = manager.create(slow_url, "video")
    wait_for(lambda: job.status in ("done", "error"))
    assert job.status == "done", job.error_message
    assert job.file_path.stat().st_size == TOTAL


def test_a_file_over_the_size_limit_is_aborted_and_leaves_nothing_behind(make_manager, slow_url):
    manager = make_manager(max_filesize_bytes=5 * 1024 * 1024)
    job = manager.create(slow_url, "video")
    wait_for(lambda: job.status in ("done", "error"))
    assert (job.status, job.error_code) == ("error", "TOO_LARGE")
    assert not job.dir.exists()


def test_cancelling_a_real_download_stops_it_and_deletes_the_partial_file(make_manager, slow_url):
    manager = make_manager()
    job = manager.create(slow_url, "video")
    wait_for(lambda: job.percent > 0)
    manager.cancel(job.id)
    wait_for(lambda: job.status in ("done", "error", "cancelled"))
    assert job.status == "cancelled"
    assert not job.dir.exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="the app refuses downloads without ffmpeg")
def test_the_assembled_app_blocks_a_private_url_even_if_the_validator_lets_it_through(slow_url, monkeypatch):
    """create_app wires the proxy into yt-dlp: a loopback target dies with BLOCKED_ADDRESS."""
    monkeypatch.setenv("SIFON_MIN_FREE_DISK_MB", "1")
    app = create_app(url_validator=lambda u: u, serve_web=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        job_id = client.post("/api/jobs", json={"url": slow_url, "mode": "video"}).json()["job_id"]
        deadline = time.time() + 30
        body = {}
        while time.time() < deadline:
            body = client.get(f"/api/jobs/{job_id}").json()
            if body["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert body["status"] == "error"
        assert body["error_code"] == "BLOCKED_ADDRESS"
        info = client.post("/api/info", json={"url": slow_url})
        assert info.status_code == 400
        assert info.json()["error_code"] == "BLOCKED_ADDRESS"

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.errors import DownloadFailure, ErrorCode
from app.jobs import JobManager
from app.main import create_app
from app.urlcheck import validate_url

NASTY_NAME = "Canción ñ 😀 [abc].mp4"


def fake_info(url):
    return {"title": "T", "thumbnail": None, "duration": 12, "uploader": "U", "heights": [1080, 720]}


def ok_runner(job, on_progress):
    on_progress({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2, "speed": 1.0, "eta": 1})
    path = job.dir / NASTY_NAME
    path.write_bytes(b"data")
    return path


@pytest.fixture
def make_client(tmp_path):
    managers = []

    def _make(runner=ok_runner, **overrides):
        manager = JobManager(tmp_path / f"jobs{len(managers)}", runner)
        managers.append(manager)
        app = create_app(
            manager=manager,
            info_fetcher=overrides.get("info_fetcher", fake_info),
            url_validator=overrides.get("url_validator", lambda u: u),
            serve_web=False,
        )
        return TestClient(app)

    yield _make
    for manager in managers:
        manager.shutdown()


def wait_done(client, job_id, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_health(make_client):
    body = make_client().get("/api/health").json()
    assert body["ok"] is True
    assert body["ytdlp_version"]
    assert isinstance(body["ffmpeg"], bool)


def test_info_returns_summary(make_client):
    res = make_client().post("/api/info", json={"url": "https://example.com/v"})
    assert res.status_code == 200
    assert res.json()["heights"] == [1080, 720]


def test_info_failure_maps_to_400_with_code(make_client):
    def failing(url):
        raise DownloadFailure(ErrorCode.UNSUPPORTED_SITE)

    res = make_client(info_fetcher=failing).post("/api/info", json={"url": "https://example.com/v"})
    assert res.status_code == 400
    assert res.json()["error_code"] == "UNSUPPORTED_SITE"
    assert res.json()["error_message"]


def test_info_unexpected_exception_maps_to_400_unknown(make_client):
    def exploding(url):
        raise RuntimeError("boom")

    res = make_client(info_fetcher=exploding).post("/api/info", json={"url": "https://example.com/v"})
    assert res.status_code == 400
    assert res.json()["error_code"] == "UNKNOWN"


def test_info_unexpected_exception_never_leaks_url_to_log_or_body(make_client, caplog):
    def leaking(url):
        raise RuntimeError("https://secret.example/x?token=abc")

    with caplog.at_level("DEBUG"):
        res = make_client(info_fetcher=leaking).post("/api/info", json={"url": "https://example.com/v"})
    assert res.status_code == 400
    for leaked in ("secret.example", "token=abc"):
        assert leaked not in caplog.text
        assert leaked not in res.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("bad", ["youtube.com/watch?v=1", "", "ftp://x.com/a", "https://exa mple.com/"])
def test_malformed_urls_are_400_invalid_url_not_500(make_client, bad):
    client = make_client(url_validator=validate_url)
    for path, payload in (
        ("/api/info", {"url": bad}),
        ("/api/jobs", {"url": bad, "mode": "video"}),
    ):
        res = client.post(path, json=payload)
        assert res.status_code == 400
        assert res.json()["error_code"] == "INVALID_URL"


def test_private_host_is_blocked_at_the_api(make_client):
    import socket

    def to_loopback(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    client = make_client(url_validator=lambda u: validate_url(u, resolver=to_loopback))
    res = client.post("/api/jobs", json={"url": "https://innocent.example/v", "mode": "video"})
    assert res.status_code == 400
    assert res.json()["error_code"] == "INVALID_URL"


def test_job_lifecycle_and_file_download_with_unicode_name(make_client):
    client = make_client()
    res = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "video", "height": "720"})
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    status = wait_done(client, job_id)
    assert status["status"] == "done"
    assert status["filename"] == NASTY_NAME
    assert status["percent"] == 100.0

    file_res = client.get(f"/api/jobs/{job_id}/file")
    assert file_res.status_code == 200
    assert file_res.content == b"data"
    disposition = file_res.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert "Canci%C3%B3n" in disposition


def test_failed_job_reports_error_fields(make_client):
    def runner(job, on_progress):
        raise DownloadFailure(ErrorCode.GEO_BLOCKED)

    client = make_client(runner=runner)
    job_id = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "audio"}).json()["job_id"]
    status = wait_done(client, job_id)
    assert status["status"] == "error"
    assert status["error_code"] == "GEO_BLOCKED"
    assert client.get(f"/api/jobs/{job_id}/file").status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "https://example.com/v", "mode": "gif"},
        {"url": "https://example.com/v", "mode": "video", "height": "999"},
        {"url": "https://example.com/v", "mode": "audio", "audio_format": "wav"},
        {"mode": "video"},
    ],
)
def test_invalid_job_request_is_422(make_client, payload):
    assert make_client().post("/api/jobs", json=payload).status_code == 422


def test_unknown_and_traversal_shaped_ids_are_404(make_client):
    client = make_client()
    for job_id in ("nope", "..%2Fsecret", "%2E%2E", "a" * 500):
        assert client.get(f"/api/jobs/{job_id}").status_code == 404
        assert client.get(f"/api/jobs/{job_id}/file").status_code == 404


def test_file_before_done_is_409(make_client):
    release = threading.Event()

    def slow(job, on_progress):
        release.wait(3)
        return ok_runner(job, on_progress)

    client = make_client(runner=slow)
    job_id = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "video"}).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}/file").status_code == 409
    release.set()
    assert wait_done(client, job_id)["status"] == "done"

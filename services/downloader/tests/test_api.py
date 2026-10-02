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
            **({"allowed_hosts": overrides["allowed_hosts"]} if "allowed_hosts" in overrides else {}),
        )
        return TestClient(app, base_url="http://127.0.0.1")

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


def test_lifespan_starts_the_sweeper_and_shutdown_removes_the_base_dir(tmp_path):
    manager = JobManager(tmp_path / "lifespan", ok_runner)
    app = create_app(manager=manager, info_fetcher=fake_info, url_validator=lambda u: u, serve_web=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        assert manager.base_dir.exists()
        assert manager._sweeper is not None and manager._sweeper.is_alive()
    assert not manager.base_dir.exists()


INFO_BODY = {"url": "https://example.com/v"}


@pytest.mark.parametrize("method, path", [("get", "/api/health"), ("post", "/api/info")])
def test_foreign_host_header_is_403(make_client, method, path):
    kwargs = {"json": INFO_BODY} if method == "post" else {}
    res = getattr(make_client(), method)(path, headers={"Host": "evil.example"}, **kwargs)
    assert res.status_code == 403
    assert res.json() == {"detail": "host not allowed"}


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost", "LOCALHOST:1", "[::1]:8000", "127.0.0.1"])
def test_loopback_host_headers_are_accepted(make_client, host):
    assert make_client().get("/api/health", headers={"Host": host}).status_code == 200


def test_cross_origin_post_is_403(make_client):
    res = make_client().post("/api/info", json=INFO_BODY, headers={"Origin": "http://evil.example"})
    assert res.status_code == 403
    assert res.json() == {"detail": "origin not allowed"}


def test_cross_origin_job_creation_is_403_and_creates_nothing(make_client):
    res = make_client().post(
        "/api/jobs", json={**INFO_BODY, "mode": "video"}, headers={"Origin": "https://evil.example:8765"}
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"},
        {"Origin": "http://localhost", "Host": "localhost"},
        {"Origin": "http://LOCALHOST:9000", "Host": "localhost:9000"},
        {"Origin": "http://[::1]:8000", "Host": "[::1]:8000"},
        {},
    ],
)
def test_same_origin_or_missing_origin_post_is_accepted(make_client, headers):
    assert make_client().post("/api/info", json=INFO_BODY, headers=headers).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        # another web app on localhost, different port: local, but not the page that owns this API
        {"Origin": "http://localhost:3000", "Host": "127.0.0.1:8765"},
        {"Origin": "http://127.0.0.1:3000", "Host": "127.0.0.1:8765"},
        # same port, different local name
        {"Origin": "http://localhost:8765", "Host": "127.0.0.1:8765"},
        # port omitted on one side only
        {"Origin": "http://127.0.0.1", "Host": "127.0.0.1:8765"},
        {"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1"},
        # https origin against a plain-http server
        {"Origin": "https://127.0.0.1", "Host": "127.0.0.1"},
    ],
)
def test_post_from_another_local_origin_is_403(make_client, headers):
    res = make_client().post("/api/info", json=INFO_BODY, headers=headers)
    assert res.status_code == 403
    assert res.json() == {"detail": "origin not allowed"}


@pytest.mark.parametrize("host", ["127.0.0.1:evil.com", "127.0.0.1:80@evil.com", "[::1]x"])
def test_malformed_host_headers_are_403(make_client, host):
    assert make_client().get("/api/health", headers={"Host": host}).status_code == 403


def test_origin_is_not_checked_on_get(make_client):
    res = make_client().get("/api/health", headers={"Origin": "http://evil.example"})
    assert res.status_code == 200


def test_null_origin_post_is_403(make_client):
    assert make_client().post("/api/info", json=INFO_BODY, headers={"Origin": "null"}).status_code == 403


def test_custom_allowed_hosts_are_honored(make_client):
    client = make_client(allowed_hosts=("vd.test",))
    assert client.get("/api/health", headers={"Host": "vd.test:80"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "127.0.0.1"}).status_code == 403
    assert client.post("/api/info", json=INFO_BODY, headers={"Host": "vd.test", "Origin": "http://vd.test"}).status_code == 200


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

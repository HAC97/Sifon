"""Regression tests for the findings of the independent security review (F1-F6)."""
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import app.jobs as jobs_module
from app.config import SettingsError, load_settings
from app.egress_proxy import EgressProxy
from app.formats import FFMPEG_INPUT_PROTOCOLS, ytdlp_options
from app.jobs import JobManager

PUBLIC = "127.0.0.1"


def allow_only_public(ip) -> bool:
    return str(ip) != PUBLIC


def resolver(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port))]


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for condition")


# --- F1: a page that never ends must not be buffered without bound -------------------------------


def test_the_proxy_cuts_a_response_that_never_ends_at_the_byte_cap():
    sent = {"bytes": 0}
    server = socket.socket()
    server.bind((PUBLIC, 0))
    server.listen(1)
    port = server.getsockname()[1]
    stop = threading.Event()

    def endless():
        conn, _ = server.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
        chunk = b"x" * 65536
        try:
            while not stop.is_set():
                conn.sendall(chunk)
                sent["bytes"] += len(chunk)
        except OSError:
            pass
        finally:
            conn.close()

    threading.Thread(target=endless, daemon=True).start()
    cap = 1024 * 1024
    proxy = EgressProxy(resolver=resolver, is_blocked=allow_only_public, max_response_bytes=cap)
    proxy.start()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy.url}))
        received = 0
        with opener.open(f"http://endless.test:{port}/", timeout=10) as res:
            try:
                while chunk := res.read(65536):
                    received += len(chunk)
            except Exception:  # the proxy closes the connection: a truncated body is the expected end
                pass
        assert received <= cap + 65536 * 2, received
        wait_for(lambda: sent["bytes"] < 200 * 1024 * 1024, 5)
        assert sent["bytes"] < 100 * 1024 * 1024  # the upstream was cut off, not drained forever
    finally:
        stop.set()
        proxy.stop()
        server.close()


def test_a_response_within_the_cap_passes_untouched():
    server = socket.socket()
    server.bind((PUBLIC, 0))
    server.listen(1)
    port = server.getsockname()[1]
    body = b"y" * 100_000

    def serve():
        conn, _ = server.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    proxy = EgressProxy(resolver=resolver, is_blocked=allow_only_public, max_response_bytes=1024 * 1024)
    proxy.start()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy.url}))
        with opener.open(f"http://small.test:{port}/", timeout=10) as res:
            assert res.read() == body
    finally:
        proxy.stop()
        server.close()


def test_the_assembled_app_caps_downloads_at_the_file_size_limit_and_info_at_a_small_page_size():
    from app.config import Settings
    from app.main import INFO_RESPONSE_CAP, create_app

    app = create_app(settings=Settings(max_filesize_mb=7), serve_web=False)
    assert app.state.egress._max_response == 7 * 1024 * 1024
    assert app.state.info_egress._max_response == INFO_RESPONSE_CAP
    assert INFO_RESPONSE_CAP <= 64 * 1024 * 1024


def test_both_proxies_start_and_stop_with_the_app():
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(serve_web=False)
    with TestClient(app, base_url="http://127.0.0.1"):
        ports = {app.state.egress.port, app.state.info_egress.port}
        assert None not in ports and len(ports) == 2
    assert app.state.egress.port is None and app.state.info_egress.port is None


def test_server_entry_point_routes_children_through_the_proxy_and_restores_the_environment(monkeypatch):
    import os

    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("HTTPS_PROXY", "http://corp:3128")
    app = create_app(serve_web=False, route_environment=True)
    with TestClient(app, base_url="http://127.0.0.1"):
        assert os.environ["HTTPS_PROXY"] == os.environ["HTTP_PROXY"] == app.state.egress.url
        assert "NO_PROXY" not in os.environ
    assert os.environ["NO_PROXY"] == "127.0.0.1" and os.environ["HTTPS_PROXY"] == "http://corp:3128"


# --- F2: ffmpeg is a child process with its own networking ---------------------------------------


def test_ffmpeg_inputs_are_limited_to_plain_http_protocols():
    opts = ytdlp_options("video", "best", "mp3", "out", lambda d: None)
    args = opts["external_downloader_args"]["ffmpeg_i"]
    assert args == ["-protocol_whitelist", FFMPEG_INPUT_PROTOCOLS]
    allowed = set(FFMPEG_INPUT_PROTOCOLS.split(","))
    assert "httpproxy" not in allowed and "file" not in allowed and "rtmp" not in allowed


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_hls_manifest_cannot_make_ffmpeg_connect_to_a_private_address(tmp_path):
    """A public manifest (SAMPLE-AES, so yt-dlp hands it to ffmpeg) whose segment is
    httpproxy://<private host>: ffmpeg used to connect there directly, around the proxy."""
    import http.server

    from app.jobs import Job
    from app.ytdlp_runner import run_download

    private_hits = []

    def private_listener():
        s = socket.socket()
        s.bind(("127.0.0.2", 0))
        s.listen(5)

        def accept():
            while True:
                try:
                    conn, _ = s.accept()
                except OSError:
                    return
                conn.settimeout(2)
                try:
                    private_hits.append(conn.recv(200))
                except OSError:
                    private_hits.append(b"")
                conn.close()

        threading.Thread(target=accept, daemon=True).start()
        return s

    private = private_listener()
    private_port = private.getsockname()[1]

    class Manifest(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/k":
                body, kind = b"0" * 16, "application/octet-stream"
            else:
                body = (
                    "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:5\n"
                    '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="k"\n#EXTINF:4,\n'
                    f"httpproxy://127.0.0.2:{private_port}/s.ts\n#EXT-X-ENDLIST\n"
                ).encode()
                kind = "application/vnd.apple.mpegurl"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer((PUBLIC, 0), Manifest)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    proxy = EgressProxy(resolver=resolver, is_blocked=allow_only_public)
    proxy.start()
    try:
        job = Job(
            id="x", url=f"http://public.test:{httpd.server_address[1]}/a.m3u8", mode="video",
            height="best", audio_format="mp3", dir=tmp_path,
        )
        try:
            run_download(job, lambda d: None, proxy=proxy.url)
        except Exception:
            pass  # failing is the expected outcome; what matters is that nothing reached the private host
        time.sleep(0.5)
        assert private_hits == [], private_hits
    finally:
        proxy.stop()
        httpd.shutdown()
        httpd.server_close()
        private.close()


# --- F4: Windows cannot delete a file a client is still reading ---------------------------------


def test_a_folder_that_cannot_be_deleted_yet_is_retried_on_the_next_sweep(tmp_path, monkeypatch):
    manager = JobManager(tmp_path / "base", lambda job, cb: job.dir / "x", ttl_seconds=0)
    try:
        folder = manager.base_dir / "job1"
        folder.mkdir()
        (folder / "video.mp4").write_bytes(b"x")
        real_rmtree = shutil.rmtree
        locked = {"on": True}

        def flaky(path, *a, **k):
            if locked["on"] and Path(path) == folder:
                return  # a client holds the file open: nothing gets deleted, no exception either
            return real_rmtree(path, *a, **k)

        monkeypatch.setattr(jobs_module.shutil, "rmtree", flaky)
        manager._discard(folder)
        assert folder.exists() and folder in manager._undeleted
        locked["on"] = False  # the client finished
        manager.cleanup()
        assert not folder.exists() and not manager._undeleted
    finally:
        manager.shutdown()


# --- F6 and the new memory setting -------------------------------------------------------------


@pytest.mark.parametrize("target", ["GET http://example.com:99999/ HTTP/1.1", "GET http://example.com:abc/ HTTP/1.1"])
def test_a_bad_port_in_the_proxy_request_gets_400_not_a_traceback(target):
    proxy = EgressProxy(resolver=resolver, is_blocked=allow_only_public)
    proxy.start()
    try:
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as sock:
            sock.sendall(f"{target}\r\nHost: x\r\n\r\n".encode())
            assert sock.recv(1024).startswith(b"HTTP/1.1 400")
    finally:
        proxy.stop()


def test_memory_limit_setting_has_a_sane_default_and_is_validated():
    assert load_settings({}).max_memory_mb == 4096
    assert load_settings({"SIFON_MAX_MEMORY_MB": "2048"}).max_memory_bytes == 2048 * 1024 * 1024
    with pytest.raises(SettingsError, match="SIFON_MAX_MEMORY_MB"):
        load_settings({"SIFON_MAX_MEMORY_MB": "0"})

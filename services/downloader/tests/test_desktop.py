"""Desktop launcher logic: ports, single instance, server thread, update checks, real start/stop."""
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import desktop
from app.jobs import JobManager
from app.main import create_app

SERVICE_DIR = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- ports ------------------------------------------------------------------------------------


def test_the_preferred_port_is_used_when_free():
    assert desktop.choose_port(8000, 20, is_free=lambda p: True) == 8000


def test_the_next_free_port_is_used_when_the_preferred_one_is_busy():
    assert desktop.choose_port(8000, 20, is_free=lambda p: p >= 8003) == 8003


def test_any_free_port_is_used_when_the_whole_span_is_busy():
    port = desktop.choose_port(8000, 20, is_free=lambda p: False)
    assert 1024 <= port <= 65535 and not (8000 <= port < 8020)


def test_a_port_in_use_is_reported_busy():
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        assert desktop.port_is_free(holder.getsockname()[1]) is False
    assert desktop.port_is_free(free_port()) is True


# --- single instance --------------------------------------------------------------------------


def test_no_instance_file_means_nothing_is_running(tmp_path):
    assert desktop.find_running(tmp_path, health=lambda p: {"ok": True}) is None


def test_a_live_instance_is_found_through_its_health_endpoint(tmp_path):
    desktop.write_instance(tmp_path, 8123)
    assert desktop.find_running(tmp_path, health=lambda p: {"ok": True} if p == 8123 else None) == 8123


def test_a_stale_instance_file_is_ignored(tmp_path):
    desktop.write_instance(tmp_path, 8123)
    assert desktop.find_running(tmp_path, health=lambda p: None) is None


def test_a_corrupt_instance_file_is_ignored(tmp_path):
    (tmp_path / desktop.INSTANCE_FILE).write_text("{not json", encoding="utf-8")
    assert desktop.find_running(tmp_path, health=lambda p: {"ok": True}) is None


def test_health_ignores_proxy_variables_because_the_server_sets_them_to_a_proxy_that_refuses_loopback(quiet_factory, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")  # a dead proxy: any use of it would fail
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    port = free_port()
    server = desktop.ServerThread(quiet_factory, port)
    server.start()
    try:
        assert server.wait_ready(15)
        assert desktop.fetch_health(port)["ok"] is True
    finally:
        server.stop()


def test_health_of_something_that_is_not_sifon_does_not_count():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        assert desktop.fetch_health(s.getsockname()[1], timeout=0.3) is None


# --- the server thread --------------------------------------------------------------------------


@pytest.fixture
def quiet_factory(tmp_path):
    managers = []

    def factory():
        manager = JobManager(tmp_path / "jobs", lambda job, cb: job.dir)
        managers.append(manager)
        return create_app(manager=manager, info_fetcher=lambda u: {}, url_validator=lambda u: u, serve_web=True)

    yield factory
    for manager in managers:
        manager.shutdown()


def test_the_server_thread_starts_answers_health_serves_the_page_and_stops(quiet_factory):
    port = free_port()
    server = desktop.ServerThread(quiet_factory, port)
    server.start()
    try:
        assert server.wait_ready(15)
        assert desktop.fetch_health(port)["ok"] is True
        assert server.active_jobs() == 0
        import urllib.request

        assert b"sif" in urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
    finally:
        server.stop()
    assert desktop.fetch_health(port, timeout=0.5) is None


def test_a_factory_that_fails_surfaces_the_error_instead_of_hanging():
    def broken():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        desktop.ServerThread(broken, free_port()).start()


def test_active_jobs_counts_running_downloads(tmp_path):
    import threading

    release = threading.Event()
    manager = JobManager(tmp_path / "jobs", lambda job, cb: (release.wait(5), job.dir)[1])
    server = desktop.ServerThread(
        lambda: create_app(manager=manager, info_fetcher=lambda u: {}, url_validator=lambda u: u, serve_web=False),
        free_port(),
    )
    server.start()
    try:
        assert server.wait_ready(15)
        manager.create("https://example.com/v", "video")
        deadline = time.time() + 3
        while server.active_jobs() == 0 and time.time() < deadline:
            time.sleep(0.02)
        assert server.active_jobs() == 1
    finally:
        release.set()
        server.stop()
        manager.shutdown()


# --- update checks from the window ----------------------------------------------------------------


class StubServer:
    def active_jobs(self):
        return 0

    def stop(self, timeout=0):
        self.stopped = True


def make_desktop(tmp_path):
    return desktop.Desktop(tmp_path, 8000, StubServer(), "2026.8.19")


def test_forcing_a_check_installs_and_asks_for_a_restart(tmp_path):
    from tests.test_ytdlp_update import FakePyPI, good_selftest

    d = make_desktop(tmp_path)
    result = d.check_for_update(force=True, fetch=FakePyPI("2026.9.1"), selftest=good_selftest)
    assert result.status == "updated" and d.restart_needed
    assert d.checking is False


def test_the_daily_check_is_skipped_when_it_already_ran_and_leaves_no_message(tmp_path):
    from app.ytdlp_update import write_prefs

    write_prefs(tmp_path, last_check=time.time())
    d = make_desktop(tmp_path)
    assert d.check_for_update(fetch=lambda url: b"{}").status == "skipped"
    assert d.update is None and not d.restart_needed


def test_a_failed_check_is_shown_but_does_not_ask_for_a_restart(tmp_path):
    def offline(url):
        raise OSError("offline")

    d = make_desktop(tmp_path)
    assert d.check_for_update(force=True, fetch=offline).status == "failed"
    assert d.update.status == "failed" and not d.restart_needed


def test_two_checks_at_once_do_not_both_run(tmp_path):
    d = make_desktop(tmp_path)
    d.checking = True
    assert d.check_for_update(force=True, fetch=lambda url: b"{}").status == "skipped"


def test_shutdown_stops_the_server_and_clears_the_instance_file(tmp_path):
    d = make_desktop(tmp_path)
    desktop.write_instance(tmp_path, 8000)
    d.shutdown()
    assert d.server.stopped and not (tmp_path / desktop.INSTANCE_FILE).exists()


# --- the real program, started and stopped as a user would ----------------------------------------


def start_program(data_dir: Path, port: int, *extra):
    env = {**os.environ, "SIFON_DATA_DIR": str(data_dir), "PYTHONPATH": str(SERVICE_DIR)}
    return subprocess.Popen(
        [sys.executable, "-m", "app.desktop", "--no-window", "--no-browser", "--port", str(port), *extra],
        cwd=SERVICE_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )


def wait_for_file(path: Path, timeout=10.0):
    deadline = time.time() + timeout
    while not path.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert path.exists(), f"{path.name} was not written"


def wait_health(port: int, timeout=40.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = desktop.fetch_health(port)
        if body:
            return body
        time.sleep(0.2)
    return None


@pytest.mark.skipif(sys.platform != "win32", reason="uses CTRL_BREAK to stop the process")
def test_the_program_starts_refuses_a_second_copy_and_cleans_up_when_stopped(tmp_path):
    port = free_port()
    first = start_program(tmp_path, port)
    try:
        assert wait_health(port), "the program did not come up"
        wait_for_file(tmp_path / desktop.INSTANCE_FILE)
        assert json.loads((tmp_path / desktop.INSTANCE_FILE).read_text())["port"] == port
        assert (tmp_path / "logs" / "sifon.log").is_file()

        # A second launch finds the first, opens nothing (no browser) and exits cleanly, fast.
        second = start_program(tmp_path, free_port())
        assert second.wait(timeout=30) == 0
        assert wait_health(port) is not None  # the first one is untouched

        first.send_signal(signal.CTRL_BREAK_EVENT)
        first.wait(timeout=30)
        assert not (tmp_path / desktop.INSTANCE_FILE).exists()
        assert desktop.fetch_health(port, timeout=0.5) is None
    finally:
        if first.poll() is None:
            first.kill()


def test_a_busy_explicit_port_is_refused_with_a_message_and_exit_code_2(tmp_path):
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        busy = holder.getsockname()[1]
        proc = start_program(tmp_path, busy)
        out, _ = proc.communicate(timeout=60)
    assert proc.returncode == 2 and str(busy) in out

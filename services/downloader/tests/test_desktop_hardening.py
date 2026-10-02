"""Regression tests for the findings of the independent review of the launcher (F8)."""
import http.server
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

from app import __version__, desktop


def serve(handler_class):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    return server


def handler(status, headers, body):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return H


def test_something_that_only_looks_a_little_like_sifon_is_not_sifon():
    for body in (b'{"ok": true}', b'{"ok": true, "ytdlp_version": "1"}', b'{"ok": "yes", "ytdlp_version": "1", "version": "1"}', b"[]"):
        server = serve(handler(200, {"Content-Type": "application/json"}, body))
        try:
            assert desktop.fetch_health(server.server_address[1], timeout=2) is None, body
        finally:
            server.shutdown()
            server.server_close()


def test_the_real_health_shape_is_accepted():
    body = json.dumps({"ok": True, "version": __version__, "ytdlp_version": "2026.8.19"}).encode()
    server = serve(handler(200, {}, body))
    try:
        assert desktop.fetch_health(server.server_address[1], timeout=2)["ok"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_a_redirect_to_another_local_service_is_not_followed():
    real = json.dumps({"ok": True, "version": "1", "ytdlp_version": "1"}).encode()
    target = serve(handler(200, {}, real))
    redirector = serve(handler(302, {"Location": f"http://127.0.0.1:{target.server_address[1]}/api/health"}, b""))
    try:
        assert desktop.fetch_health(redirector.server_address[1], timeout=2) is None
    finally:
        for s in (target, redirector):
            s.shutdown()
            s.server_close()


# --- the instance file belongs to the process that wrote it --------------------------------------


def test_a_process_only_removes_its_own_instance_file(tmp_path):
    (tmp_path / desktop.INSTANCE_FILE).write_text(json.dumps({"pid": 111111, "port": 8000}))
    desktop.clear_instance(tmp_path, owner_pid=222222)
    assert (tmp_path / desktop.INSTANCE_FILE).exists()  # somebody else's: left alone
    desktop.clear_instance(tmp_path, owner_pid=111111)
    assert not (tmp_path / desktop.INSTANCE_FILE).exists()


@pytest.mark.parametrize("content", ["{not json", "[]", "null", '{"pid": "x"}', '{"pid": null}'])
def test_clearing_a_damaged_instance_file_never_raises(tmp_path, content):
    (tmp_path / desktop.INSTANCE_FILE).write_text(content)
    desktop.clear_instance(tmp_path, owner_pid=1)


def test_without_an_owner_the_file_is_removed(tmp_path):
    desktop.write_instance(tmp_path, 8000)
    desktop.clear_instance(tmp_path)
    assert not (tmp_path / desktop.INSTANCE_FILE).exists()


# --- single instance: the OS arbitrates, not a file -----------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows only")
def test_the_second_claim_on_the_same_folder_loses_and_a_different_folder_wins(tmp_path):
    first = desktop.SingleInstance(tmp_path / "a")
    try:
        assert first.acquired
        second = desktop.SingleInstance(tmp_path / "a")
        assert not second.acquired
        second.release()
        other = desktop.SingleInstance(tmp_path / "b")
        assert other.acquired
        other.release()
    finally:
        first.release()
    again = desktop.SingleInstance(tmp_path / "a")  # free again once the first one let go
    assert again.acquired
    again.release()


@pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows only")
def test_many_simultaneous_launches_produce_exactly_one_winner(tmp_path):
    results, holders = [], []

    def launch():
        instance = desktop.SingleInstance(tmp_path)
        results.append(instance.acquired)
        holders.append(instance)

    threads = [threading.Thread(target=launch) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert results.count(True) == 1
    finally:
        for h in holders:
            h.release()


def test_waiting_for_a_starting_instance_returns_its_port_once_it_is_ready(tmp_path):
    calls = {"n": 0}

    def health(port):
        calls["n"] += 1
        return {"ok": True} if calls["n"] >= 3 else None

    desktop.write_instance(tmp_path, 8123)
    assert desktop.wait_for_running(tmp_path, timeout=5, health=health) == 8123


def test_waiting_gives_up_when_nothing_ever_answers(tmp_path):
    desktop.write_instance(tmp_path, 8123)
    assert desktop.wait_for_running(tmp_path, timeout=0.6, health=lambda p: None) is None


# --- ports and restart ----------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["99999", "0", "80", "-1"])
def test_an_out_of_range_port_is_rejected_by_the_command_line(value):
    with pytest.raises(SystemExit):
        desktop.parse_args(["--port", value])


def test_an_impossible_port_is_just_not_free_instead_of_crashing():
    assert desktop.port_is_free(99999) is False


def test_restart_keeps_the_original_options_and_never_reopens_the_browser(tmp_path, monkeypatch):
    launched = {}
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda cmd, **kw: launched.setdefault("cmd", cmd))

    class Stub:
        def stop(self, timeout=0):
            pass

        def active_jobs(self):
            return 0

    d = desktop.Desktop(tmp_path, 8000, Stub(), "2026.8.19", argv=["--port", "8765", "--no-window"])
    d.restart()
    assert launched["cmd"][-4:] == ["--port", "8765", "--no-window", "--no-browser"]
    assert launched["cmd"].count("--no-browser") == 1

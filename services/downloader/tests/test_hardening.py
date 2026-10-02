import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.hardening import route_environment_through

SERVICE_DIR = Path(__file__).resolve().parents[1]


def test_environment_is_pointed_at_the_proxy_and_bypass_variables_are_removed():
    env = {"NO_PROXY": "127.0.0.1", "no_proxy": "localhost", "ALL_PROXY": "socks5://x", "HTTPS_PROXY": "http://corp:3128", "KEEP": "1"}
    route_environment_through("http://127.0.0.1:5555", env)
    assert env["HTTP_PROXY"] == env["http_proxy"] == env["HTTPS_PROXY"] == env["https_proxy"] == "http://127.0.0.1:5555"
    for gone in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
        assert gone not in env
    assert env["KEEP"] == "1"


def test_restore_puts_the_original_environment_back():
    env = {"NO_PROXY": "127.0.0.1", "HTTPS_PROXY": "http://corp:3128"}
    original = dict(env)
    restore = route_environment_through("http://127.0.0.1:5555", env)
    restore()
    assert env == original


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows only")
def test_memory_limit_turns_a_runaway_allocation_into_memoryerror_not_a_frozen_machine():
    code = textwrap.dedent(
        """
        from app.hardening import limit_process_memory
        assert limit_process_memory(300 * 1024 * 1024) is True
        try:
            hog = bytearray(1024 * 1024 * 1024)  # 1 GB, over the 300 MB cap
            print("NOT LIMITED")
        except MemoryError:
            print("MemoryError")
        small = bytearray(10 * 1024 * 1024)       # normal work still works afterwards
        print("still alive", len(small))
        """
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=SERVICE_DIR, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert "MemoryError" in done.stdout and "still alive" in done.stdout and "NOT LIMITED" not in done.stdout

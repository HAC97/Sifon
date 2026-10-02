import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_env  # noqa: E402


def levels(results):
    return {name: level for level, name, _ in results}


def only(*names):
    return lambda name: f"/bin/{name}" if name in names else None


def test_python_too_old_fails_and_untested_warns_and_tested_passes():
    assert levels(check_env.check_python((3, 9))) == {"python": "FAIL"}
    assert levels(check_env.check_python((3, 13))) == {"python": "WARN"}
    assert levels(check_env.check_python((3, 12))) == {"python": "OK"}


def test_missing_library_fails_naming_the_pip_package():
    results = check_env.check_libraries(find_spec=lambda m: None if m == "curl_cffi" else object())
    assert levels(results)["curl-cffi"] == "FAIL"
    assert levels(results)["fastapi"] == "OK"


def test_ffmpeg_is_required_ffprobe_and_deno_are_not():
    assert levels(check_env.check_programs(only()))["ffmpeg"] == "FAIL"
    found = levels(check_env.check_programs(only("ffmpeg")))
    assert found == {"ffmpeg": "OK", "ffprobe": "WARN", "deno": "WARN"}
    assert levels(check_env.check_programs(only("ffmpeg", "ffprobe", "deno"))) == {
        "ffmpeg": "OK",
        "ffprobe": "OK",
        "deno": "OK",
    }


def test_node_alone_still_only_warns_about_deno():
    results = check_env.check_programs(only("ffmpeg", "node"))
    deno = next(r for r in results if r[1] == "deno")
    assert deno[0] == "WARN" and "node" in deno[2]


def test_ejs_requirement_is_read_from_the_default_extra():
    requires = ['brotli; extra == "default"', 'yt-dlp-ejs==0.8.0; extra == "default"', "websockets>=13"]
    assert check_env.ejs_requirement(requires) == "0.8.0"
    assert check_env.ejs_requirement(["yt-dlp-ejs>=0.8"]) is None
    assert check_env.ejs_requirement(None) is None


def test_mismatched_ejs_fails_and_matching_passes():
    requires = lambda _d: ['yt-dlp-ejs==0.8.0; extra == "default"']  # noqa: E731
    assert levels(check_env.check_ejs_matches_ytdlp(requires, installed=lambda _d: "0.7.0")) == {"yt-dlp-ejs": "FAIL"}
    assert levels(check_env.check_ejs_matches_ytdlp(requires, installed=lambda _d: "0.8.0")) == {"yt-dlp-ejs": "OK"}


def test_bad_settings_fail_naming_the_variable(monkeypatch):
    monkeypatch.setenv("SIFON_MAX_QUEUE", "zero")
    results = check_env.check_settings()
    assert results[0][0] == "FAIL" and "SIFON_MAX_QUEUE" in results[0][2]


def test_default_settings_pass(monkeypatch):
    for variable in list(__import__("os").environ):
        if variable.startswith("SIFON_"):
            monkeypatch.delenv(variable)
    assert check_env.check_settings()[0][0] == "OK"


def test_render_has_one_line_per_result():
    text = check_env.render([("OK", "a", "1"), ("FAIL", "b", "2")])
    assert text.splitlines() == ["OK    a: 1", "FAIL  b: 2"]


def test_script_runs_and_the_installed_libraries_are_consistent():
    """Runs the real script in this venv: the libraries must be present and ejs must match yt-dlp."""
    done = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_env.py"), "--libs-only"], capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "FAIL" not in done.stdout


def test_versions_line_names_the_three_updatable_packages():
    done = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_env.py"), "--versions"], capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0
    for package in ("yt-dlp ", "yt-dlp-ejs ", "curl-cffi "):
        assert package in done.stdout


# --- up-to-date check: pip install --upgrade exits 0 even when the index is unreachable -----------

PIP_INDEX_OUTPUT = """WARNING: pip index is currently an experimental command.
yt-dlp (2026.8.19)
Available versions: 2026.8.19, 2026.7.4
  INSTALLED: 2026.8.19
  LATEST:    2026.8.19
"""


class Done:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout = returncode, stdout


def test_up_to_date_when_installed_is_the_latest():
    results = check_env.check_up_to_date(run=lambda *a, **k: Done(0, PIP_INDEX_OUTPUT))
    assert levels(results) == {"yt-dlp": "OK"}


def test_outdated_install_fails_with_both_versions():
    out = PIP_INDEX_OUTPUT.replace("LATEST:    2026.8.19", "LATEST:    2026.9.1")
    ((level, _, detail),) = check_env.check_up_to_date(run=lambda *a, **k: Done(0, out))
    assert level == "FAIL" and "2026.8.19" in detail and "2026.9.1" in detail


def test_unreachable_index_is_a_failure_not_a_silent_success():
    results = check_env.check_up_to_date(run=lambda *a, **k: Done(1, ""))
    assert levels(results) == {"yt-dlp": "FAIL"}


def test_timeout_and_unparseable_output_fail():
    def hangs(*a, **k):
        raise subprocess.TimeoutExpired("pip", 90)

    assert levels(check_env.check_up_to_date(run=hangs)) == {"yt-dlp": "FAIL"}
    assert levels(check_env.check_up_to_date(run=lambda *a, **k: Done(0, "no versions here"))) == {"yt-dlp": "FAIL"}


def test_update_script_runs_the_up_to_date_check_before_reporting_success():
    script = (SCRIPTS / "update-ytdlp.ps1").read_text(encoding="utf-8-sig")
    assert script.index("--up-to-date") < script.index("Actualización verificada")

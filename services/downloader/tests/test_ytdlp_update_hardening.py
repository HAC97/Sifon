"""Regression tests for the findings of the independent review of the updater (F1-F7)."""
import hashlib
import io
import json
import threading
import urllib.request
import zipfile
from pathlib import Path

import pytest

from app import ytdlp_update as upd
from tests.test_ytdlp_update import FakePyPI, good_selftest, make_wheel


# --- F1: yt-dlp writes '2026.08.19', PyPI reports '2026.8.19' ------------------------------------


def test_zero_padded_and_normalised_versions_are_the_same_release():
    assert upd.same_version("2026.08.19", "2026.8.19")
    assert upd.same_version("2026.10.05", "2026.10.5")
    assert not upd.same_version("2026.08.19", "2026.8.20")
    assert not upd.same_version("dev", "dev")  # no digits: never "the same"


def test_the_real_selftest_accepts_a_padded_version_when_pypi_says_unpadded(tmp_path):
    wheel = make_wheel("2026.09.01")  # what yt_dlp.version.__version__ looks like
    upd.safe_extract(wheel, tmp_path)
    upd.safe_extract(make_wheel("0.1", "yt_dlp_ejs"), tmp_path)
    assert upd.run_selftest(tmp_path, "2026.9.1") is True  # what PyPI's JSON says
    assert upd.run_selftest(tmp_path, "2026.9.2") is False


def test_a_full_update_works_when_the_package_pads_its_version(tmp_path):
    pypi = FakePyPI("2026.9.1")
    padded = make_wheel("2026.09.01")
    pypi.files["https://files.pythonhosted.org/packages/yt_dlp.whl"] = padded
    entry = json.loads(pypi.files["https://pypi.org/pypi/yt-dlp/json"])
    entry["releases"]["2026.9.1"][0]["digests"]["sha256"] = hashlib.sha256(padded).hexdigest()
    pypi.files["https://pypi.org/pypi/yt-dlp/json"] = json.dumps(entry).encode()
    result = upd.install_update(tmp_path, "2026.8.19", pypi, upd.run_selftest)
    assert result.status == "updated", result.detail


# --- F2/F4: nothing from the index may name a path, a host or a scheme ----------------------------


@pytest.mark.parametrize(
    "version",
    ["9999.0/../../../victim", "2026.8.19.dev0", "2026.8.19rc1", "1!2026.8.19", "99999999999999999999.1",
     "", "..", "2026", "2026.8.19\\evil", "2026.8.19 ", 20260819],
)
def test_a_hostile_or_odd_version_string_is_refused(version):
    pypi = FakePyPI("2026.9.1")
    meta = json.loads(pypi.files["https://pypi.org/pypi/yt-dlp/json"])
    meta["info"]["version"] = version
    pypi.files["https://pypi.org/pypi/yt-dlp/json"] = json.dumps(meta).encode()
    with pytest.raises(ValueError):
        upd.plan_update(pypi, "2026.8.19")


def test_a_hostile_version_cannot_delete_or_replace_a_folder_outside_the_updates_folder(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep me")
    pypi = FakePyPI("2026.9.1")
    meta = json.loads(pypi.files["https://pypi.org/pypi/yt-dlp/json"])
    meta["info"]["version"] = "9999.0/../../../victim"
    pypi.files["https://pypi.org/pypi/yt-dlp/json"] = json.dumps(meta).encode()
    result = upd.install_update(tmp_path / "data", "2026.8.19", pypi, good_selftest)
    assert result.status == "failed"
    assert (victim / "precious.txt").read_text() == "keep me"


@pytest.mark.parametrize(
    "url",
    ["http://files.pythonhosted.org/x.whl", "file:///C:/Windows/win.ini", "ftp://files.pythonhosted.org/x",
     "https://evil.example/x.whl", "https://files.pythonhosted.org.evil.example/x.whl",
     "https://user:pw@files.pythonhosted.org/x.whl", "https://127.0.0.1/x.whl"],
)
def test_only_https_on_pypis_hosts_is_downloaded(url):
    with pytest.raises(ValueError):
        upd.check_url(url)
    with pytest.raises(ValueError):
        upd.default_fetch(url)


def test_a_wheel_url_on_another_host_in_the_json_is_refused():
    pypi = FakePyPI("2026.9.1")
    meta = json.loads(pypi.files["https://pypi.org/pypi/yt-dlp/json"])
    meta["releases"]["2026.9.1"][0]["url"] = "https://evil.example/yt_dlp.whl"
    pypi.files["https://pypi.org/pypi/yt-dlp/json"] = json.dumps(meta).encode()
    with pytest.raises(ValueError, match="refusing"):
        upd.plan_update(pypi, "2026.8.19")


def test_the_ejs_pin_cannot_traverse_on_the_index():
    pypi = FakePyPI("2026.9.1")
    meta = json.loads(pypi.files["https://pypi.org/pypi/yt-dlp/json"])
    meta["info"]["requires_dist"] = ['yt-dlp-ejs==..; extra == "default"']
    pypi.files["https://pypi.org/pypi/yt-dlp/json"] = json.dumps(meta).encode()
    with pytest.raises(ValueError):
        upd.plan_update(pypi, "2026.8.19")


def test_a_redirect_to_http_or_another_host_is_refused():
    handler = upd._SameHostsRedirects()
    request = urllib.request.Request("https://pypi.org/pypi/yt-dlp/json")
    for target in ("http://pypi.org/x", "https://evil.example/x", "http://127.0.0.1:9/x"):
        with pytest.raises(ValueError):
            handler.redirect_request(request, None, 302, "Found", {}, target)
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://files.pythonhosted.org/ok") is not None


def test_a_slow_trickle_is_cut_by_the_overall_deadline(monkeypatch):
    class Trickle:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b"x"

    monkeypatch.setattr(upd._OPENER, "open", lambda request, timeout=None: Trickle())
    monkeypatch.setattr(upd, "DOWNLOAD_DEADLINE", -1)
    with pytest.raises(TimeoutError):
        upd.default_fetch("https://files.pythonhosted.org/x.whl")


# --- F5: the preferences file may hold anything ------------------------------------------------


@pytest.mark.parametrize("content", ["[]", "null", '"x"', "7", "{not json", '{"last_check": "abc"}', '{"last_check": [1]}'])
def test_a_damaged_or_odd_preferences_file_never_breaks_the_check(tmp_path, content):
    (tmp_path / "update_state.json").write_text(content, encoding="utf-8")
    assert upd.check_due(tmp_path) in (True, False)
    assert upd.auto_update_enabled(tmp_path) in (True, False)
    result = upd.update_if_due(tmp_path, "2026.8.19", FakePyPI("2026.8.19"), selftest=good_selftest)
    assert result.status in ("current", "skipped")
    upd.write_prefs(tmp_path, auto=True)  # and writing over it repairs it
    assert upd.read_prefs(tmp_path)["auto"] is True


def test_a_last_check_in_the_future_does_not_switch_checks_off(tmp_path):
    upd.write_prefs(tmp_path, last_check=4102444800.0)  # year 2100
    assert upd.check_due(tmp_path, now=1_800_000_000.0 + upd.CHECK_EVERY_SECONDS + 1)


def test_the_string_false_does_not_count_as_enabled_or_disabled_by_accident(tmp_path):
    upd.write_prefs(tmp_path, auto=False)
    assert upd.auto_update_enabled(tmp_path) is False
    upd.write_prefs(tmp_path, auto="false")  # wrong type: treated as the default (on), never a crash
    assert upd.auto_update_enabled(tmp_path) is True


def test_concurrent_writers_do_not_lose_each_others_keys(tmp_path):
    def writer(key, n):
        for i in range(n):
            upd.write_prefs(tmp_path, **{key: i})

    threads = [threading.Thread(target=writer, args=(f"k{j}", 40)) for j in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    state = upd.read_prefs(tmp_path)
    assert all(state.get(f"k{j}") == 39 for j in range(4)), state
    assert not list(tmp_path.glob("*.tmp"))


# --- F6/F7: bad overlays and pruning -------------------------------------------------------------


def make_overlay(root: Path, version: str, ok=True):
    folder = root / "ytdlp" / version
    folder.mkdir(parents=True)
    if ok:
        (folder / upd.OK_MARKER).write_text("{}")
    return folder


def test_a_broken_overlay_stops_being_usable_even_if_a_bad_folder_already_exists(tmp_path):
    folder = make_overlay(tmp_path, "2099.1.1")
    (folder / "yt_dlp").mkdir()
    (folder / "yt_dlp" / "__init__.py").write_text("raise ImportError('broken')")
    (folder / "yt_dlp_ejs").mkdir()
    (folder / "yt_dlp_ejs" / "__init__.py").write_text("")
    (tmp_path / "ytdlp" / "2099.1.1.bad").mkdir()  # left from an earlier failure
    out = __import__("subprocess").run(
        [__import__("sys").executable, "-c",
         f"from pathlib import Path; from app.ytdlp_update import apply_overlay, usable_overlays; "
         f"print(apply_overlay(Path(r'{tmp_path}'), '2026.8.19')); print(usable_overlays(Path(r'{tmp_path}')))"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60,
    )
    assert out.stdout.splitlines()[0] == "None" and out.stdout.splitlines()[1] == "[]", out.stdout + out.stderr


def test_prune_removes_old_bad_folders_and_keeps_the_two_newest(tmp_path):
    for v in ("2026.7.1", "2026.8.1", "2026.9.1"):
        make_overlay(tmp_path, v)
    (tmp_path / "ytdlp" / "2026.6.1.bad").mkdir()
    upd.prune(tmp_path)
    assert [f.name for _, f in upd.usable_overlays(tmp_path)] == ["2026.9.1", "2026.8.1"]
    assert not (tmp_path / "ytdlp" / "2026.6.1.bad").exists()


def test_prune_never_deletes_the_overlay_the_process_is_running_from(tmp_path):
    for v in ("2026.7.1", "2026.8.1", "2026.9.1"):
        make_overlay(tmp_path, v)
    oldest = (tmp_path / "ytdlp" / "2026.7.1").resolve()
    upd.prune(tmp_path, keep=oldest)
    assert oldest.is_dir()


def test_active_overlay_is_found_from_the_imported_module(tmp_path, monkeypatch):
    import sys
    import types

    folder = make_overlay(tmp_path, "2099.1.1")
    fake = types.ModuleType("yt_dlp")
    fake.__file__ = str(folder / "yt_dlp" / "__init__.py")
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    assert upd.active_overlay() == folder.resolve()
    fake.__file__ = r"C:\somewhere\site-packages\yt_dlp\__init__.py"
    assert upd.active_overlay() is None


def test_zip_with_duplicate_members_is_still_contained(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("yt_dlp/a.py", "1")
        z.writestr("YT_DLP/a.py", "2")  # a different top-level name: skipped, never written
    assert upd.safe_extract(buffer.getvalue(), tmp_path) == 1

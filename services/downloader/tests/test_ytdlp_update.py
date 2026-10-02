"""The packaged app's yt-dlp updater, against a fake PyPI. No network."""
import hashlib
import io
import json
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from app import ytdlp_update as upd

SERVICE_DIR = Path(__file__).resolve().parents[1]


def make_wheel(version: str, package: str = "yt_dlp", extra: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        if package == "yt_dlp":
            z.writestr("yt_dlp/__init__.py", "")
            z.writestr("yt_dlp/version.py", f"__version__ = '{version}'\n")
        else:
            z.writestr("yt_dlp_ejs/__init__.py", "")
        z.writestr(f"{package}-{version}.dist-info/METADATA", "Name: x\n")  # must NOT be extracted
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buffer.getvalue()


class FakePyPI:
    """Serves the PyPI JSON documents and wheel files for yt-dlp and yt-dlp-ejs."""

    def __init__(self, version="2026.9.1", ejs="0.9.0", yanked=False, tamper=False):
        self.files = {}
        self.requested = []
        ytdlp_wheel = make_wheel(version)
        ejs_wheel = make_wheel(ejs, "yt_dlp_ejs")
        self.files["https://files/yt_dlp.whl"] = ytdlp_wheel
        self.files["https://files/ejs.whl"] = ejs_wheel
        digest = hashlib.sha256(ytdlp_wheel).hexdigest() if not tamper else "0" * 64
        entry = {
            "packagetype": "bdist_wheel", "filename": f"yt_dlp-{version}-py3-none-any.whl",
            "url": "https://files/yt_dlp.whl", "digests": {"sha256": digest}, "yanked": yanked,
        }
        self.files["https://pypi.org/pypi/yt-dlp/json"] = json.dumps(
            {"info": {"version": version, "requires_dist": [f'yt-dlp-ejs=={ejs}; extra == "default"', "requests"]},
             "releases": {version: [entry]}, "urls": [entry]}
        ).encode()
        self.files[f"https://pypi.org/pypi/yt-dlp-ejs/{ejs}/json"] = json.dumps(
            {"urls": [{"packagetype": "bdist_wheel", "filename": f"yt_dlp_ejs-{ejs}-py3-none-any.whl",
                       "url": "https://files/ejs.whl", "digests": {"sha256": hashlib.sha256(ejs_wheel).hexdigest()}}]}
        ).encode()

    def __call__(self, url):
        self.requested.append(url)
        return self.files[url]


def good_selftest(folder, expected):
    return (folder / "yt_dlp" / "version.py").read_text().strip().endswith(f"'{expected}'")


# --- versions ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b", [("2026.08.19", "2026.9.1"), ("2026.8.19", "2026.8.19.post1"), ("2025.12.8", "2026.1.2")]
)
def test_version_ordering_is_numeric_not_textual(a, b):
    assert upd.version_key(a) < upd.version_key(b)


def test_unparseable_version_has_an_empty_key():
    assert upd.version_key("dev") == ()


# --- planning ---------------------------------------------------------------------------------


def test_plan_is_none_when_already_current():
    assert upd.plan_update(FakePyPI("2026.8.19"), "2026.08.19") is None


def test_plan_lists_yt_dlp_and_the_exact_ejs_it_pins():
    version, wheels = upd.plan_update(FakePyPI("2026.9.1", ejs="0.9.0"), "2026.8.19")
    assert version == "2026.9.1"
    assert [w["filename"] for w in wheels] == ["yt_dlp-2026.9.1-py3-none-any.whl", "yt_dlp_ejs-0.9.0-py3-none-any.whl"]


def test_a_release_with_only_a_yanked_wheel_is_not_installed():
    with pytest.raises(ValueError, match="no universal wheel"):
        upd.plan_update(FakePyPI(yanked=True), "2026.8.19")


# --- unpacking --------------------------------------------------------------------------------


def test_only_the_two_packages_are_extracted(tmp_path):
    count = upd.safe_extract(make_wheel("2026.9.1"), tmp_path)
    assert count == 2
    assert (tmp_path / "yt_dlp" / "version.py").is_file()
    assert not list(tmp_path.glob("*.dist-info"))


@pytest.mark.parametrize(
    "evil",
    ["yt_dlp/../../outside.py", "yt_dlp/..\\..\\outside.py", "yt_dlp/C:/x.py", "yt_dlp//../escape.py"],
)
def test_path_traversal_in_a_wheel_is_rejected(tmp_path, evil):
    wheel = make_wheel("2026.9.1", extra={evil: "boom"})
    with pytest.raises(ValueError):
        upd.safe_extract(wheel, tmp_path / "target")
    assert not (tmp_path / "outside.py").exists()


def test_a_symlink_member_is_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        link = zipfile.ZipInfo("yt_dlp/link")
        link.external_attr = (0o120777 << 16)
        z.writestr(link, "../../etc")
    with pytest.raises(ValueError, match="symlink"):
        upd.safe_extract(buffer.getvalue(), tmp_path)


def test_an_oversized_wheel_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(upd, "MAX_UNPACKED_BYTES", 10)
    with pytest.raises(ValueError, match="larger"):
        upd.safe_extract(make_wheel("2026.9.1"), tmp_path)


# --- installing -------------------------------------------------------------------------------


def test_install_downloads_verifies_extracts_and_marks_usable(tmp_path):
    result = upd.install_update(tmp_path, "2026.8.19", FakePyPI("2026.9.1"), good_selftest)
    assert (result.status, result.version) == ("updated", "2026.9.1")
    assert [folder.name for _, folder in upd.usable_overlays(tmp_path)] == ["2026.9.1"]
    assert (tmp_path / "ytdlp" / "2026.9.1" / "yt_dlp_ejs" / "__init__.py").is_file()
    assert not list((tmp_path / "ytdlp").glob("*.tmp"))


def test_a_wheel_that_does_not_match_the_published_hash_installs_nothing(tmp_path):
    result = upd.install_update(tmp_path, "2026.8.19", FakePyPI(tamper=True), good_selftest)
    assert result.status == "failed" and "hash" in result.detail
    assert upd.usable_overlays(tmp_path) == [] and not list((tmp_path / "ytdlp").glob("*"))


def test_a_copy_that_fails_its_selftest_is_discarded(tmp_path):
    result = upd.install_update(tmp_path, "2026.8.19", FakePyPI(), lambda folder, version: False)
    assert result.status == "failed"
    assert upd.usable_overlays(tmp_path) == [] and not list((tmp_path / "ytdlp").glob("*"))


def test_up_to_date_changes_nothing_on_disk(tmp_path):
    result = upd.install_update(tmp_path, "2026.9.1", FakePyPI("2026.9.1"), good_selftest)
    assert result.status == "current" and not (tmp_path / "ytdlp").exists()


def test_a_network_error_becomes_a_failed_result_never_an_exception(tmp_path):
    def offline(url):
        raise OSError("no network")

    result = upd.install_update(tmp_path, "2026.8.19", offline, good_selftest)
    assert result.status == "failed" and "OSError" in result.detail


def test_only_the_two_newest_versions_are_kept(tmp_path):
    for version in ("2026.7.1", "2026.8.1", "2026.9.1"):
        folder = tmp_path / "ytdlp" / version
        folder.mkdir(parents=True)
        (folder / upd.OK_MARKER).write_text("{}")
    (tmp_path / "ytdlp" / "2026.10.1.tmp").mkdir()
    upd.prune(tmp_path)
    assert [f.name for _, f in upd.usable_overlays(tmp_path)] == ["2026.9.1", "2026.8.1"]
    assert not (tmp_path / "ytdlp" / "2026.10.1.tmp").exists()


def test_an_unfinished_folder_without_the_marker_is_never_used(tmp_path):
    (tmp_path / "ytdlp" / "2026.9.1").mkdir(parents=True)
    assert upd.usable_overlays(tmp_path) == []


def test_the_real_selftest_runs_a_fresh_process_against_the_unpacked_copy(tmp_path):
    upd.safe_extract(make_wheel("2099.1.1"), tmp_path)
    upd.safe_extract(make_wheel("0.1", "yt_dlp_ejs"), tmp_path)
    assert upd.run_selftest(tmp_path, "2099.1.1") is True
    assert upd.run_selftest(tmp_path, "2099.1.2") is False  # reports a different version
    assert upd.run_selftest(tmp_path / "missing", "2099.1.1") is False


# --- applying at start-up (needs a process where yt_dlp is not imported yet) --------------------


def run_startup(data_dir: Path, bundled: str) -> subprocess.CompletedProcess:
    code = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from app.ytdlp_update import apply_overlay
        used = apply_overlay(Path(r"{data_dir}"), {bundled!r})
        import yt_dlp.version
        print("overlay=", used, "| imported=", yt_dlp.version.__version__)
        """
    )
    return subprocess.run([sys.executable, "-c", code], cwd=SERVICE_DIR, capture_output=True, text=True, timeout=60)


def install_fake_overlay(data_dir: Path, version: str, *, broken=False):
    folder = data_dir / "ytdlp" / version
    (folder / "yt_dlp").mkdir(parents=True)
    (folder / "yt_dlp_ejs").mkdir()
    (folder / "yt_dlp_ejs" / "__init__.py").write_text("")
    (folder / "yt_dlp" / "__init__.py").write_text("raise ImportError('broken update')" if broken else "")
    (folder / "yt_dlp" / "version.py").write_text(f"__version__ = '{version}'\n")
    if broken:
        (folder / "yt_dlp" / "version.py").write_text("raise ImportError('broken update')")
    (folder / upd.OK_MARKER).write_text("{}")
    return folder


def test_a_newer_overlay_is_loaded_instead_of_the_bundled_copy(tmp_path):
    install_fake_overlay(tmp_path, "2099.1.1")
    out = run_startup(tmp_path, "2026.8.19")
    assert "overlay= 2099.1.1 | imported= 2099.1.1" in out.stdout, out.stderr


def test_an_overlay_that_is_not_newer_than_the_bundled_copy_is_ignored(tmp_path):
    install_fake_overlay(tmp_path, "2020.1.1")
    out = run_startup(tmp_path, "2026.8.19")
    assert "overlay= None" in out.stdout and "imported= 2026" in out.stdout, out.stderr


def test_an_overlay_that_does_not_import_is_set_aside_and_the_bundled_copy_runs(tmp_path):
    install_fake_overlay(tmp_path, "2099.1.1", broken=True)
    out = run_startup(tmp_path, "2026.8.19")
    assert "overlay= None" in out.stdout and "imported= 2026" in out.stdout, out.stderr
    assert (tmp_path / "ytdlp" / "2099.1.1.bad").is_dir()


def test_apply_overlay_is_a_noop_once_yt_dlp_is_imported(tmp_path):
    import yt_dlp  # noqa: F401

    install_fake_overlay(tmp_path, "2099.1.1")
    assert upd.apply_overlay(tmp_path, "2026.8.19") is None


# --- when to check ----------------------------------------------------------------------------


def test_a_check_happens_once_a_day(tmp_path):
    pypi = FakePyPI("2026.9.1")
    first = upd.update_if_due(tmp_path, "2026.8.19", pypi, selftest=good_selftest)
    assert first.status == "updated"
    calls = len(pypi.requested)
    second = upd.update_if_due(tmp_path, "2026.8.19", pypi, selftest=good_selftest)
    assert second.status == "skipped" and len(pypi.requested) == calls  # no network the second time


def test_a_failed_check_is_not_remembered_so_it_retries_at_the_next_start(tmp_path):
    def offline(url):
        raise OSError("offline")

    assert upd.update_if_due(tmp_path, "2026.8.19", offline).status == "failed"
    assert upd.check_due(tmp_path)


def test_the_environment_variable_and_the_preference_turn_the_check_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFON_NO_AUTO_UPDATE", "1")
    assert upd.update_if_due(tmp_path, "2026.8.19", FakePyPI()).status == "skipped"
    monkeypatch.delenv("SIFON_NO_AUTO_UPDATE")
    upd.write_prefs(tmp_path, auto=False)
    assert not upd.auto_update_enabled(tmp_path)
    assert upd.update_if_due(tmp_path, "2026.8.19", FakePyPI()).status == "skipped"


def test_check_due_uses_the_recorded_time(tmp_path):
    upd.write_prefs(tmp_path, last_check=1000.0)
    assert not upd.check_due(tmp_path, now=1000.0 + upd.CHECK_EVERY_SECONDS - 1)
    assert upd.check_due(tmp_path, now=1000.0 + upd.CHECK_EVERY_SECONDS + 1)

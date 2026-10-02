import sys
from pathlib import Path

import pytest

from app import paths


def test_in_development_everything_resolves_inside_the_repo():
    assert not paths.is_frozen()
    assert paths.app_dir() == paths.REPO_DIR == paths.resource_dir()
    assert (paths.web_dir() / "index.html").is_file()
    assert paths.jobs_log_path() == paths.SERVICE_DIR / "jobs.log"
    assert paths.bin_dir() is None


def test_data_dir_honours_the_override_and_is_created(tmp_path, monkeypatch):
    target = tmp_path / "custom" / "data"
    monkeypatch.setenv("SIFON_DATA_DIR", str(target))
    assert paths.data_dir() == target and target.is_dir()


def test_data_dir_defaults_to_localappdata_sifon(tmp_path, monkeypatch):
    monkeypatch.delenv("SIFON_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / "sifon"


def fake_packaged(monkeypatch, tmp_path):
    """Pretend to be the PyInstaller folder: <tmp>/sifon.exe, <tmp>/bin, <tmp>/_internal/web."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "_internal" / "web").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "sifon.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)


def test_packaged_paths_use_the_program_folder_for_code_and_the_user_folder_for_writes(monkeypatch, tmp_path):
    fake_packaged(monkeypatch, tmp_path / "prog")
    monkeypatch.setenv("SIFON_DATA_DIR", str(tmp_path / "data"))
    prog = (tmp_path / "prog").resolve()
    assert paths.is_frozen()
    assert paths.app_dir() == prog
    assert paths.web_dir() == prog / "_internal" / "web"
    assert paths.bin_dir() == prog / "bin"
    assert paths.jobs_log_path() == tmp_path / "data" / "jobs.log"  # never inside the program folder


@pytest.fixture(autouse=True)
def _mkdirs(tmp_path):
    (tmp_path / "prog").mkdir(exist_ok=True)


def test_bundled_tools_are_put_first_on_the_path_once(monkeypatch, tmp_path):
    fake_packaged(monkeypatch, tmp_path / "prog")
    env = {"PATH": r"C:\Windows" + ";" + r"C:\Tools"}
    folder = paths.prepend_bin_to_path(env)
    assert env["PATH"].split(";")[0] == str(folder)
    paths.prepend_bin_to_path(env)  # idempotent
    assert env["PATH"].split(";").count(str(folder)) == 1


def test_nothing_is_added_to_the_path_in_development():
    env = {"PATH": "x"}
    assert paths.prepend_bin_to_path(env) is None and env == {"PATH": "x"}


def test_main_still_exposes_service_dir_and_web_dir():
    from app import main

    assert main.SERVICE_DIR == paths.SERVICE_DIR and main.WEB_DIR == paths.web_dir()
    assert isinstance(main.WEB_DIR, Path)

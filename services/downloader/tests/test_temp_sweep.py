"""Temp directories: a dead run is cleaned up, a live one never is."""
import os
import time

from app.jobs import ALIVE_FILE, JobManager
from app.main import STALE_AFTER_SECONDS, TEMP_PREFIX, _sweep_stale_temp_dirs


def make_run(root, name, heartbeat_age=None, dir_age=None):
    run = root / f"{TEMP_PREFIX}{name}"
    (run / "job").mkdir(parents=True)
    (run / "job" / "video.mp4").write_bytes(b"x")
    now = time.time()
    if heartbeat_age is not None:
        beat = run / ALIVE_FILE
        beat.touch()
        os.utime(beat, (now - heartbeat_age, now - heartbeat_age))
    if dir_age is not None:
        os.utime(run, (now - dir_age, now - dir_age))
    return run


def test_run_with_a_stale_heartbeat_is_removed(tmp_path):
    dead = make_run(tmp_path, "111", heartbeat_age=STALE_AFTER_SECONDS + 60)
    _sweep_stale_temp_dirs(tmp_path, keep=tmp_path / "none")
    assert not dead.exists()


def test_run_with_a_fresh_heartbeat_is_kept_even_if_its_folder_is_old(tmp_path):
    live = make_run(tmp_path, "222", heartbeat_age=30, dir_age=10 * STALE_AFTER_SECONDS)
    _sweep_stale_temp_dirs(tmp_path, keep=tmp_path / "none")
    assert (live / "job" / "video.mp4").exists()


def test_run_without_heartbeat_falls_back_to_the_folder_age(tmp_path):
    old = make_run(tmp_path, "333", dir_age=STALE_AFTER_SECONDS + 60)
    new = make_run(tmp_path, "444", dir_age=5)
    _sweep_stale_temp_dirs(tmp_path, keep=tmp_path / "none")
    assert not old.exists() and new.exists()


def test_our_own_dir_and_unrelated_folders_are_never_touched(tmp_path):
    mine = make_run(tmp_path, "555", heartbeat_age=10 * STALE_AFTER_SECONDS)
    other = tmp_path / "somebody-else"
    other.mkdir()
    (other / "keep.txt").write_text("x")
    _sweep_stale_temp_dirs(tmp_path, keep=mine)
    assert mine.exists() and (other / "keep.txt").exists()


def test_the_sweeper_writes_the_heartbeat(tmp_path):
    manager = JobManager(tmp_path / "base", lambda job, cb: job.dir)
    try:
        manager.start_sweeper(interval=0.05)
        deadline = time.time() + 3
        while time.time() < deadline and not (manager.base_dir / ALIVE_FILE).exists():
            time.sleep(0.01)
        assert (manager.base_dir / ALIVE_FILE).exists()
    finally:
        manager.shutdown()

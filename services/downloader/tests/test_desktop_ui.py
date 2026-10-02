import tkinter as tk

import pytest

from app.desktop_ui import DesktopWindow
from app.ytdlp_update import UpdateResult


class FakeServer:
    def __init__(self, jobs=0):
        self.jobs = jobs

    def active_jobs(self):
        return self.jobs


class FakeDesktop:
    url = "http://127.0.0.1:8000"
    installed_ytdlp = "2026.8.19"

    def __init__(self, tmp_path, jobs=0):
        self.data_dir = tmp_path
        self.server = FakeServer(jobs)
        self.update = None
        self.checking = False
        self.opened = 0
        self.auto = None

    @property
    def restart_needed(self):
        return self.update is not None and self.update.status == "updated"

    def open_browser(self):
        self.opened += 1

    def set_auto_update(self, enabled):
        self.auto = enabled

    def check_for_update(self, force=False):
        self.update = UpdateResult("updated", "yt-dlp 2026.9.1 descargado", "2026.9.1")


@pytest.fixture(scope="module")
def tk_root():
    """Tk cannot be started again after it is destroyed in the same process: one root per module."""
    try:
        base = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for tkinter")
    base.withdraw()
    yield base
    base.destroy()


@pytest.fixture
def root(tk_root):
    window = tk.Toplevel(tk_root)
    window.withdraw()
    yield window
    if window.winfo_exists():
        window.destroy()


def make(root, tmp_path, jobs=0, answer=True):
    asked = []
    desktop = FakeDesktop(tmp_path, jobs)
    window = DesktopWindow(root, desktop, confirm=lambda title, text: asked.append(text) or answer)
    return window, desktop, asked


def test_the_window_shows_the_address_the_state_and_the_ytdlp_version(root, tmp_path):
    window, desktop, _ = make(root, tmp_path)
    assert window.address.cget("text") == "http://127.0.0.1:8000"
    assert window.status.get() == "Funcionando."
    assert "2026.8.19" in window.ytdlp.get()


def test_running_downloads_are_shown(root, tmp_path):
    window, _, _ = make(root, tmp_path, jobs=2)
    assert "2" in window.status.get()


def test_open_button_opens_the_browser(root, tmp_path):
    window, desktop, _ = make(root, tmp_path)
    window.open_page()
    assert desktop.opened == 1


def test_closing_with_no_downloads_does_not_ask(root, tmp_path):
    window, _, asked = make(root, tmp_path)
    window.request_close()
    assert asked == []
    assert not root.winfo_exists()  # closed without asking


def test_closing_with_downloads_asks_and_respects_no(root, tmp_path):
    window, _, asked = make(root, tmp_path, jobs=1, answer=False)
    window.request_close()
    assert len(asked) == 1 and "descargas" in asked[0]
    assert root.winfo_exists()  # still open


def test_closing_with_downloads_and_yes_closes(root, tmp_path):
    window, _, asked = make(root, tmp_path, jobs=1, answer=True)
    window.request_close()
    assert len(asked) == 1 and not window.restart_requested
    assert not root.winfo_exists()


def test_a_downloaded_update_offers_a_restart_and_restarting_flags_it(root, tmp_path):
    window, desktop, _ = make(root, tmp_path)
    assert window.restart_button.grid_info() == {}  # hidden until an update was downloaded
    desktop.check_for_update()
    root.update()
    window.refresh()
    assert "2026.9.1" in window.ytdlp.get()
    assert window.restart_button.grid_info() != {}
    window.restart()
    assert window.restart_requested and not root.winfo_exists()


def test_the_checkbox_saves_the_preference(root, tmp_path):
    window, desktop, _ = make(root, tmp_path)
    window.auto.set(False)
    window.toggle_auto()
    assert desktop.auto is False


def test_checking_disables_the_button(root, tmp_path):
    window, desktop, _ = make(root, tmp_path)
    desktop.checking = True
    window.refresh()
    assert "disabled" in window.update_button.state()
    assert "Buscando" in window.ytdlp.get()

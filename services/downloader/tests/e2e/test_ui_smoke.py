import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app.errors import DownloadFailure, ErrorCode
from app.jobs import JobManager
from app.main import create_app

pytestmark = pytest.mark.e2e
sync_api = pytest.importorskip("playwright.sync_api")

TITLE = "<b>Hola</b> & más 😀"


def fake_info(url):
    if "bad" in url:
        raise DownloadFailure(ErrorCode.UNSUPPORTED_SITE)
    if "slow" in url:
        time.sleep(1.5)  # keeps a search in flight long enough to observe the page while it waits
    return {"title": TITLE, "thumbnail": None, "duration": 125, "uploader": "Canal", "heights": [1080, 720]}


def fake_runner(job, on_progress):
    on_progress({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 1000.0, "eta": 1})
    time.sleep(0.5)
    path = job.dir / ("clip.mp3" if job.mode == "audio" else "clip.mp4")
    path.write_bytes(b"data")
    return path


@pytest.fixture
def server(tmp_path):
    manager = JobManager(tmp_path / "jobs", fake_runner)
    app = create_app(manager=manager, info_fetcher=fake_info, url_validator=lambda u: u)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    assert srv.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(5)


@pytest.fixture
def page():
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(accept_downloads=True)
        context.set_default_timeout(10000)  # a missing element fails in 10 s, not 30
        yield context.new_page()
        browser.close()


@pytest.mark.parametrize("mode, ext", [("video", "mp4"), ("audio", "mp3")])
def test_paste_url_choose_mode_and_get_the_file(server, page, mode, ext):
    page.goto(server)
    page.fill("#url", "https://example.com/v")
    page.click("#fetch")
    page.wait_for_selector("#card:not([hidden])")

    assert page.inner_text("#title") == TITLE  # shown as text, never parsed as HTML
    assert page.locator("#title b").count() == 0
    assert page.locator("#height option").all_inner_texts() == ["Mejor calidad", "1080p", "720p"]

    if mode == "audio":
        page.check('input[value="audio"]')
        assert page.is_visible("#audio-format")
        assert not page.is_visible("#height")

    with page.expect_download(timeout=10000) as download:
        page.click("#download")
    assert download.value.suggested_filename == f"clip.{ext}"
    assert Path(download.value.path()).read_bytes() == b"data"
    assert "Listo" in page.inner_text("#status")


def test_unsupported_site_error_is_shown(server, page):
    page.goto(server)
    page.fill("#url", "https://bad.example/v")
    page.click("#fetch")
    page.wait_for_selector("#error:not([hidden])")
    assert "no está soportado" in page.inner_text("#error")
    assert not page.is_visible("#card")


def search(page, server, url="https://example.com/v"):
    page.goto(server)
    page.fill("#url", url)
    page.click("#fetch")
    page.wait_for_selector("#card:not([hidden])")


def test_finished_job_counts_to_100_and_offers_the_file_again(server, page):
    search(page, server)
    assert not page.is_visible("#again")
    with page.expect_download(timeout=10000):
        page.click("#download")
    page.wait_for_selector("#again:not([hidden])")
    page.wait_for_function("document.getElementById('pct').textContent === '100'")
    assert "Listo: clip.mp4" in page.inner_text("#status")

    with page.expect_download(timeout=10000) as again:
        page.click("#again")
    assert again.value.suggested_filename == "clip.mp4"
    assert Path(again.value.path()).read_bytes() == b"data"


def test_busy_state_lasts_only_while_a_job_runs(server, page):
    search(page, server)
    assert not page.evaluate("document.body.classList.contains('busy')")
    with page.expect_download(timeout=10000):
        page.click("#download")
        assert page.evaluate("document.body.classList.contains('busy')")
    page.wait_for_function("!document.body.classList.contains('busy')")
    assert page.is_enabled("#download") and page.is_enabled("#paste")


def test_paste_button_reads_the_clipboard_and_searches(server, page):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=server)
    page.goto(server)
    page.evaluate("navigator.clipboard.writeText('https://example.com/v')")
    page.click("#paste")
    page.wait_for_selector("#card:not([hidden])")
    assert page.input_value("#url") == "https://example.com/v"


def test_paste_button_explains_what_to_do_when_the_clipboard_is_blocked(server, page):
    page.goto(server)
    # Written as a function body: a bare expression that returns a function would be *called* by evaluate().
    page.evaluate(
        "() => { navigator.clipboard.readText = () => Promise.reject(new DOMException('denied', 'NotAllowedError')); }"
    )
    page.click("#paste")
    page.wait_for_selector("#error:not([hidden])")
    assert "Ctrl+V" in page.inner_text("#error")
    assert not page.is_visible("#card")


def test_paste_button_with_an_empty_clipboard_says_so(server, page):
    page.goto(server)
    page.evaluate("() => { navigator.clipboard.readText = () => Promise.resolve('   '); }")
    page.click("#paste")
    page.wait_for_selector("#error:not([hidden])")
    assert "vacío" in page.inner_text("#error")
    assert not page.is_visible("#card")


PASTE_INTO_FIELD = """(text) => {
    const input = document.getElementById('url');
    input.value = text;
    input.dispatchEvent(new Event('paste'));
}"""


def test_pasting_a_link_into_the_field_searches_right_away(server, page):
    page.goto(server)
    page.evaluate(PASTE_INTO_FIELD, "https://example.com/v")
    page.wait_for_selector("#card:not([hidden])")


def test_pasting_a_link_that_is_not_http_does_not_search(server, page):
    # A valid URL for the browser's own type=url check, so only our handler can stop the search.
    page.goto(server)
    page.evaluate(PASTE_INTO_FIELD, "ftp://example.com/v")
    page.wait_for_timeout(300)  # negative check: give the handler's timer time to (not) fire
    assert not page.is_visible("#card")
    assert not page.is_visible("#error")


def search_another(page, url="https://example.com/other"):
    """Search again on the SAME page (no reload), to prove the page state was really reset."""
    page.fill("#url", url)
    page.click("#fetch")
    page.wait_for_selector("#card:not([hidden])")


def test_url_becomes_fixed_with_a_clear_button_once_the_video_is_found(server, page):
    page.goto(server)
    assert not page.is_visible("#clear")
    assert page.is_visible("#paste") and page.is_visible("#fetch")

    page.fill("#url", "https://example.com/v")
    page.click("#fetch")
    page.wait_for_selector("#card:not([hidden])")

    assert page.eval_on_selector("#url", "e => e.readOnly")
    assert page.is_visible("#clear")
    assert page.get_attribute("#clear", "aria-label")  # it is an icon, so it needs a name
    assert not page.is_visible("#paste") and not page.is_visible("#fetch")

    page.click("#url")
    page.keyboard.type("zzz")
    assert page.input_value("#url") == "https://example.com/v"


def test_enter_in_the_fixed_url_does_not_search_again(server, page):
    info_requests = []
    page.on("request", lambda r: info_requests.append(r.url) if r.url.endswith("/api/info") else None)
    search(page, server)
    assert len(info_requests) == 1

    page.click("#url")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)  # negative check: a second request would have gone out by now
    assert len(info_requests) == 1
    assert page.is_visible("#card")


def test_clear_button_returns_to_the_search_screen_in_default_mode(server, page):
    search(page, server)
    page.check('input[value="audio"]')
    page.select_option("#audio-format", "opus")
    page.click("#clear")

    assert page.input_value("#url") == ""
    assert not page.eval_on_selector("#url", "e => e.readOnly")
    assert page.evaluate("document.activeElement.id") == "url"
    assert not page.is_visible("#card")
    assert not page.is_visible("#error")
    assert not page.is_visible("#clear")
    assert page.is_visible("#paste") and page.is_visible("#fetch")

    # the next search starts in the default mode (video), not in the audio mode left behind
    search_another(page)
    assert page.is_checked('input[value="video"]')
    assert page.is_visible("#height") and not page.is_visible("#audio-format")
    assert page.input_value("#audio-format") == "mp3"  # the audio format is back to its default too


def test_clear_button_after_a_finished_download_resets_the_progress(server, page):
    search(page, server)
    with page.expect_download(timeout=10000):
        page.click("#download")
    page.wait_for_selector("#again:not([hidden])")

    page.click("#clear")
    assert not page.is_visible("#progress") and not page.is_visible("#again")

    search_another(page)
    assert not page.is_visible("#progress")
    assert page.inner_text("#pct") == "0"
    assert page.is_enabled("#download")


def test_clear_button_during_a_download_stops_following_it_without_saving_the_file(server, page):
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    search(page, server)
    page.click("#download")
    page.wait_for_selector("#progress:not([hidden])")
    page.click("#clear")

    page.wait_for_timeout(2500)  # negative check: longer than one poll (1 s) plus the fake runner (0.5 s)
    assert downloads == []
    assert not page.is_visible("#card") and not page.is_visible("#progress")
    assert page.is_enabled("#paste") and page.is_enabled("#fetch")

    # the page is usable right away: a new search and a new download work, and only that one is saved
    search_another(page)
    with page.expect_download(timeout=10000) as fresh:
        page.click("#download")
    assert Path(fresh.value.path()).read_bytes() == b"data"
    page.wait_for_timeout(300)
    assert len(downloads) == 1


def test_a_search_started_after_clearing_stays_busy_until_it_ends(server, page):
    search(page, server)
    page.click("#download")
    page.wait_for_selector("#progress:not([hidden])")
    page.click("#clear")
    page.fill("#url", "https://slow.example/v")
    page.click("#fetch")  # the fake server holds this search for 1.5 s

    # The abandoned download's loop wakes up after about 1 s; it must not free the buttons
    # of the search that is running now.
    page.wait_for_timeout(1200)
    assert page.is_disabled("#fetch") and page.is_disabled("#paste")
    page.wait_for_selector("#card:not([hidden])")

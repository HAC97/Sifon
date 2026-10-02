import re

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobManager
from app.main import WEB_DIR, create_app

# Ids that tests/e2e/test_ui_smoke.py and web/app.js rely on. If the page is redesigned again,
# these must survive or both sides are updated together.
REQUIRED_IDS = {
    "url-form", "url", "paste", "fetch", "error", "card", "thumb", "title", "byline",
    "height", "audio-format", "video-opt", "audio-opt", "download", "progress",
    "pct", "status", "detail", "bar", "again",
}


@pytest.fixture
def client(tmp_path):
    manager = JobManager(tmp_path / "jobs", lambda job, on_progress: job.dir)
    app = create_app(manager=manager, serve_web=True)
    yield TestClient(app, base_url="http://127.0.0.1")
    manager.shutdown()


def html():
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


def test_index_is_served_with_the_app_name(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "<title>sifón</title>" in res.text


def test_favicon_is_served_as_svg(client):
    res = client.get("/favicon.svg")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in res.text


def test_assets_referenced_by_the_page_exist():
    refs = re.findall(r'(?:href|src)="([^"#]+\.(?:css|js|svg))"', html())
    assert {"favicon.svg", "style.css", "app.js"} <= set(refs)
    for ref in refs:
        assert (WEB_DIR / ref).is_file(), f"index.html references missing file {ref}"


def test_every_id_used_by_app_js_exists_in_the_page():
    used = set(re.findall(r'\$\("([\w-]+)"\)', (WEB_DIR / "app.js").read_text(encoding="utf-8")))
    declared = set(re.findall(r'\bid="([\w-]+)"', html()))
    assert used, "no ids found in app.js: the extraction pattern is stale"
    assert used <= declared, f"app.js uses ids that index.html lacks: {sorted(used - declared)}"


def test_page_keeps_the_ids_other_code_depends_on():
    declared = re.findall(r'\bid="([\w-]+)"', html())
    assert REQUIRED_IDS <= set(declared), f"missing: {sorted(REQUIRED_IDS - set(declared))}"
    assert len(declared) == len(set(declared)), "duplicate ids in index.html"


def test_mode_radios_and_status_region_stay_accessible():
    page = html()
    assert 'name="mode" value="video"' in page and 'name="mode" value="audio"' in page
    assert re.search(r'id="status"[^>]*role="status"', page)
    assert re.search(r'<progress[^>]*aria-label="[^"]+"', page)
    assert re.search(r'id="error"[^>]*role="alert"', page)

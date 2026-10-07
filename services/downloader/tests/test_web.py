import re

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobManager
from app.main import WEB_DIR, create_app

# Ids that tests/e2e/test_ui_smoke.py and web/app.js rely on. If the page is redesigned again,
# these must survive or both sides are updated together.
REQUIRED_IDS = {
    "url-form", "url", "paste", "fetch", "clear", "error", "card", "thumb", "title", "byline",
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


# --- contrast of the colours in style.css (WCAG 2.x), both themes ---------------------------------
# A control's border, the focus ring and the progress outline need 3:1 (non-text); text needs 4.5:1.
# `--line` is only for dividers and the card edge, so it is deliberately not asserted.


def _tokens(block):
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def _themes():
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    light = _tokens(re.search(r":root\s*\{(.*?)\}", css, re.S).group(1))
    dark_block = re.search(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{(.*?)\}", css, re.S).group(1)
    return {"light": light, "dark": {**light, **_tokens(dark_block)}}


def _luminance(color):
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_control_borders_and_focus_colours_reach_3_to_1(theme):
    t = _themes()[theme]
    for foreground in ("edge", "accent"):
        for background in ("bg", "surface"):
            ratio = contrast(t[foreground], t[background])
            assert ratio >= 3, f"{theme}: --{foreground} on --{background} is {ratio:.2f}:1, needs 3:1"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_colours_reach_4_5_to_1(theme):
    t = _themes()[theme]
    pairs = [("ink", "bg"), ("ink", "surface"), ("muted", "bg"), ("muted", "surface"),
             ("accent-ink", "accent"), ("danger", "danger-bg")]
    for foreground, background in pairs:
        ratio = contrast(t[foreground], t[background])
        assert ratio >= 4.5, f"{theme}: --{foreground} on --{background} is {ratio:.2f}:1, needs 4.5:1"


def test_controls_use_the_edge_colour_not_the_divider_colour():
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    for selector in (r"\.drop", r"\.btn\.ghost", r"\.seg", r"\.field select", r"progress"):
        rule = re.search(r"(?m)^" + selector + r"\s*\{[^}]*\}", css)
        assert rule and "var(--edge)" in rule.group(0), f"{selector} must draw its border with --edge"


def test_forced_colors_keeps_the_focus_and_the_selected_option_visible():
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    block = re.search(r"@media \(forced-colors: active\)\s*\{(.*?)\n\}", css, re.S).group(1)
    assert ".drop:focus-within" in block and "outline" in block
    assert "input:checked" in block and "input:focus-visible" in block


def test_title_can_receive_focus_so_the_result_is_announced():
    assert '<h2 id="title" tabindex="-1">' in html()

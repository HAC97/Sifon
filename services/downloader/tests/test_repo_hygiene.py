"""Guards against committing build output or binaries (it happened once, before the first push)."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BINARY_SUFFIXES = (".exe", ".dll", ".pyd", ".zip", ".whl", ".msi", ".so", ".dylib", ".7z", ".mp4", ".mp3", ".m4a", ".opus")
# Binary files that are part of the documentation on purpose.
ALLOWED = {"docs/screenshot.png"}


def tracked_files() -> list[str]:
    done = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        pytest.skip("not a git checkout")
    return done.stdout.splitlines()


def test_no_binaries_or_build_output_are_tracked():
    bad = [
        f for f in tracked_files()
        if f.lower().endswith(BINARY_SUFFIXES) or f.split("/")[0] in ("dist", "build")
    ]
    assert bad == [], f"do not commit these: {bad[:10]}"


def test_only_the_documentation_screenshot_is_a_tracked_image():
    images = [f for f in tracked_files() if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".ico"))]
    assert set(images) <= ALLOWED, images


def test_gitignore_covers_the_package_build_output():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/dist/" in lines and "/build/" in lines

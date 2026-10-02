"""Smoke test of the built package, run exactly as a user's machine would see it.

    python packaging/smoke_test.py dist/sifon --ytdlp-src <site-packages>   # offline checks
    python packaging/smoke_test.py dist/sifon --ytdlp-src <site-packages> --online   # + real downloads

The program starts with a PATH that has only the Windows folders: no Python, FFmpeg, Deno or
Node. Everything it needs must come from the package. Exits 0 only if every check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return bool(ok)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def clean_env(data_dir: Path) -> dict:
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    return {
        "PATH": f"{windows}\\System32;{windows}",
        "SystemRoot": windows,
        "TEMP": os.environ.get("TEMP", ""), "TMP": os.environ.get("TMP", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""), "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "SIFON_DATA_DIR": str(data_dir),
        "SIFON_NO_AUTO_UPDATE": "1",  # the smoke test must not depend on PyPI
    }


def same_version(a: str, b: str) -> bool:
    """'2026.08.19' (yt-dlp's own string) and '2026.8.19' (package metadata) are the same release."""
    return [int(x) for x in re.findall(r"\d+", a)] == [int(x) for x in re.findall(r"\d+", b)]


def get_json(port: int, path: str, timeout=5.0):
    with DIRECT.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read())


def post_json(port: int, path: str, payload: dict, timeout=120.0):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with DIRECT.open(request, timeout=timeout) as r:
        return json.loads(r.read())


def wait_health(port: int, proc: subprocess.Popen | None = None, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return None
        try:
            return get_json(port, "/api/health", 2.0)
        except (OSError, ValueError):
            time.sleep(0.3)
    return None


class Running:
    """The program started headless, stopped through its stop file."""

    def __init__(self, exe: Path, data_dir: Path, extra_env: dict | None = None):
        self.exe, self.data_dir = exe, data_dir
        self.port = free_port()
        env = {**clean_env(data_dir), **(extra_env or {})}
        self.proc = subprocess.Popen(
            [str(exe), "--no-window", "--no-browser", "--port", str(self.port)], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.health = wait_health(self.port, self.proc)

    def stop(self, timeout=40.0) -> bool:
        (self.data_dir / "stop.request").write_text("stop")
        try:
            self.proc.wait(timeout)
            return True
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return False


def run_offline(package: Path, ytdlp_src: Path | None) -> None:
    exe = package / "sifon.exe"
    check("sifon.exe exists", exe.is_file())
    for tool in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        check(f"bin/{tool} is bundled", (package / "bin" / tool).is_file())
    for lic in ("LICENSE", "THIRD_PARTY.md", "BUNDLED.txt", "FFmpeg-LICENSE.txt", "Deno-LICENSE.md"):
        check(f"licenses/{lic} is bundled", (package / "licenses" / lic).is_file())

    env = clean_env(Path(tempfile.gettempdir()))
    for tool, args in (("ffmpeg", ["-version"]), ("ffprobe", ["-version"]), ("deno", ["--version"])):
        done = subprocess.run([str(package / "bin" / f"{tool}.exe"), *args], capture_output=True, text=True, env=env)
        check(f"{tool} runs from the package", done.returncode == 0, done.stdout.splitlines()[0] if done.stdout else "")

    with tempfile.TemporaryDirectory(prefix="sifon-smoke-") as work:
        work = Path(work)
        for codec, ext in (("libmp3lame", "mp3"), ("libopus", "opus"), ("aac", "m4a")):
            out = work / f"t.{ext}"
            done = subprocess.run(
                [str(package / "bin" / "ffmpeg.exe"), "-y", "-f", "lavfi", "-i", "sine=d=1", "-c:a", codec, str(out)],
                capture_output=True, env=env,
            )
            check(f"bundled ffmpeg encodes {ext}", done.returncode == 0 and out.is_file() and out.stat().st_size > 500)

        data = work / "data"
        data.mkdir()
        app = Running(exe, data)
        try:
            h = app.health
            check("server starts and answers /api/health", bool(h))
            if h:
                bundled = json.loads(next((package / "_internal").rglob("bundled.json")).read_text())
                check("health reports the bundled ffmpeg, ffprobe and deno", h["ffmpeg"] and h["ffprobe"] and h["js_runtime"] == "deno", str(h))
                check("yt-dlp version is the bundled one", same_version(h["ytdlp_version"], bundled["yt_dlp"]), h["ytdlp_version"])
                with DIRECT.open(f"http://127.0.0.1:{app.port}/", timeout=5) as r:
                    page = r.read().decode("utf-8")
                check("the web page is served from the package", "sif" in page and "app.js" in page)
                check("the page's script is served", b"use strict" in DIRECT.open(f"http://127.0.0.1:{app.port}/app.js", timeout=5).read())
                check("instance file records the port", json.loads((data / "instance.json").read_text())["port"] == app.port)
                check("a log file is written to the data folder", (data / "logs" / "sifon.log").is_file())
                check("nothing is written inside the program folder", not (package / "jobs.log").exists())
                second = subprocess.run([str(exe), "--no-browser"], env=clean_env(data), timeout=40)
                check("a second launch exits cleanly and leaves the first running", second.returncode == 0 and bool(wait_health(app.port)))
        finally:
            stopped = app.stop()
        check("headless shutdown is clean", stopped and not (data / "instance.json").exists())
        time.sleep(1)
        check("the temp folder of the run is removed", not list(Path(tempfile.gettempdir()).glob(f"sifon-{app.proc.pid}")))

        if ytdlp_src is not None:
            run_overlay_checks(package, exe, work, ytdlp_src)


def make_overlay(src: Path, target: Path, version: str, broken=False) -> None:
    for name in ("yt_dlp", "yt_dlp_ejs"):
        shutil.copytree(src / name, target / name, ignore=shutil.ignore_patterns("__pycache__"))
    version_file = target / "yt_dlp" / "version.py"
    if broken:
        version_file.write_text("raise ImportError('broken')\n", encoding="utf-8")
    else:  # the real file with only the version replaced, so every other name stays importable
        text = re.sub(r"__version__ = '[^']*'", f"__version__ = '{version}'", version_file.read_text(encoding="utf-8"))
        version_file.write_text(text, encoding="utf-8")
    (target / "ok.json").write_text("{}")


def run_overlay_checks(package: Path, exe: Path, work: Path, src: Path) -> None:
    data = work / "data-overlay"
    overlay = data / "ytdlp" / "2099.1.1"
    make_overlay(src, overlay, "2099.1.1")
    done = subprocess.run([str(exe), "--selftest-ytdlp", str(overlay), "2099.1.1"], capture_output=True, text=True, env=clean_env(data), timeout=90)
    check("the packaged program can self-test an unpacked yt-dlp", done.returncode == 0 and "2099.1.1" in done.stdout, (done.stdout + done.stderr).strip()[:120])
    # yt-dlp writes '2099.01.01' while PyPI reports '2099.1.1': the real updater must treat them as one.
    padded = work / "padded" / "2099.01.01"
    make_overlay(src, padded, "2099.01.01")
    done = subprocess.run([str(exe), "--selftest-ytdlp", str(padded), "2099.1.1"], capture_output=True, text=True, env=clean_env(data), timeout=90)
    check("the packaged self-test accepts a zero-padded version for PyPI's normalised one", done.returncode == 0, (done.stdout + done.stderr).strip()[:100])
    shutil.rmtree(work / "padded", ignore_errors=True)

    app = Running(exe, data, {"SIFON_NO_AUTO_UPDATE": "1"})
    try:
        check("a downloaded yt-dlp is loaded in front of the bundled one", bool(app.health) and app.health["ytdlp_version"] == "2099.1.1", str(app.health and app.health["ytdlp_version"]))
    finally:
        app.stop()

    shutil.rmtree(overlay)
    broken = data / "ytdlp" / "2099.2.2"
    make_overlay(src, broken, "2099.2.2", broken=True)
    app = Running(exe, data)
    try:
        bundled = json.loads(next((package / "_internal").rglob("bundled.json")).read_text())["yt_dlp"]
        check("a broken update is skipped and the bundled yt-dlp runs", bool(app.health) and same_version(app.health["ytdlp_version"], bundled))
        check("a broken update is set aside", (data / "ytdlp" / "2099.2.2.bad").is_dir())
    finally:
        app.stop()


def run_online(package: Path) -> None:
    exe = package / "sifon.exe"
    with tempfile.TemporaryDirectory(prefix="sifon-smoke-online-") as work:
        data = Path(work)
        app = Running(exe, data)
        try:
            if not check("server starts (online run)", bool(app.health)):
                return
            url = "https://soundcloud.com/ethmusic/lostin-powers-she-so-heavy"
            info = post_json(app.port, "/api/info", {"url": url})
            check("/api/info reads a real page through the egress proxy", bool(info.get("title")), info.get("title", "")[:50])
            job = post_json(app.port, "/api/jobs", {"url": url, "mode": "audio", "audio_format": "mp3"})
            status = {}
            deadline = time.time() + 240
            while time.time() < deadline:
                status = get_json(app.port, f"/api/jobs/{job['job_id']}")
                if status["status"] in ("done", "error"):
                    break
                time.sleep(1)
            check("a real audio download finishes", status.get("status") == "done", str(status.get("error_code")))
            if status.get("status") == "done":
                with DIRECT.open(f"http://127.0.0.1:{app.port}/api/jobs/{job['job_id']}/file", timeout=60) as r:
                    content = r.read()
                target = data / "out.mp3"
                target.write_bytes(content)
                probe = subprocess.run(
                    [str(package / "bin" / "ffprobe.exe"), "-v", "error", "-show_entries", "stream=codec_name:format=duration", "-of", "json", str(target)],
                    capture_output=True, text=True,
                )
                parsed = json.loads(probe.stdout or "{}")
                check("the file is a real MP3 of the right length", parsed.get("streams", [{}])[0].get("codec_name") == "mp3" and abs(float(parsed["format"]["duration"]) - 143.2) < 3)
        finally:
            app.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--ytdlp-src", type=Path, help="site-packages with yt_dlp and yt_dlp_ejs, to build fake updates")
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    run_offline(args.package.resolve(), args.ytdlp_src)
    if args.online:
        run_online(args.package.resolve())
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

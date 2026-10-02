# VideoDownloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web app local, tipo cobalt: pegás la URL de un video, elegís Video o solo Audio, y el navegador descarga el archivo.

**Architecture:** Un servicio FastAPI (`services/downloader`) usa yt-dlp como librería y ffmpeg para fusionar y extraer audio. Los jobs corren en un pool de hilos con estado en memoria y el cliente consulta el progreso cada 1 s. Una UI vanilla (`web/`) se sirve desde el mismo proceso. El contrato OpenAPI vive en `contracts/` y un test impide que se desincronice del código.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, yt-dlp, ffmpeg/ffprobe, pytest, jsonschema, Playwright (solo e2e), HTML/JS/CSS vanilla.

**Spec:** `docs/superpowers/specs/2026-10-01-videodownloader-design.md`

## Global Constraints

- Servidor escucha solo en `127.0.0.1` (puerto por defecto 8000, parametrizable).
- yt-dlp se usa como librería Python, nunca parseando la salida del CLI.
- Selector de video: `bv*[height<=H]+ba/b[height<=H]` (o `bv*+ba/b` para `best`), salida `mp4`.
- Audio: `mp3` a 192k, `m4a` u `opus`, vía `FFmpegExtractAudio`.
- Alturas permitidas: 360, 480, 720, 1080, 1440, 2160 o `best`.
- Máximo 3 jobs simultáneos. TTL de archivos: 30 min después de terminar.
- Solo `http`/`https`; se rechazan hosts que resuelvan a direcciones no públicas.
- `noplaylist=True` y `playlist_items="1"`: solo el primer video.
- Códigos de error exactos: `INVALID_URL`, `UNSUPPORTED_SITE`, `LOGIN_REQUIRED`, `GEO_BLOCKED`, `FFMPEG_MISSING`, `NETWORK`, `UNKNOWN`.
- Gate tests: deterministas, sin red, menos de 2 s en total. Evals y e2e quedan fuera del gate por marcador.
- Sin frameworks de frontend ni paso de build.
- Textos de UI y errores en español.
- Nunca se loguea la URL completa, solo el host.
- Cada commit termina con `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

Convención de comandos (PowerShell, desde la raíz del worktree): `PY` significa `.\services\downloader\.venv\Scripts\python.exe`. Se escribe completo en cada paso.

## Review Focus

Entradas que la spec implica pero no nombra, de más a menos probable de romper algo:

1. URL mal formada (sin esquema, con espacios o saltos de línea, de más de 2048 caracteres, `http://[::1`): debe dar `400 INVALID_URL`, nunca un 500. Tests en Task 1 y Task 5.
2. Host que resuelve a loopback, red privada, link-local, CGNAT, IPv6 o IPv4 mapeada en IPv6, o forma decimal (`http://2130706433/`), o resolución mixta pública y privada: se bloquea. Tests en Task 1.
3. Título con emoji, acentos o HTML (`<b>x</b>`): el archivo se entrega con `Content-Disposition` correcto y la UI lo muestra como texto, sin interpretarlo. Tests en Task 5 y Task 7.
4. Estado o archivo de un job inexistente, con id con forma de path traversal, o que aún no terminó: 404 o 409, nunca 500 ni lectura fuera del directorio del job. Tests en Task 5.
5. URL de playlist o con `&list=`: solo se baja el primer video. Test en Task 2.

---

### Task 1: Scaffolding, errores y validación de URL

**Files:**
- Create: `.gitignore`
- Create: `services/downloader/requirements.txt`, `services/downloader/requirements-dev.txt`, `services/downloader/pytest.ini`
- Create: `services/downloader/app/__init__.py` (vacío)
- Create: `services/downloader/app/errors.py`, `services/downloader/app/urlcheck.py`
- Test: `services/downloader/tests/test_errors.py`, `services/downloader/tests/test_urlcheck.py`

**Interfaces:**
- Produces: `ErrorCode` (str Enum con los 7 códigos), `USER_MESSAGES: dict[ErrorCode, str]`, `DownloadFailure(code: ErrorCode, message: str | None = None)` con atributos `.code` y `.message`, `map_error(message: str) -> ErrorCode`, `validate_url(url: str, resolver=socket.getaddrinfo) -> str` (devuelve la URL sin espacios laterales o lanza `DownloadFailure(INVALID_URL)`).

- [ ] **Step 1: Scaffolding y entorno**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.log
services/downloader/evals/results/
node_modules/
```

`services/downloader/requirements.txt`:
```
fastapi>=0.115
uvicorn[standard]>=0.30
yt-dlp
```

`services/downloader/requirements-dev.txt`:
```
-r requirements.txt
pytest>=8
httpx>=0.27
jsonschema>=4.22
playwright>=1.45
```

`services/downloader/pytest.ini`:
```
[pytest]
pythonpath = .
testpaths = tests
addopts = -m "not e2e and not eval"
markers =
    e2e: browser smoke test (needs playwright chromium)
    eval: hits real sites (needs network)
```

Crear el entorno:
```powershell
python -m venv services\downloader\.venv
.\services\downloader\.venv\Scripts\python.exe -m pip install -r services\downloader\requirements-dev.txt
```
Expected: instalación sin errores; `.\services\downloader\.venv\Scripts\python.exe -c "import fastapi, yt_dlp; print('ok')"` imprime `ok`.

- [ ] **Step 2: Write the failing tests**

`services/downloader/tests/test_errors.py`:
```python
import pytest

from app.errors import USER_MESSAGES, DownloadFailure, ErrorCode, map_error


@pytest.mark.parametrize(
    "message, expected",
    [
        ("ERROR: Unsupported URL: https://example.com/x", ErrorCode.UNSUPPORTED_SITE),
        ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: Private video. Sign in if you've been granted access", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: This video is not available in your country", ErrorCode.GEO_BLOCKED),
        ("ERROR: The uploader has blocked it in your country on copyright grounds", ErrorCode.GEO_BLOCKED),
        ("ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install", ErrorCode.FFMPEG_MISSING),
        ("ERROR: You have requested merging of multiple formats but ffmpeg is not installed", ErrorCode.FFMPEG_MISSING),
        ("ERROR: Unable to download webpage: <urlopen error timed out>", ErrorCode.NETWORK),
        ("ERROR: [Errno 11001] getaddrinfo failed", ErrorCode.NETWORK),
        ("ERROR: something nobody has seen before", ErrorCode.UNKNOWN),
        ("", ErrorCode.UNKNOWN),
    ],
)
def test_map_error(message, expected):
    assert map_error(message) == expected


def test_ffmpeg_wins_over_generic_download_words():
    # "Unable to download" alone is NETWORK, but a missing ffmpeg must be reported as such.
    assert map_error("Unable to download: ffprobe and ffmpeg not found") == ErrorCode.FFMPEG_MISSING


def test_every_code_has_a_spanish_user_message():
    assert set(USER_MESSAGES) == set(ErrorCode)
    assert all(msg.strip() for msg in USER_MESSAGES.values())


def test_download_failure_defaults_to_user_message():
    failure = DownloadFailure(ErrorCode.GEO_BLOCKED)
    assert failure.code == ErrorCode.GEO_BLOCKED
    assert failure.message == USER_MESSAGES[ErrorCode.GEO_BLOCKED]


def test_download_failure_accepts_custom_message():
    assert DownloadFailure(ErrorCode.INVALID_URL, "custom").message == "custom"
```

`services/downloader/tests/test_urlcheck.py`:
```python
import socket

import pytest

from app.errors import DownloadFailure, ErrorCode
from app.urlcheck import validate_url


def resolver_for(*ips):
    def _resolve(host, port, *args, **kwargs):
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))
            for ip in ips
        ]

    return _resolve


PUBLIC = resolver_for("93.184.216.34")


def test_accepts_public_https_url():
    url = "https://example.com/watch?v=1"
    assert validate_url(url, PUBLIC) == url


def test_accepts_http_and_strips_outer_whitespace():
    assert validate_url("  http://example.com/a \n", PUBLIC) == "http://example.com/a"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "ftp://example.com/a",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "youtube.com/watch?v=1",
        "http://",
        "https://",
        "https://exa mple.com/",
        "https://example.com/a\nb",
        "https://example.com/" + "a" * 3000,
        "http://[::1",
    ],
)
def test_rejects_malformed_urls(bad):
    with pytest.raises(DownloadFailure) as exc:
        validate_url(bad, PUBLIC)
    assert exc.value.code == ErrorCode.INVALID_URL


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_rejects_hosts_resolving_to_non_public_addresses(ip):
    with pytest.raises(DownloadFailure) as exc:
        validate_url("https://innocent.example/v", resolver_for(ip))
    assert exc.value.code == ErrorCode.INVALID_URL


def test_rejects_decimal_ip_host_that_resolves_to_loopback():
    with pytest.raises(DownloadFailure):
        validate_url("http://2130706433/", resolver_for("127.0.0.1"))


def test_rejects_when_any_resolved_address_is_private():
    with pytest.raises(DownloadFailure):
        validate_url("https://rebind.example/v", resolver_for("93.184.216.34", "10.0.0.1"))


def test_rejects_unresolvable_host():
    def boom(host, port, *args, **kwargs):
        raise socket.gaierror("no such host")

    with pytest.raises(DownloadFailure) as exc:
        validate_url("https://does-not-exist.invalid/v", boom)
    assert exc.value.code == ErrorCode.INVALID_URL
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q`
Expected: collection errors, `ModuleNotFoundError: No module named 'app.errors'`.

- [ ] **Step 4: Write minimal implementation**

`services/downloader/app/errors.py`:
```python
from enum import Enum


class ErrorCode(str, Enum):
    INVALID_URL = "INVALID_URL"
    UNSUPPORTED_SITE = "UNSUPPORTED_SITE"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    GEO_BLOCKED = "GEO_BLOCKED"
    FFMPEG_MISSING = "FFMPEG_MISSING"
    NETWORK = "NETWORK"
    UNKNOWN = "UNKNOWN"


USER_MESSAGES = {
    ErrorCode.INVALID_URL: "La URL no es válida. Pegá un enlace completo que empiece con http:// o https://.",
    ErrorCode.UNSUPPORTED_SITE: "Este sitio o enlace no está soportado.",
    ErrorCode.LOGIN_REQUIRED: "El video es privado o requiere iniciar sesión, y esta app no soporta login.",
    ErrorCode.GEO_BLOCKED: "El video no está disponible en tu país.",
    ErrorCode.FFMPEG_MISSING: "No se encontró ffmpeg. Instalalo y reiniciá la app.",
    ErrorCode.NETWORK: "Falló la conexión con el sitio. Revisá tu internet y probá de nuevo.",
    ErrorCode.UNKNOWN: "No se pudo descargar el video. Probá de nuevo o actualizá yt-dlp.",
}


class DownloadFailure(Exception):
    def __init__(self, code: ErrorCode, message: str | None = None):
        self.code = code
        self.message = message or USER_MESSAGES[code]
        super().__init__(self.message)


# First match wins, so the specific causes come before the generic NETWORK words.
_RULES = [
    (
        ErrorCode.FFMPEG_MISSING,
        ("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed"),
    ),
    (ErrorCode.UNSUPPORTED_SITE, ("unsupported url",)),
    (
        ErrorCode.LOGIN_REQUIRED,
        ("sign in", "log in", "login", "private video", "members-only", "confirm your age", "age-restricted"),
    ),
    (
        ErrorCode.GEO_BLOCKED,
        ("not available in your country", "blocked it in your country", "geo restriction", "geo-restricted"),
    ),
    (
        ErrorCode.NETWORK,
        (
            "timed out",
            "connection",
            "name or service not known",
            "getaddrinfo",
            "unable to download",
            "temporary failure in name resolution",
        ),
    ),
]


def map_error(message: str) -> ErrorCode:
    text = message.lower()
    for code, needles in _RULES:
        if any(needle in text for needle in needles):
            return code
    return ErrorCode.UNKNOWN
```

`services/downloader/app/urlcheck.py`:
```python
import ipaddress
import socket
from urllib.parse import urlsplit

from app.errors import DownloadFailure, ErrorCode

MAX_URL_LENGTH = 2048


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (not ip.is_global) or ip.is_multicast


def validate_url(url: str, resolver=socket.getaddrinfo) -> str:
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH or any(c.isspace() or ord(c) < 32 for c in url):
        raise DownloadFailure(ErrorCode.INVALID_URL)
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise DownloadFailure(ErrorCode.INVALID_URL) from None
    if parts.scheme not in ("http", "https") or not host:
        raise DownloadFailure(ErrorCode.INVALID_URL)
    try:
        infos = resolver(host, None)
    except (socket.gaierror, UnicodeError):
        raise DownloadFailure(ErrorCode.INVALID_URL, "No se pudo resolver el host de la URL.") from None
    for info in infos:
        address = info[4][0].split("%")[0]
        if _is_blocked(ipaddress.ip_address(address)):
            raise DownloadFailure(
                ErrorCode.INVALID_URL,
                "Esa dirección apunta a una red local o reservada y está bloqueada.",
            )
    return url
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add .gitignore services
git commit -m "feat(downloader): error codes and SSRF-safe URL validation"
```
(Agregar la línea `Co-Authored-By` indicada en Global Constraints.)

---

### Task 2: Opciones de yt-dlp (formatos)

**Files:**
- Create: `services/downloader/app/formats.py`
- Test: `services/downloader/tests/test_formats.py`

**Interfaces:**
- Produces: `HEIGHTS: tuple[str, ...]`, `AUDIO_CODECS: dict[str, str]`, `OUTTMPL: str`, `video_selector(height: str = "best") -> str`, `ytdlp_options(mode: str, height: str, audio_format: str, outtmpl: str, progress_hook, postprocessor_hook=None) -> dict`. Lanzan `ValueError` ante valores fuera de contrato.

- [ ] **Step 1: Write the failing tests**

`services/downloader/tests/test_formats.py`:
```python
import pytest

from app.formats import HEIGHTS, OUTTMPL, video_selector, ytdlp_options


def noop(_):
    pass


def test_best_selector_has_no_height_filter():
    assert video_selector("best") == "bv*+ba/b"


@pytest.mark.parametrize("height", HEIGHTS)
def test_height_selector_caps_resolution(height):
    assert video_selector(height) == f"bv*[height<={height}]+ba/b[height<={height}]"


@pytest.mark.parametrize("bad", ["999", "", "1080p", "-1", "best; rm"])
def test_invalid_height_rejected(bad):
    with pytest.raises(ValueError):
        video_selector(bad)


def test_video_options_merge_to_mp4_and_prefer_compatible_codecs():
    opts = ytdlp_options("video", "720", "mp3", "C:/t/%(title)s.%(ext)s", noop)
    assert opts["format"] == "bv*[height<=720]+ba/b[height<=720]"
    assert opts["merge_output_format"] == "mp4"
    assert opts["format_sort"] == ["res", "ext:mp4:m4a"]
    assert "postprocessors" not in opts


def test_mp3_audio_options_use_192k():
    opts = ytdlp_options("audio", "best", "mp3", "x", noop)
    assert opts["format"] == "bestaudio/best"
    assert opts["postprocessors"] == [
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
    ]


@pytest.mark.parametrize("fmt", ["m4a", "opus"])
def test_other_audio_formats_have_no_forced_bitrate(fmt):
    opts = ytdlp_options("audio", "best", fmt, "x", noop)
    assert opts["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": fmt}]


def test_playlists_are_limited_to_first_item():
    for mode in ("video", "audio"):
        opts = ytdlp_options(mode, "best", "mp3", "x", noop)
        assert opts["noplaylist"] is True
        assert opts["playlist_items"] == "1"


def test_hooks_and_outtmpl_are_wired():
    pp = lambda d: None  # noqa: E731
    opts = ytdlp_options("video", "best", "mp3", "OUT", noop, pp)
    assert opts["outtmpl"] == "OUT"
    assert opts["progress_hooks"] == [noop]
    assert opts["postprocessor_hooks"] == [pp]


def test_invalid_mode_and_audio_format_rejected():
    with pytest.raises(ValueError):
        ytdlp_options("gif", "best", "mp3", "x", noop)
    with pytest.raises(ValueError):
        ytdlp_options("audio", "best", "wav", "x", noop)


def test_outtmpl_truncates_title_and_includes_id():
    assert "%(title).120s" in OUTTMPL
    assert "[%(id)s]" in OUTTMPL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests\test_formats.py -q`
Expected: `ModuleNotFoundError: No module named 'app.formats'`.

- [ ] **Step 3: Write minimal implementation**

`services/downloader/app/formats.py`:
```python
HEIGHTS = ("360", "480", "720", "1080", "1440", "2160")
AUDIO_CODECS = {"mp3": "mp3", "m4a": "m4a", "opus": "opus"}

# 120 chars keeps the full path under Windows' 260 limit even inside the temp dir.
OUTTMPL = "%(title).120s [%(id)s].%(ext)s"


def video_selector(height: str = "best") -> str:
    if height == "best":
        return "bv*+ba/b"
    if height not in HEIGHTS:
        raise ValueError(f"invalid height: {height!r}")
    cap = f"[height<={height}]"
    return f"bv*{cap}+ba/b{cap}"


def ytdlp_options(
    mode: str,
    height: str,
    audio_format: str,
    outtmpl: str,
    progress_hook,
    postprocessor_hook=None,
) -> dict:
    opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
        "socket_timeout": 20,
        "retries": 3,
        "progress_hooks": [progress_hook],
    }
    if postprocessor_hook is not None:
        opts["postprocessor_hooks"] = [postprocessor_hook]

    if mode == "video":
        opts["format"] = video_selector(height)
        # Resolution first, then prefer mp4/m4a so the mp4 merge is a plain remux when possible.
        opts["format_sort"] = ["res", "ext:mp4:m4a"]
        opts["merge_output_format"] = "mp4"
    elif mode == "audio":
        if audio_format not in AUDIO_CODECS:
            raise ValueError(f"invalid audio format: {audio_format!r}")
        opts["format"] = "bestaudio/best"
        processor = {"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_CODECS[audio_format]}
        if audio_format == "mp3":
            processor["preferredquality"] = "192"
        opts["postprocessors"] = [processor]
    else:
        raise ValueError(f"invalid mode: {mode!r}")
    return opts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add services
git commit -m "feat(downloader): yt-dlp option builder for video and audio"
```

---

### Task 3: Gestor de jobs

**Files:**
- Create: `services/downloader/app/jobs.py`
- Test: `services/downloader/tests/test_jobs.py`

**Interfaces:**
- Consumes: `DownloadFailure`, `ErrorCode`, `USER_MESSAGES` (Task 1).
- Produces:
  - `Job` dataclass con campos `id, url, mode, height, audio_format, dir: Path, status, percent, speed, eta, filename, error_code, error_message, created_at, started_at, finished_at, file_path` y método `snapshot() -> dict` con las claves `status, percent, speed, eta, filename, error_code, error_message`.
  - `JobManager(base_dir, runner, max_workers=3, ttl_seconds=1800, clock=time.time, log_path=None)` con `create(url, mode, height="best", audio_format="mp3") -> Job`, `get(job_id) -> Job | None`, `cleanup() -> int`, `start_sweeper(interval=60.0)`, `shutdown()` y la propiedad `base_dir`.
  - Contrato del runner: `runner(job, on_progress) -> Path`. `on_progress` recibe dicts de yt-dlp (`status: "downloading"` con `downloaded_bytes`, `total_bytes` o `total_bytes_estimate`, `speed`, `eta`) o `{"status": "processing"}`. El runner lanza `DownloadFailure` para fallos esperados.

- [ ] **Step 1: Write the failing tests**

`services/downloader/tests/test_jobs.py`:
```python
import json
import threading
import time

import pytest

from app.errors import DownloadFailure, ErrorCode
from app.jobs import JobManager


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for condition")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def make_manager(tmp_path):
    made = []

    def _make(runner, **kwargs):
        manager = JobManager(tmp_path / f"base{len(made)}", runner, **kwargs)
        made.append(manager)
        return manager

    yield _make
    for manager in made:
        manager.shutdown()


def ok_runner(job, on_progress):
    path = job.dir / "out.mp4"
    path.write_bytes(b"x")
    return path


def test_successful_job_ends_done_with_file(make_manager):
    manager = make_manager(ok_runner)
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "done")
    assert job.filename == "out.mp4"
    assert job.percent == 100.0
    assert job.file_path.read_bytes() == b"x"
    assert job.snapshot()["error_code"] is None


def test_download_failure_is_reported_with_its_code(make_manager):
    def runner(job, on_progress):
        raise DownloadFailure(ErrorCode.GEO_BLOCKED)

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    wait_for(lambda: job.status == "error")
    assert job.error_code == "GEO_BLOCKED"
    assert job.error_message


def test_unexpected_exception_becomes_unknown_error(make_manager):
    def runner(job, on_progress):
        raise RuntimeError("boom")

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "audio")
    wait_for(lambda: job.status == "error")
    assert job.error_code == "UNKNOWN"


def test_progress_is_mapped_and_percent_never_goes_back(make_manager):
    mid, first, second = threading.Event(), threading.Event(), threading.Event()

    def runner(job, on_progress):
        on_progress({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 10.0, "eta": 5})
        on_progress({"status": "downloading", "downloaded_bytes": 20, "total_bytes": 100, "speed": 8.0, "eta": 9})
        mid.set()
        first.wait(3)
        on_progress({"status": "processing"})
        second.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    assert mid.wait(3)
    snap = job.snapshot()
    assert snap["status"] == "downloading"
    assert snap["percent"] == 50.0
    assert snap["speed"] == 8.0
    assert snap["eta"] == 9
    first.set()
    wait_for(lambda: job.status == "processing")
    assert job.speed is None
    second.set()
    wait_for(lambda: job.status == "done")
    assert job.percent == 100.0


def test_estimated_total_is_used_and_percent_is_capped_below_100(make_manager):
    mid, release = threading.Event(), threading.Event()

    def runner(job, on_progress):
        on_progress({"status": "downloading", "downloaded_bytes": 100, "total_bytes_estimate": 100})
        mid.set()
        release.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner)
    job = manager.create("https://example.com/v", "video")
    assert mid.wait(3)
    assert job.percent < 100.0
    release.set()
    wait_for(lambda: job.status == "done")


def test_at_most_max_workers_run_at_once(make_manager):
    release = threading.Event()

    def runner(job, on_progress):
        release.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner, max_workers=2)
    jobs = [manager.create(f"https://example.com/{i}", "video") for i in range(3)]
    wait_for(lambda: sorted(j.status for j in jobs) == ["downloading", "downloading", "queued"])
    assert len({j.dir for j in jobs}) == 3
    release.set()
    wait_for(lambda: all(j.status == "done" for j in jobs))


def test_cleanup_removes_only_expired_finished_jobs(make_manager):
    clock = Clock()
    hold = threading.Event()

    def runner(job, on_progress):
        if job.url.endswith("/slow"):
            hold.wait(3)
        return ok_runner(job, on_progress)

    manager = make_manager(runner, ttl_seconds=100, clock=clock)
    fast = manager.create("https://example.com/fast", "video")
    slow = manager.create("https://example.com/slow", "audio")
    wait_for(lambda: fast.status == "done")

    clock.t += 99
    assert manager.cleanup() == 0
    assert fast.dir.exists()

    clock.t += 2
    assert manager.cleanup() == 1
    assert manager.get(fast.id) is None
    assert not fast.dir.exists()
    assert manager.get(slow.id) is not None
    assert slow.dir.exists()
    hold.set()


def test_get_unknown_job_returns_none(make_manager):
    assert make_manager(ok_runner).get("nope") is None


def test_finished_job_is_logged_without_the_full_url(make_manager, tmp_path):
    log = tmp_path / "jobs.log"
    manager = make_manager(ok_runner, log_path=log)
    job = manager.create("https://example.com/watch?v=secret", "video")
    wait_for(lambda: job.status == "done")
    text = log.read_text(encoding="utf-8")
    entry = json.loads(text.splitlines()[0])
    assert entry["host"] == "example.com"
    assert entry["status"] == "done"
    assert entry["mode"] == "video"
    assert entry["job_id"] == job.id
    assert "duration_s" in entry
    assert "secret" not in text


def test_failed_job_log_has_error_code(make_manager, tmp_path):
    def runner(job, on_progress):
        raise DownloadFailure(ErrorCode.NETWORK)

    log = tmp_path / "jobs.log"
    manager = make_manager(runner, log_path=log)
    job = manager.create("https://example.com/v", "audio")
    wait_for(lambda: job.status == "error")
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert entry["status"] == "error"
    assert entry["error_code"] == "NETWORK"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests\test_jobs.py -q`
Expected: `ModuleNotFoundError: No module named 'app.jobs'`.

- [ ] **Step 3: Write minimal implementation**

`services/downloader/app/jobs.py`:
```python
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from app.errors import USER_MESSAGES, DownloadFailure, ErrorCode

log = logging.getLogger("videodownloader")

Runner = Callable[["Job", Callable[[dict], None]], Path]


@dataclass
class Job:
    id: str
    url: str
    mode: str
    height: str
    audio_format: str
    dir: Path
    status: str = "queued"
    percent: float = 0.0
    speed: float | None = None
    eta: float | None = None
    filename: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    file_path: Path | None = None

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "percent": self.percent,
            "speed": self.speed,
            "eta": self.eta,
            "filename": self.filename,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


class JobManager:
    def __init__(
        self,
        base_dir: Path,
        runner: Runner,
        max_workers: int = 3,
        ttl_seconds: float = 1800,
        clock: Callable[[], float] = time.time,
        log_path: Path | None = None,
    ):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._runner = runner
        self._ttl = ttl_seconds
        self._clock = clock
        self._log_path = Path(log_path) if log_path else None
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._stop = threading.Event()
        self._sweeper: threading.Thread | None = None

    @property
    def base_dir(self) -> Path:
        return self._base

    def create(self, url: str, mode: str, height: str = "best", audio_format: str = "mp3") -> Job:
        job_id = uuid.uuid4().hex
        job = Job(
            id=job_id,
            url=url,
            mode=mode,
            height=height,
            audio_format=audio_format,
            dir=self._base / job_id,
            created_at=self._clock(),
        )
        job.dir.mkdir(parents=True)
        with self._lock:
            self._jobs[job_id] = job
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cleanup(self) -> int:
        now = self._clock()
        with self._lock:
            expired_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if job.finished_at is not None and now - job.finished_at > self._ttl
            ]
            expired = [self._jobs.pop(job_id) for job_id in expired_ids]
        for job in expired:
            shutil.rmtree(job.dir, ignore_errors=True)
        return len(expired)

    def start_sweeper(self, interval: float = 60.0) -> None:
        if self._sweeper is not None:
            return

        def loop():
            while not self._stop.wait(interval):
                self.cleanup()

        self._sweeper = threading.Thread(target=loop, name="sweeper", daemon=True)
        self._sweeper.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
        shutil.rmtree(self._base, ignore_errors=True)

    def _run(self, job: Job) -> None:
        job.started_at = self._clock()
        job.status = "downloading"
        try:
            path = Path(self._runner(job, lambda d: self._on_progress(job, d)))
        except DownloadFailure as failure:
            self._finish(job, "error", failure.code, failure.message)
        except Exception:
            log.exception("job %s crashed", job.id)
            self._finish(job, "error", ErrorCode.UNKNOWN, USER_MESSAGES[ErrorCode.UNKNOWN])
        else:
            self._finish(job, "done", path=path)

    def _on_progress(self, job: Job, data: dict) -> None:
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if total:
                percent = min(data.get("downloaded_bytes", 0) / total * 100.0, 99.9)
                job.percent = max(job.percent, percent)
            job.speed = data.get("speed")
            job.eta = data.get("eta")
            job.status = "downloading"
        elif status == "processing":
            job.speed = None
            job.eta = None
            job.status = "processing"

    def _finish(
        self,
        job: Job,
        status: str,
        code: ErrorCode | None = None,
        message: str | None = None,
        path: Path | None = None,
    ) -> None:
        job.finished_at = self._clock()
        job.error_code = code.value if code else None
        job.error_message = message
        job.speed = None
        job.eta = None
        if path is not None:
            job.file_path = path
            job.filename = path.name
            job.percent = 100.0
        self._log(job, status)
        # Status flips last: anyone who sees "done"/"error" also sees a complete record and log line.
        job.status = status

    def _log(self, job: Job, status: str) -> None:
        if self._log_path is None:
            return
        started = job.started_at if job.started_at is not None else job.finished_at
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "job_id": job.id,
            "mode": job.mode,
            "status": status,
            "duration_s": round(job.finished_at - started, 2),
            "error_code": job.error_code,
            "host": urlsplit(job.url).hostname,
        }
        try:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError:
            log.exception("could not write jobs log")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add services
git commit -m "feat(downloader): job manager with pool, progress, TTL cleanup and jobs.log"
```

---

### Task 4: Runner de yt-dlp y extractor de info

**Files:**
- Create: `services/downloader/app/ytdlp_runner.py`, `services/downloader/app/extractor.py`
- Test: `services/downloader/tests/test_runner.py`, `services/downloader/tests/test_extractor.py`

**Interfaces:**
- Consumes: `ytdlp_options`, `OUTTMPL` (Task 2); `Job`, la forma del runner y de `on_progress` (Task 3); `DownloadFailure`, `ErrorCode`, `map_error` (Task 1).
- Produces:
  - `find_output(job_dir: Path) -> Path` y `run_download(job, on_progress, ytdlp_cls=yt_dlp.YoutubeDL, which=shutil.which) -> Path`.
  - `summarize_info(raw: dict) -> dict` y `fetch_info(url: str, ytdlp_cls=yt_dlp.YoutubeDL) -> dict`. El resultado tiene las claves `title, thumbnail, duration, uploader, heights` (lista de int, descendente).

- [ ] **Step 1: Write the failing tests**

`services/downloader/tests/test_runner.py`:
```python
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode
from app.jobs import Job
from app.ytdlp_runner import find_output, run_download


def make_job(tmp_path, mode="video"):
    return Job(id="j", url="https://example.com/v", mode=mode, height="best", audio_format="mp3", dir=tmp_path)


def fake_ydl(error=None):
    class FakeYDL:
        instances = []

        def __init__(self, opts):
            self.opts = opts
            FakeYDL.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            if error is not None:
                raise error
            out = Path(self.opts["outtmpl"]).parent / "Title [abc].mp4"
            self.opts["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})
            self.opts["postprocessor_hooks"][0]({"status": "started"})
            out.write_bytes(b"x")

    return FakeYDL


def has_ffmpeg(_name):
    return "ffmpeg"


def test_run_download_returns_output_and_forwards_progress(tmp_path):
    events = []
    cls = fake_ydl()
    path = run_download(make_job(tmp_path), events.append, ytdlp_cls=cls, which=has_ffmpeg)
    assert path == tmp_path / "Title [abc].mp4"
    assert [e["status"] for e in events] == ["downloading", "processing"]
    assert cls.instances[0].opts["outtmpl"].startswith(str(tmp_path))


def test_missing_ffmpeg_fails_before_touching_yt_dlp(tmp_path):
    cls = fake_ydl()
    with pytest.raises(DownloadFailure) as exc:
        run_download(make_job(tmp_path), lambda d: None, ytdlp_cls=cls, which=lambda _n: None)
    assert exc.value.code == ErrorCode.FFMPEG_MISSING
    assert cls.instances == []


def test_download_error_is_mapped(tmp_path):
    cls = fake_ydl(DownloadError("ERROR: Unsupported URL: https://example.com/v"))
    with pytest.raises(DownloadFailure) as exc:
        run_download(make_job(tmp_path), lambda d: None, ytdlp_cls=cls, which=has_ffmpeg)
    assert exc.value.code == ErrorCode.UNSUPPORTED_SITE


def test_audio_job_passes_audio_options(tmp_path):
    cls = fake_ydl()
    run_download(make_job(tmp_path, "audio"), lambda d: None, ytdlp_cls=cls, which=has_ffmpeg)
    assert cls.instances[0].opts["postprocessors"][0]["preferredcodec"] == "mp3"


def test_find_output_ignores_partial_files_and_picks_largest(tmp_path):
    (tmp_path / "a.mp4.part").write_bytes(b"x" * 500)
    (tmp_path / "a.ytdl").write_bytes(b"x" * 500)
    (tmp_path / "small.mp4").write_bytes(b"x")
    (tmp_path / "big.mp4").write_bytes(b"xxxx")
    assert find_output(tmp_path) == tmp_path / "big.mp4"


def test_find_output_without_files_is_unknown_failure(tmp_path):
    (tmp_path / "only.part").write_bytes(b"x")
    with pytest.raises(DownloadFailure) as exc:
        find_output(tmp_path)
    assert exc.value.code == ErrorCode.UNKNOWN
```

`services/downloader/tests/test_extractor.py`:
```python
import pytest
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode
from app.extractor import fetch_info, summarize_info

RAW = {
    "title": "Me at the zoo",
    "thumbnail": "https://img.example/t.jpg",
    "duration": 19,
    "uploader": "jawed",
    "formats": [
        {"format_id": "140", "height": None, "vcodec": "none"},
        {"format_id": "18", "height": 360, "vcodec": "avc1"},
        {"format_id": "22", "height": 720, "vcodec": "avc1"},
        {"format_id": "137", "height": 720, "vcodec": "avc1"},
        {"format_id": "x", "height": 1080, "vcodec": None},
    ],
}


def test_summarize_lists_unique_video_heights_descending():
    info = summarize_info(RAW)
    assert info == {
        "title": "Me at the zoo",
        "thumbnail": "https://img.example/t.jpg",
        "duration": 19,
        "uploader": "jawed",
        "heights": [1080, 720, 360],
    }


def test_summarize_fills_defaults_for_sparse_info():
    info = summarize_info({"formats": []})
    assert info["title"] == "video"
    assert info["heights"] == []
    assert info["thumbnail"] is None
    assert info["uploader"] is None


def test_summarize_uses_channel_when_uploader_missing():
    assert summarize_info({"title": "t", "channel": "chan"})["uploader"] == "chan"


def test_summarize_takes_first_entry_of_a_playlist():
    raw = {"_type": "playlist", "entries": [None, RAW, {"title": "second"}]}
    assert summarize_info(raw)["title"] == "Me at the zoo"


def test_summarize_empty_playlist_is_unknown_failure():
    with pytest.raises(DownloadFailure) as exc:
        summarize_info({"_type": "playlist", "entries": []})
    assert exc.value.code == ErrorCode.UNKNOWN


def fake_ydl(raw=None, error=None):
    class FakeYDL:
        opts = None

        def __init__(self, opts):
            FakeYDL.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            if error is not None:
                raise error
            return raw

        def sanitize_info(self, info):
            return info

    return FakeYDL


def test_fetch_info_returns_summary_and_disables_playlists():
    cls = fake_ydl(raw=RAW)
    assert fetch_info("https://example.com/v", ytdlp_cls=cls)["title"] == "Me at the zoo"
    assert cls.opts["noplaylist"] is True
    assert cls.opts["playlist_items"] == "1"
    assert cls.opts["skip_download"] is True


def test_fetch_info_maps_download_errors():
    cls = fake_ydl(error=DownloadError("ERROR: Unsupported URL: x"))
    with pytest.raises(DownloadFailure) as exc:
        fetch_info("https://example.com/v", ytdlp_cls=cls)
    assert exc.value.code == ErrorCode.UNSUPPORTED_SITE


def test_fetch_info_none_result_is_unknown_failure():
    with pytest.raises(DownloadFailure) as exc:
        fetch_info("https://example.com/v", ytdlp_cls=fake_ydl(raw=None))
    assert exc.value.code == ErrorCode.UNKNOWN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests\test_runner.py services\downloader\tests\test_extractor.py -q`
Expected: `ModuleNotFoundError: No module named 'app.ytdlp_runner'`.

- [ ] **Step 3: Write minimal implementation**

`services/downloader/app/ytdlp_runner.py`:
```python
from __future__ import annotations

import shutil
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode, map_error
from app.formats import OUTTMPL, ytdlp_options

_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp")


def find_output(job_dir: Path) -> Path:
    candidates = [
        p for p in job_dir.iterdir() if p.is_file() and not p.name.endswith(_PARTIAL_SUFFIXES)
    ]
    if not candidates:
        raise DownloadFailure(ErrorCode.UNKNOWN)
    return max(candidates, key=lambda p: p.stat().st_size)


def run_download(job, on_progress, ytdlp_cls=yt_dlp.YoutubeDL, which=shutil.which) -> Path:
    if which("ffmpeg") is None:
        raise DownloadFailure(ErrorCode.FFMPEG_MISSING)

    def postprocessor_hook(data: dict) -> None:
        if data.get("status") == "started":
            on_progress({"status": "processing"})

    opts = ytdlp_options(
        job.mode,
        job.height,
        job.audio_format,
        str(job.dir / OUTTMPL),
        on_progress,
        postprocessor_hook,
    )
    try:
        with ytdlp_cls(opts) as ydl:
            ydl.download([job.url])
    except DownloadError as error:
        raise DownloadFailure(map_error(str(error))) from error
    return find_output(job.dir)
```

`services/downloader/app/extractor.py`:
```python
from __future__ import annotations

import yt_dlp
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode, map_error


def summarize_info(raw: dict) -> dict:
    if raw.get("_type") == "playlist" or "entries" in raw:
        entries = [entry for entry in (raw.get("entries") or []) if entry]
        if not entries:
            raise DownloadFailure(ErrorCode.UNKNOWN)
        raw = entries[0]
    heights = sorted(
        {
            int(fmt["height"])
            for fmt in raw.get("formats") or []
            if fmt.get("height") and fmt.get("vcodec") != "none"
        },
        reverse=True,
    )
    return {
        "title": raw.get("title") or "video",
        "thumbnail": raw.get("thumbnail"),
        "duration": raw.get("duration"),
        "uploader": raw.get("uploader") or raw.get("channel"),
        "heights": heights,
    }


def fetch_info(url: str, ytdlp_cls=yt_dlp.YoutubeDL) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlist_items": "1",
        "skip_download": True,
        "socket_timeout": 20,
    }
    try:
        with ytdlp_cls(opts) as ydl:
            raw = ydl.extract_info(url, download=False)
            if raw is None:
                raise DownloadFailure(ErrorCode.UNKNOWN)
            return summarize_info(ydl.sanitize_info(raw))
    except DownloadError as error:
        raise DownloadFailure(map_error(str(error))) from error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add services
git commit -m "feat(downloader): yt-dlp runner and info extractor"
```

---

### Task 5: API HTTP y contrato OpenAPI

**Files:**
- Create: `services/downloader/app/main.py`, `scripts/gen_contract.py`, `contracts/api.openapi.json` (generado)
- Test: `services/downloader/tests/test_api.py`, `services/downloader/tests/test_contract.py`

**Interfaces:**
- Consumes: `JobManager` (Task 3), `fetch_info` (Task 4), `run_download` (Task 4), `validate_url` (Task 1), `DownloadFailure`, `ErrorCode` (Task 1).
- Produces:
  - `create_app(manager=None, info_fetcher=fetch_info, url_validator=validate_url, serve_web=True) -> FastAPI`, y `contract() -> dict`. Cuando `manager` es `None` se crea uno con directorio temporal `<tmp>/videodownloader` (se vacía al arrancar), `run_download` y log en `services/downloader/jobs.log`.
  - Endpoints: `POST /api/info` (200), `POST /api/jobs` (202, `{job_id}`), `GET /api/jobs/{id}`, `GET /api/jobs/{id}/file`, `GET /api/health`.
  - Los `DownloadFailure` devuelven `400` con `{"error_code", "error_message"}`. Job inexistente: 404. Archivo no listo: 409.
  - Se sirve `web/` en `/` si existe.

- [ ] **Step 1: Write the failing tests**

`services/downloader/tests/test_api.py`:
```python
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.errors import DownloadFailure, ErrorCode
from app.jobs import JobManager
from app.main import create_app
from app.urlcheck import validate_url

NASTY_NAME = "Canción ñ 😀 [abc].mp4"


def fake_info(url):
    return {"title": "T", "thumbnail": None, "duration": 12, "uploader": "U", "heights": [1080, 720]}


def ok_runner(job, on_progress):
    on_progress({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2, "speed": 1.0, "eta": 1})
    path = job.dir / NASTY_NAME
    path.write_bytes(b"data")
    return path


@pytest.fixture
def make_client(tmp_path):
    managers = []

    def _make(runner=ok_runner, **overrides):
        manager = JobManager(tmp_path / f"jobs{len(managers)}", runner)
        managers.append(manager)
        app = create_app(
            manager=manager,
            info_fetcher=overrides.get("info_fetcher", fake_info),
            url_validator=overrides.get("url_validator", lambda u: u),
            serve_web=False,
        )
        return TestClient(app)

    yield _make
    for manager in managers:
        manager.shutdown()


def wait_done(client, job_id, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_health(make_client):
    body = make_client().get("/api/health").json()
    assert body["ok"] is True
    assert body["ytdlp_version"]
    assert isinstance(body["ffmpeg"], bool)


def test_info_returns_summary(make_client):
    res = make_client().post("/api/info", json={"url": "https://example.com/v"})
    assert res.status_code == 200
    assert res.json()["heights"] == [1080, 720]


def test_info_failure_maps_to_400_with_code(make_client):
    def failing(url):
        raise DownloadFailure(ErrorCode.UNSUPPORTED_SITE)

    res = make_client(info_fetcher=failing).post("/api/info", json={"url": "https://example.com/v"})
    assert res.status_code == 400
    assert res.json()["error_code"] == "UNSUPPORTED_SITE"
    assert res.json()["error_message"]


@pytest.mark.parametrize("bad", ["youtube.com/watch?v=1", "", "ftp://x.com/a", "https://exa mple.com/"])
def test_malformed_urls_are_400_invalid_url_not_500(make_client, bad):
    client = make_client(url_validator=validate_url)
    for path, payload in (
        ("/api/info", {"url": bad}),
        ("/api/jobs", {"url": bad, "mode": "video"}),
    ):
        res = client.post(path, json=payload)
        assert res.status_code == 400
        assert res.json()["error_code"] == "INVALID_URL"


def test_private_host_is_blocked_at_the_api(make_client):
    import socket

    def to_loopback(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    client = make_client(url_validator=lambda u: validate_url(u, resolver=to_loopback))
    res = client.post("/api/jobs", json={"url": "https://innocent.example/v", "mode": "video"})
    assert res.status_code == 400
    assert res.json()["error_code"] == "INVALID_URL"


def test_job_lifecycle_and_file_download_with_unicode_name(make_client):
    client = make_client()
    res = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "video", "height": "720"})
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    status = wait_done(client, job_id)
    assert status["status"] == "done"
    assert status["filename"] == NASTY_NAME
    assert status["percent"] == 100.0

    file_res = client.get(f"/api/jobs/{job_id}/file")
    assert file_res.status_code == 200
    assert file_res.content == b"data"
    disposition = file_res.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert "Canci%C3%B3n" in disposition


def test_failed_job_reports_error_fields(make_client):
    def runner(job, on_progress):
        raise DownloadFailure(ErrorCode.GEO_BLOCKED)

    client = make_client(runner=runner)
    job_id = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "audio"}).json()["job_id"]
    status = wait_done(client, job_id)
    assert status["status"] == "error"
    assert status["error_code"] == "GEO_BLOCKED"
    assert client.get(f"/api/jobs/{job_id}/file").status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "https://example.com/v", "mode": "gif"},
        {"url": "https://example.com/v", "mode": "video", "height": "999"},
        {"url": "https://example.com/v", "mode": "audio", "audio_format": "wav"},
        {"mode": "video"},
    ],
)
def test_invalid_job_request_is_422(make_client, payload):
    assert make_client().post("/api/jobs", json=payload).status_code == 422


def test_unknown_and_traversal_shaped_ids_are_404(make_client):
    client = make_client()
    for job_id in ("nope", "..%2Fsecret", "%2E%2E", "a" * 500):
        assert client.get(f"/api/jobs/{job_id}").status_code == 404
        assert client.get(f"/api/jobs/{job_id}/file").status_code == 404


def test_file_before_done_is_409(make_client):
    release = threading.Event()

    def slow(job, on_progress):
        release.wait(3)
        return ok_runner(job, on_progress)

    client = make_client(runner=slow)
    job_id = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "video"}).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}/file").status_code == 409
    release.set()
    assert wait_done(client, job_id)["status"] == "done"
```

`services/downloader/tests/test_contract.py`:
```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.errors import DownloadFailure, ErrorCode
from app.jobs import JobManager
from app.main import contract, create_app

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "api.openapi.json"


def validate(instance, schema_name):
    doc = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": doc["components"]}
    Draft202012Validator(schema).validate(instance)


def test_committed_contract_matches_the_code():
    committed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert committed == contract(), "run: python scripts/gen_contract.py"


@pytest.fixture
def client(tmp_path):
    def runner(job, on_progress):
        if job.mode == "audio":
            raise DownloadFailure(ErrorCode.NETWORK)
        path = job.dir / "a.mp4"
        path.write_bytes(b"x")
        return path

    manager = JobManager(tmp_path / "jobs", runner)
    app = create_app(
        manager=manager,
        info_fetcher=lambda url: {"title": "T", "thumbnail": None, "duration": 1, "uploader": None, "heights": [720]},
        url_validator=lambda u: u,
        serve_web=False,
    )
    yield TestClient(app)
    manager.shutdown()


def wait_finished(client, job_id):
    import time

    for _ in range(300):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_responses_validate_against_committed_schemas(client):
    validate(client.get("/api/health").json(), "HealthResponse")
    validate(client.post("/api/info", json={"url": "https://example.com/v"}).json(), "InfoResponse")

    created = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "video"})
    validate(created.json(), "JobCreated")
    validate(wait_finished(client, created.json()["job_id"]), "JobStatus")

    failed = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "audio"})
    validate(wait_finished(client, failed.json()["job_id"]), "JobStatus")


def test_error_body_validates_against_committed_schema(tmp_path):
    def failing(url):
        raise DownloadFailure(ErrorCode.UNSUPPORTED_SITE)

    manager = JobManager(tmp_path / "jobs", lambda job, cb: job.dir)
    app = create_app(manager=manager, info_fetcher=failing, url_validator=lambda u: u, serve_web=False)
    res = TestClient(app).post("/api/info", json={"url": "https://example.com/v"})
    assert res.status_code == 400
    validate(res.json(), "ErrorBody")
    manager.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests\test_api.py services\downloader\tests\test_contract.py -q`
Expected: `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Write minimal implementation**

`services/downloader/app/main.py`:
```python
from __future__ import annotations

import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Literal

import yt_dlp.version
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.errors import DownloadFailure, ErrorCode
from app.extractor import fetch_info
from app.jobs import JobManager
from app.urlcheck import validate_url
from app.ytdlp_runner import run_download

SERVICE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parents[3] / "web"

HeightChoice = Literal["360", "480", "720", "1080", "1440", "2160", "best"]


class InfoRequest(BaseModel):
    url: str


class InfoResponse(BaseModel):
    title: str
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    heights: list[int]


class JobRequest(BaseModel):
    url: str
    mode: Literal["video", "audio"]
    height: HeightChoice = "best"
    audio_format: Literal["mp3", "m4a", "opus"] = "mp3"


class JobCreated(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    status: Literal["queued", "downloading", "processing", "done", "error"]
    percent: float
    speed: float | None = None
    eta: float | None = None
    filename: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    ytdlp_version: str
    ffmpeg: bool


class ErrorBody(BaseModel):
    error_code: ErrorCode
    error_message: str


def create_app(
    manager: JobManager | None = None,
    info_fetcher: Callable[[str], dict] = fetch_info,
    url_validator: Callable[[str], str] = validate_url,
    serve_web: bool = True,
) -> FastAPI:
    if manager is None:
        base = Path(tempfile.gettempdir()) / "videodownloader"
        shutil.rmtree(base, ignore_errors=True)
        manager = JobManager(base, run_download, log_path=SERVICE_DIR / "jobs.log")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.start_sweeper()
        yield
        manager.shutdown()

    app = FastAPI(title="VideoDownloader", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(DownloadFailure)
    async def _download_failure(_request, exc: DownloadFailure):
        return JSONResponse(
            status_code=400,
            content={"error_code": exc.code.value, "error_message": exc.message},
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health():
        return {
            "ok": True,
            "ytdlp_version": yt_dlp.version.__version__,
            "ffmpeg": shutil.which("ffmpeg") is not None,
        }

    @app.post("/api/info", response_model=InfoResponse, responses={400: {"model": ErrorBody}})
    def info(req: InfoRequest):
        return info_fetcher(url_validator(req.url))

    @app.post(
        "/api/jobs",
        response_model=JobCreated,
        status_code=202,
        responses={400: {"model": ErrorBody}},
    )
    def create_job(req: JobRequest):
        url = url_validator(req.url)
        job = manager.create(url, req.mode, req.height, req.audio_format)
        return {"job_id": job.id}

    @app.get(
        "/api/jobs/{job_id}",
        response_model=JobStatus,
        responses={404: {"description": "Unknown job"}},
    )
    def job_status(job_id: str):
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.snapshot()

    @app.get(
        "/api/jobs/{job_id}/file",
        responses={
            200: {"description": "The downloaded file", "content": {"application/octet-stream": {}}},
            404: {"description": "Unknown job"},
            409: {"description": "Job is not finished or failed"},
        },
    )
    def job_file(job_id: str):
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status != "done" or job.file_path is None or not job.file_path.is_file():
            raise HTTPException(status_code=409, detail="file not ready")
        return FileResponse(job.file_path, filename=job.filename)

    if serve_web and WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def contract() -> dict:
    """OpenAPI document that is committed to contracts/. Built from a throwaway app."""
    dummy = JobManager(Path(tempfile.mkdtemp(prefix="vd-contract-")), lambda job, cb: job.dir)
    try:
        return create_app(manager=dummy, serve_web=False).openapi()
    finally:
        shutil.rmtree(dummy.base_dir, ignore_errors=True)
```

`scripts/gen_contract.py`:
```python
"""Regenerate contracts/api.openapi.json from the FastAPI app."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "downloader"))

from app.main import contract  # noqa: E402

target = ROOT / "contracts" / "api.openapi.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(contract(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {target}")
```

- [ ] **Step 4: Generate the contract**

Run: `.\services\downloader\.venv\Scripts\python.exe scripts\gen_contract.py`
Expected: `wrote ...\contracts\api.openapi.json`.

- [ ] **Step 5: Run the whole gate suite and time it**

Run: `Measure-Command { .\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q | Out-Default }`
Expected: all pass, total under 2 s of test time (pytest's own summary line). Si algún test falla por el 404 de ids con `%2F`, mirar la respuesta real antes de tocar el test: el comportamiento exigido es 404.

- [ ] **Step 6: Commit**

```powershell
git add services scripts contracts
git commit -m "feat(downloader): HTTP API, OpenAPI contract and drift guard"
```

---

### Task 6: Interfaz web

**Files:**
- Create: `web/index.html`, `web/style.css`, `web/app.js`

**Interfaces:**
- Consumes: los 4 endpoints de Task 5 (`/api/info`, `/api/jobs`, `/api/jobs/{id}`, `/api/jobs/{id}/file`).
- Produces: ids estables que usa el e2e de Task 7: `#url-form`, `#url`, `#fetch`, `#error`, `#card`, `#title`, `#byline`, `#thumb`, `input[name=mode]`, `#height`, `#audio-format`, `#download`, `#progress`, `#bar`, `#status`.

Esta tarea se verifica en Task 7 (smoke e2e) y a mano en Task 9. No tiene test propio porque no hay lógica de negocio fuera del navegador.

- [ ] **Step 1: Write `web/index.html`**

```html
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VideoDownloader</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main>
    <h1>VideoDownloader</h1>
    <p class="sub">Pegá un enlace y descargá el video o solo el audio.</p>

    <form id="url-form" autocomplete="off">
      <input id="url" type="url" placeholder="https://..." required aria-label="URL del video">
      <button id="fetch" type="submit">Buscar</button>
    </form>

    <p id="error" role="alert" hidden></p>

    <section id="card" hidden>
      <img id="thumb" alt="" referrerpolicy="no-referrer" hidden>
      <div class="meta">
        <h2 id="title"></h2>
        <p id="byline"></p>
      </div>

      <div class="modes" role="radiogroup" aria-label="Tipo de descarga">
        <label><input type="radio" name="mode" value="video" checked> Video</label>
        <label><input type="radio" name="mode" value="audio"> Solo audio</label>
      </div>

      <label id="video-opt">Calidad
        <select id="height"></select>
      </label>
      <label id="audio-opt" hidden>Formato
        <select id="audio-format">
          <option value="mp3">MP3</option>
          <option value="m4a">M4A</option>
          <option value="opus">Opus</option>
        </select>
      </label>

      <button id="download" type="button">Descargar</button>

      <div id="progress" hidden>
        <progress id="bar" max="100" value="0"></progress>
        <span id="status"></span>
      </div>
    </section>
  </main>
  <noscript>Esta página necesita JavaScript.</noscript>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `web/style.css`**

```css
:root {
  --bg: #fafafa;
  --fg: #16181d;
  --muted: #5f6672;
  --card: #ffffff;
  --border: #d9dce1;
  --accent: #3b5bdb;
  --accent-fg: #ffffff;
  --danger: #c92a2a;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #101216;
    --fg: #eceef2;
    --muted: #9aa1ad;
    --card: #181b21;
    --border: #2b303a;
    --accent: #748ffc;
    --accent-fg: #101216;
    --danger: #ff8787;
  }
}

* { box-sizing: border-box; }
[hidden] { display: none !important; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}

main {
  max-width: 560px;
  margin: 0 auto;
  padding: 48px 16px;
}

h1 { margin: 0 0 4px; font-size: 1.75rem; }
h2 { margin: 0; font-size: 1.05rem; overflow-wrap: anywhere; }
.sub, #byline { margin: 0; color: var(--muted); }

#url-form { display: flex; gap: 8px; margin: 24px 0 12px; }

input[type="url"], select {
  min-width: 0;
  padding: 10px 12px;
  color: var(--fg);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  font: inherit;
}
input[type="url"] { flex: 1; }

button {
  padding: 10px 16px;
  color: var(--accent-fg);
  background: var(--accent);
  border: 0;
  border-radius: 8px;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
button:disabled { opacity: 0.5; cursor: progress; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

#error { margin: 0 0 12px; color: var(--danger); }

#card {
  display: grid;
  gap: 14px;
  padding: 16px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
}
#thumb { width: 100%; border-radius: 8px; }
.modes { display: flex; gap: 20px; }
#card label { display: flex; align-items: center; gap: 8px; }
#progress { display: grid; gap: 6px; }
#bar { width: 100%; }
#status { color: var(--muted); font-size: 0.9rem; overflow-wrap: anywhere; }
```

- [ ] **Step 3: Write `web/app.js`**

```js
"use strict";

const $ = (id) => document.getElementById(id);

function show(el, visible) {
  el.hidden = !visible;
}

function showError(message) {
  const el = $("error");
  el.textContent = message || "";
  show(el, Boolean(message));
}

async function api(path, options) {
  let res;
  try {
    res = await fetch(path, options);
  } catch {
    throw new Error("No se pudo conectar con el servidor local.");
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    // non-JSON body, handled below
  }
  if (!res.ok) {
    throw new Error((body && body.error_message) || "La solicitud no es válida.");
  }
  return body;
}

function postJson(path, data) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function formatDuration(seconds) {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond) return "";
  return ` · ${(bytesPerSecond / 1048576).toFixed(1)} MB/s`;
}

function setBusy(busy) {
  $("fetch").disabled = busy;
  $("download").disabled = busy;
}

function setProgress(percent, text) {
  $("bar").value = percent;
  $("status").textContent = text;
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function renderInfo(info) {
  $("title").textContent = info.title;
  $("byline").textContent = [info.uploader, formatDuration(info.duration)].filter(Boolean).join(" · ");

  const thumb = $("thumb");
  if (info.thumbnail) {
    thumb.src = info.thumbnail;
    show(thumb, true);
  } else {
    thumb.removeAttribute("src");
    show(thumb, false);
  }

  const select = $("height");
  select.replaceChildren();
  const best = document.createElement("option");
  best.value = "best";
  best.textContent = "Mejor calidad";
  select.append(best);
  for (const height of info.heights) {
    const option = document.createElement("option");
    option.value = String(height);
    option.textContent = `${height}p`;
    select.append(option);
  }

  show($("progress"), false);
  show($("card"), true);
}

function triggerDownload(jobId) {
  const link = document.createElement("a");
  link.href = `/api/jobs/${jobId}/file`;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

async function pollJob(jobId) {
  for (;;) {
    const job = await api(`/api/jobs/${jobId}`);
    if (job.status === "error") {
      throw new Error(job.error_message || "Falló la descarga.");
    }
    if (job.status === "done") {
      setProgress(100, `Listo: ${job.filename}`);
      triggerDownload(jobId);
      return;
    }
    if (job.status === "processing") {
      setProgress(100, "Procesando…");
    } else if (job.status === "downloading") {
      setProgress(job.percent, `Descargando ${Math.floor(job.percent)}%${formatSpeed(job.speed)}`);
    } else {
      setProgress(0, "En cola…");
    }
    await sleep(1000);
  }
}

$("url-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  show($("card"), false);
  setBusy(true);
  $("fetch").textContent = "Buscando…";
  try {
    renderInfo(await postJson("/api/info", { url: $("url").value.trim() }));
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
    $("fetch").textContent = "Buscar";
  }
});

for (const radio of document.querySelectorAll('input[name="mode"]')) {
  radio.addEventListener("change", () => {
    const audio = selectedMode() === "audio";
    show($("video-opt"), !audio);
    show($("audio-opt"), audio);
  });
}

$("download").addEventListener("click", async () => {
  showError("");
  setBusy(true);
  show($("progress"), true);
  setProgress(0, "En cola…");
  try {
    const { job_id: jobId } = await postJson("/api/jobs", {
      url: $("url").value.trim(),
      mode: selectedMode(),
      height: $("height").value || "best",
      audio_format: $("audio-format").value,
    });
    await pollJob(jobId);
  } catch (error) {
    showError(error.message);
    show($("progress"), false);
  } finally {
    setBusy(false);
  }
});
```

- [ ] **Step 4: Commit**

```powershell
git add web
git commit -m "feat(web): vanilla UI for pasting a URL and downloading video or audio"
```

---

### Task 7: Smoke e2e con Playwright

**Files:**
- Create: `services/downloader/tests/e2e/test_ui_smoke.py`

**Interfaces:**
- Consumes: `create_app`, `JobManager` (Tasks 3 y 5), los ids de Task 6.

- [ ] **Step 1: Install the browser**

Run: `.\services\downloader\.venv\Scripts\python.exe -m playwright install chromium`
Expected: Chromium se descarga sin errores.

- [ ] **Step 2: Write the e2e test**

`services/downloader/tests/e2e/test_ui_smoke.py`:
```python
import socket
import threading
import time

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
    assert "Listo" in page.inner_text("#status")


def test_unsupported_site_error_is_shown(server, page):
    page.goto(server)
    page.fill("#url", "https://bad.example/v")
    page.click("#fetch")
    page.wait_for_selector("#error:not([hidden])")
    assert "no está soportado" in page.inner_text("#error")
    assert not page.is_visible("#card")
```

- [ ] **Step 3: Run the e2e lane**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests\e2e -m e2e -q`
Expected: 3 passed. Si falla un selector, corregir `web/` o el test según el comportamiento real, no a ciegas.

- [ ] **Step 4: Confirm the gate lane still skips it**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q`
Expected: los 3 e2e aparecen como `deselected`, el resto pasa.

- [ ] **Step 5: Commit**

```powershell
git add services
git commit -m "test(web): Playwright smoke for the download flow and error display"
```

---

### Task 8: Eval con sitios reales

**Files:**
- Create: `services/downloader/evals/test_real_sites.py`, `services/downloader/evals/URL_VERIFICATION.md`

**Interfaces:**
- Consumes: `fetch_info` (Task 4), `run_download` (Task 4), `Job` (Task 3).

- [ ] **Step 1: Verify the candidate URLs before relying on them**

Para cada URL candidata (YouTube `https://www.youtube.com/watch?v=jNQXAC9IdpU`, Vimeo `https://vimeo.com/56015672`, SoundCloud `https://soundcloud.com/ethmusic/lostin-powers-she-so-heavy`, archive.org `https://archive.org/details/Popeye_forPresident`, Dailymotion `http://www.dailymotion.com/video/x5kesuj`):

Run: `.\services\downloader\.venv\Scripts\python.exe -m yt_dlp --simulate --no-playlist --print "%(title)s | %(duration)s" <URL>`
Expected: una línea con título y duración. Si una URL falla, buscar otra del mismo sitio que sea pública y estable, probarla igual y usarla en lugar de la caída. Registrar el resultado de cada una (fecha, comando, salida resumida) en `services/downloader/evals/URL_VERIFICATION.md`.

- [ ] **Step 2: Write the eval**

`services/downloader/evals/test_real_sites.py` (reemplazar las URLs por las que quedaron verificadas en el paso 1):
```python
import json
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from app.extractor import fetch_info
from app.jobs import Job
from app.ytdlp_runner import run_download

pytestmark = pytest.mark.eval

THRESHOLD = 0.8
RESULTS_DIR = Path(__file__).resolve().parent / "results"

YOUTUBE = "https://www.youtube.com/watch?v=jNQXAC9IdpU"
VIMEO = "https://vimeo.com/56015672"
SOUNDCLOUD = "https://soundcloud.com/ethmusic/lostin-powers-she-so-heavy"
ARCHIVE = "https://archive.org/details/Popeye_forPresident"
DAILYMOTION = "http://www.dailymotion.com/video/x5kesuj"

# (site, url, mode, audio_format)
CASES = [
    ("youtube", YOUTUBE, "video", "mp3"),
    ("youtube", YOUTUBE, "audio", "mp3"),
    ("youtube", YOUTUBE, "audio", "m4a"),
    ("youtube", YOUTUBE, "audio", "opus"),
    ("vimeo", VIMEO, "video", "mp3"),
    ("vimeo", VIMEO, "audio", "mp3"),
    ("soundcloud", SOUNDCLOUD, "audio", "mp3"),
    ("archive", ARCHIVE, "video", "mp3"),
    ("archive", ARCHIVE, "audio", "mp3"),
    ("dailymotion", DAILYMOTION, "video", "mp3"),
    ("dailymotion", DAILYMOTION, "audio", "mp3"),
]

AUDIO_CODEC = {"mp3": "mp3", "m4a": "aac", "opus": "opus"}


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def verify(path: Path, mode: str, audio_format: str, expected_duration) -> str | None:
    """Return None when the file is valid, otherwise the reason it is not."""
    data = probe(path)
    kinds = {s["codec_type"] for s in data["streams"]}
    duration = float(data["format"]["duration"])
    if expected_duration and abs(duration - expected_duration) > max(2.0, 0.05 * expected_duration):
        return f"duration {duration:.1f}s vs expected {expected_duration}s"
    if mode == "video":
        return None if {"video", "audio"} <= kinds else f"streams {sorted(kinds)}"
    if kinds != {"audio"}:
        return f"streams {sorted(kinds)}"
    codec = next(s["codec_name"] for s in data["streams"] if s["codec_type"] == "audio")
    return None if codec == AUDIO_CODEC[audio_format] else f"codec {codec}"


def run_case(site, url, mode, audio_format) -> dict:
    started = time.time()
    try:
        info = fetch_info(url)
        with tempfile.TemporaryDirectory(prefix="vd-eval-") as tmp:
            job = Job(
                id="eval",
                url=url,
                mode=mode,
                height="360" if mode == "video" else "best",
                audio_format=audio_format,
                dir=Path(tmp),
            )
            path = run_download(job, lambda data: None)
            reason = verify(path, mode, audio_format, info.get("duration"))
    except Exception as error:  # noqa: BLE001 - any failure is a failed case
        reason = f"{type(error).__name__}: {error}"
    return {
        "site": site,
        "mode": mode,
        "audio_format": audio_format,
        "ok": reason is None,
        "reason": reason,
        "seconds": round(time.time() - started, 1),
    }


def test_download_success_rate_meets_threshold():
    results = [run_case(*case) for case in CASES]
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "last_run.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['site']:12} {r['mode']:6} {r['audio_format']:5} {r['seconds']:6}s  {r['reason'] or ''}")
    rate = sum(r["ok"] for r in results) / len(results)
    print(f"success rate: {rate:.0%} (threshold {THRESHOLD:.0%})")
    assert rate >= THRESHOLD
```

- [ ] **Step 3: Run the eval**

Run: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\evals -m eval -s -q`
Expected: tabla PASS/FAIL por caso y `success rate` mayor o igual a 80%. Si queda por debajo, diagnosticar cada FAIL por su motivo (no bajar el umbral): una URL caída se reemplaza (paso 1), un bug real se corrige con su test en el gate.

- [ ] **Step 4: Commit**

```powershell
git add services
git commit -m "test(downloader): real-site eval with ffprobe verification and 80% threshold"
```

---

### Task 9: Scripts, documentación y verificación final

**Files:**
- Create: `scripts/run.ps1`, `scripts/update-ytdlp.ps1`, `README.md`, `services/downloader/README.md`

- [ ] **Step 1: Write the scripts**

`scripts/run.ps1`:
```powershell
param([int]$Port = 8000)

$root = Split-Path -Parent $PSScriptRoot
$service = Join-Path $root "services\downloader"
$python = Join-Path $service ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Falta el entorno virtual. Ejecutá: python -m venv services\downloader\.venv; services\downloader\.venv\Scripts\python.exe -m pip install -r services\downloader\requirements.txt"
    exit 1
}

Set-Location $service
Write-Host "VideoDownloader en http://127.0.0.1:$Port"
& $python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port
```

`scripts/update-ytdlp.ps1`:
```powershell
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "services\downloader\.venv\Scripts\python.exe"

& $python -m pip install -U yt-dlp
& $python -c "import yt_dlp.version as v; print('yt-dlp', v.__version__)"
Write-Host "Reiniciá la app para usar la nueva versión."
```

- [ ] **Step 2: Write the docs**

`README.md` (raíz): qué es, instalación (venv + `pip install -r services/downloader/requirements.txt`), arranque (`.\scripts\run.ps1`, abrir `http://127.0.0.1:8000`), actualizar yt-dlp (`.\scripts\update-ytdlp.ps1`), estructura de carpetas, aviso: descargá solo contenido sobre el que tengas derecho a hacerlo y respetá los términos de cada sitio.

`services/downloader/README.md`: endpoints (apuntar a `contracts/api.openapi.json`), cómo regenerar el contrato (`python scripts/gen_contract.py`), los tres carriles de tests con su comando exacto (gate, e2e, eval, tal como están en los Tasks 5, 7 y 8), formato de `jobs.log`, y las limitaciones conocidas:
- La validación SSRF resuelve el host una vez; yt-dlp vuelve a resolverlo, así que un DNS rebinding o una redirección a una red privada no están cubiertos. El servidor solo escucha en `127.0.0.1`, por lo que el riesgo es bajo para uso personal.
- Sin login ni cookies: videos privados fallan con `LOGIN_REQUIRED`.
- yt-dlp se rompe cuando un sitio cambia: actualizarlo con `update-ytdlp.ps1`.

Cada comando y ruta escritos en los README se ejecutan en el paso 3.

- [ ] **Step 3: Verify every command in the docs and the real thing end to end**

1. Gate completo: `.\services\downloader\.venv\Scripts\python.exe -m pytest services\downloader\tests -q`. Expected: todo en verde.
2. Contrato sin deriva: `.\services\downloader\.venv\Scripts\python.exe scripts\gen_contract.py` y `git status --short contracts` no muestra cambios.
3. Arrancar el servidor en segundo plano (`.\scripts\run.ps1 -Port 8765`, `run_in_background`) y comprobar:
   - `Invoke-RestMethod http://127.0.0.1:8765/api/health` devuelve `ok=True`, la versión de yt-dlp y `ffmpeg=True`.
   - `Invoke-WebRequest http://127.0.0.1:8765/ -UseBasicParsing` devuelve 200 y contiene `VideoDownloader`.
   - `POST /api/info` con la URL de YouTube verificada en Task 8 devuelve título y alturas.
   - `POST /api/jobs` en modo `audio` (mp3), consultar `/api/jobs/{id}` hasta `done`, bajar `/file` a un archivo temporal y validarlo con `ffprobe` (stream de audio, codec mp3).
   - Mismo flujo en modo `video` con `height: "360"`, con `ffprobe` mostrando stream de video y de audio.
   - `POST /api/info` con `http://127.0.0.1:8765/` devuelve 400 `INVALID_URL`.
4. Revisar `services\downloader\jobs.log`: una línea por job, con host y sin URL completa.
5. Parar el servidor.
6. e2e y eval otra vez: los comandos de Task 7 paso 3 y Task 8 paso 3.
7. Abrir la UI en un navegador real contra el servidor y descargar un audio a mano (el único paso que no se puede automatizar; si no hay navegador disponible, decirlo en el reporte como no verificado).

- [ ] **Step 4: Self-rating and final report**

Antes del commit final: puntuar el trabajo de 1 a 10 con una brecha nombrada por cada punto que falte (según CLAUDE.md), lanzar la revisión crítica de rama (`/code-review`) y corregir lo que reporte. El reporte final lista qué tests, evals y agentes se corrieron, el estado (DONE / DONE_WITH_CONCERNS), y qué reiniciar (solo `scripts\run.ps1`).

- [ ] **Step 5: Commit**

```powershell
git add scripts README.md services
git commit -m "docs: run scripts, READMEs and end-to-end verification"
```

Rebase y push: el repo no tiene remoto ni `gh`. Si el usuario configura uno (`git remote add origin <url>`), aplicar el ritual de CLAUDE.md (rebase sobre `main`, `git push -u origin HEAD`, `gh pr create`). Sin remoto, avisar y dejar la rama lista para fusionar en local.

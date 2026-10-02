from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlsplit

import yt_dlp.version
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.config import Settings, load_settings
from app.egress_proxy import EgressProxy
from app.errors import HTTP_STATUS, DownloadFailure, ErrorCode
from app.extractor import fetch_info
from app.hardening import limit_process_memory, route_environment_through
from app.jobs import ALIVE_FILE, JobManager
from app.runtimes import detect_js_runtime, js_runtimes_option
from app.urlcheck import validate_url
from app.ytdlp_runner import run_download

SERVICE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parents[3] / "web"

log = logging.getLogger("videodownloader")

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
    status: Literal["queued", "downloading", "processing", "done", "error", "cancelled"]
    percent: float
    speed: float | None = None
    eta: float | None = None
    filename: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    version: str
    ytdlp_version: str
    ffmpeg: bool
    ffprobe: bool
    js_runtime: Literal["deno", "node"] | None = None
    max_filesize_mb: int
    max_duration_min: int
    max_concurrent: int
    max_queue: int


class ErrorBody(BaseModel):
    error_code: ErrorCode
    error_message: str


DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _hostname_of_host_header(value: str) -> str:
    """'LocalHost:8000' -> 'localhost', '[::1]:8000' -> '[::1]'."""
    value = value.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    return value.split(":", 1)[0]


def _hostname_of_origin(origin: str) -> str:
    """'http://127.0.0.1:8765' -> '127.0.0.1'. Unparseable or 'null' -> '' (never allowed)."""
    try:
        hostname = urlsplit(origin).hostname or ""
    except ValueError:
        return ""
    return f"[{hostname}]" if ":" in hostname else hostname


def _port_of_host_header(value: str) -> int | None:
    """'LocalHost:8000' -> 8000, '127.0.0.1' -> 80 (no port means the http default), garbage -> None."""
    value = value.strip().lower()
    rest = value[value.find("]") + 1 :] if value.startswith("[") else value.partition(":")[1] + value.partition(":")[2]
    if rest == "":
        return 80
    if not rest.startswith(":") or not rest[1:].isdigit():
        return None
    return int(rest[1:])


def _port_of_origin(origin: str) -> int | None:
    try:
        parts = urlsplit(origin)
        return parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None


TEMP_PREFIX = "sifon-"
# /api/info only reads web pages and manifests, never media: a page bigger than this is not a page.
INFO_RESPONSE_CAP = 32 * 1024 * 1024
STALE_AFTER_SECONDS = 10 * 60  # a running instance refreshes its heartbeat every minute


_OWN_DIR = re.compile(rf"^{re.escape(TEMP_PREFIX)}\d+$")


def _sweep_stale_temp_dirs(root: Path, keep: Path, now: float | None = None) -> None:
    """Remove the temp dirs of runs that died without cleaning up (heartbeat stale).

    Only folders named `sifon-<number>` that contain our heartbeat file are ever touched, so
    a folder of the user's that merely starts with "sifon-" is left alone.
    """
    cutoff = (time.time() if now is None else now) - STALE_AFTER_SECONDS
    for entry in root.glob(f"{TEMP_PREFIX}*"):
        try:
            if entry == keep or not _OWN_DIR.match(entry.name) or not entry.is_dir():
                continue
            beat = entry / ALIVE_FILE
            if beat.is_file() and beat.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def create_app(
    manager: JobManager | None = None,
    info_fetcher: Callable[[str], dict] | None = None,
    url_validator: Callable[[str], str] = validate_url,
    serve_web: bool = True,
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS,
    settings: Settings | None = None,
    egress: EgressProxy | None = None,
    route_environment: bool = False,
) -> FastAPI:
    settings = settings or load_settings()
    # Every yt-dlp request goes through this proxy; it enforces the private-network block.
    # An app built with injected fakes (tests) never touches the network, so it starts none.
    own_egress = egress is None and (manager is None or info_fetcher is None)
    if own_egress:
        egress = EgressProxy(max_response_bytes=settings.max_filesize_bytes)
    # A second proxy with a small byte cap serves /api/info.
    info_egress = EgressProxy(max_response_bytes=INFO_RESPONSE_CAP) if own_egress else None
    proxy_url = (lambda: egress.url) if egress is not None else (lambda: None)
    info_proxy_url = (lambda: info_egress.url) if info_egress is not None else proxy_url

    if manager is None:
        root = Path(tempfile.gettempdir())
        base = root / f"{TEMP_PREFIX}{os.getpid()}"
        shutil.rmtree(base, ignore_errors=True)
        _sweep_stale_temp_dirs(root, keep=base)

        def runner(job, on_progress):
            return run_download(
                job, on_progress, proxy=proxy_url(), max_duration_s=settings.max_duration_min * 60
            )

        manager = JobManager(
            base,
            runner,
            max_workers=settings.max_concurrent,
            ttl_seconds=settings.ttl_minutes * 60,
            log_path=SERVICE_DIR / "jobs.log",
            max_queue=settings.max_queue,
            max_filesize_bytes=settings.max_filesize_bytes,
            min_free_disk_bytes=settings.min_free_disk_bytes,
        )
    if info_fetcher is None:
        def info_fetcher(url: str) -> dict:
            return fetch_info(url, proxy=info_proxy_url(), js_runtimes=js_runtimes_option())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        restore_environment = None
        if own_egress:
            egress.start()
            info_egress.start()
            if route_environment:
                # ffmpeg and a few handlers read proxy variables: make sure they only see ours.
                restore_environment = route_environment_through(egress.url)
        manager.start_sweeper()
        yield
        manager.shutdown()
        if own_egress:
            egress.stop()
            info_egress.stop()
        if restore_environment:
            restore_environment()

    app = FastAPI(title="VideoDownloader", version=__version__, lifespan=lifespan)
    app.state.egress = egress
    app.state.info_egress = info_egress

    allowed = frozenset(host.lower() for host in allowed_hosts)

    @app.middleware("http")
    async def _host_and_origin_check(request: Request, call_next):
        # Blocks DNS-rebinding pages (foreign Host) and cross-origin POSTs (foreign Origin).
        host_value = request.headers.get("host", "")
        if _hostname_of_host_header(host_value) not in allowed or _port_of_host_header(host_value) is None:
            return JSONResponse(status_code=403, content={"detail": "host not allowed"})
        origin = request.headers.get("origin")
        if origin is not None and request.method not in SAFE_METHODS:
            # Same site as the page that is calling: a local host AND the same port. Another
            # web app on localhost:<other port> is a different origin and is not trusted.
            host_header = request.headers.get("host", "")
            same_origin = (
                _hostname_of_origin(origin) == _hostname_of_host_header(host_header)
                and _port_of_origin(origin) == _port_of_host_header(host_header)
                and _port_of_origin(origin) is not None
            )
            if _hostname_of_origin(origin) not in allowed or not same_origin:
                return JSONResponse(status_code=403, content={"detail": "origin not allowed"})
        return await call_next(request)

    @app.exception_handler(DownloadFailure)
    async def _download_failure(_request, exc: DownloadFailure):
        return JSONResponse(
            status_code=HTTP_STATUS.get(exc.code, 400),
            content={"error_code": exc.code.value, "error_message": exc.message},
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health():
        return {
            "ok": True,
            "version": __version__,
            "ytdlp_version": yt_dlp.version.__version__,
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": shutil.which("ffprobe") is not None,
            "js_runtime": detect_js_runtime(),
            "max_filesize_mb": settings.max_filesize_mb,
            "max_duration_min": settings.max_duration_min,
            "max_concurrent": settings.max_concurrent,
            "max_queue": settings.max_queue,
        }

    @app.post("/api/info", response_model=InfoResponse, responses={400: {"model": ErrorBody}})
    def info(req: InfoRequest):
        url = url_validator(req.url)
        try:
            return info_fetcher(url)
        except DownloadFailure:
            raise
        except Exception as exc:
            # Never log the URL: only the exception type, no message, no traceback.
            log.error("unexpected error fetching info (%s)", type(exc).__name__)
            raise DownloadFailure(ErrorCode.UNKNOWN) from exc

    @app.post(
        "/api/jobs",
        response_model=JobCreated,
        status_code=202,
        responses={
            400: {"model": ErrorBody},
            429: {"model": ErrorBody, "description": "Too many jobs running or queued"},
            507: {"model": ErrorBody, "description": "Not enough free disk space"},
        },
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

    @app.delete(
        "/api/jobs/{job_id}",
        response_model=JobStatus,
        responses={404: {"description": "Unknown job"}},
    )
    def cancel_job(job_id: str):
        """Cancel a queued or running job. A finished job is discarded together with its file."""
        job = manager.cancel(job_id)
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


def server_app() -> FastAPI:
    """Entry point of the real server (`uvicorn app.main:server_app --factory`, used by run.cmd).

    create_app stays free of process-wide side effects so tests can build many apps; this one
    adds the memory cap and routes child processes through the egress proxy.
    """
    settings = load_settings()
    if not limit_process_memory(settings.max_memory_bytes):
        log.warning("running without a memory cap")
    return create_app(settings=settings, route_environment=True)


def contract() -> dict:
    """OpenAPI document that is committed to contracts/. Built from a throwaway app."""
    dummy = JobManager(Path(tempfile.mkdtemp(prefix="vd-contract-")), lambda job, cb: job.dir)
    try:
        return create_app(manager=dummy, serve_web=False).openapi()
    finally:
        shutil.rmtree(dummy.base_dir, ignore_errors=True)

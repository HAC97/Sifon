from __future__ import annotations

import logging
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

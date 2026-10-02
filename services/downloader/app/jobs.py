from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
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
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    future: Future | None = field(default=None, repr=False)

    @property
    def active(self) -> bool:
        return self.status in ("queued", "downloading", "processing")

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
        max_workers: int = 2,
        ttl_seconds: float = 1800,
        clock: Callable[[], float] = time.time,
        log_path: Path | None = None,
        max_queue: int = 10,
        max_filesize_bytes: int | None = None,
        min_free_disk_bytes: int = 0,
        disk_usage: Callable[[Path], object] = shutil.disk_usage,
    ):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._runner = runner
        self._ttl = ttl_seconds
        self._clock = clock
        self._log_path = Path(log_path) if log_path else None
        self._max_queue = max_queue
        self._max_filesize = max_filesize_bytes
        self._min_free = min_free_disk_bytes
        self._disk_usage = disk_usage
        self._last_disk_check = 0.0
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._stop = threading.Event()
        self._sweeper: threading.Thread | None = None

    @property
    def base_dir(self) -> Path:
        return self._base

    def _free_bytes(self) -> int:
        return self._disk_usage(self._base).free

    def create(self, url: str, mode: str, height: str = "best", audio_format: str = "mp3") -> Job:
        if self._min_free and self._free_bytes() < self._min_free:
            raise DownloadFailure(ErrorCode.DISK_FULL)
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
        with self._lock:
            # Checked and inserted under one lock, so concurrent requests cannot overshoot the cap.
            if sum(1 for other in self._jobs.values() if other.active) >= self._max_queue:
                raise DownloadFailure(ErrorCode.QUEUE_FULL)
            job.dir.mkdir(parents=True)
            self._jobs[job_id] = job
        job.future = self._pool.submit(self._run, job)
        return job

    def cancel(self, job_id: str) -> Job | None:
        """Stop an active job, or discard a finished one with its file. None if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            active = job.active
            if not active:
                del self._jobs[job_id]
        if not active:
            shutil.rmtree(job.dir, ignore_errors=True)
            return job
        job.cancel_event.set()
        # Still waiting in the pool: it never starts, so finish it here.
        if job.future is not None and job.future.cancel():
            self._finish(job, "cancelled", ErrorCode.CANCELLED, USER_MESSAGES[ErrorCode.CANCELLED])
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
        if job.cancel_event.is_set():
            self._finish(job, "cancelled", ErrorCode.CANCELLED, USER_MESSAGES[ErrorCode.CANCELLED])
            return
        job.started_at = self._clock()
        job.status = "downloading"
        try:
            path = Path(self._runner(job, lambda d: self._on_progress(job, d)))
        except DownloadFailure as failure:
            if failure.code is ErrorCode.CANCELLED:
                self._finish(job, "cancelled", failure.code, failure.message)
            else:
                self._finish(job, "error", failure.code, failure.message)
        except Exception as exc:
            # Type name only: the message and traceback of yt-dlp errors embed the full URL.
            log.error("job %s crashed (%s)", job.id, type(exc).__name__)
            self._finish(job, "error", ErrorCode.UNKNOWN, USER_MESSAGES[ErrorCode.UNKNOWN])
        else:
            if job.cancel_event.is_set():  # cancelled while ffmpeg was post-processing
                self._finish(job, "cancelled", ErrorCode.CANCELLED, USER_MESSAGES[ErrorCode.CANCELLED])
            else:
                self._finish(job, "done", path=path)

    def _check_limits(self, job: Job, data: dict) -> None:
        """Raise from inside yt-dlp's progress hook to abort the download."""
        if job.cancel_event.is_set():
            raise DownloadFailure(ErrorCode.CANCELLED)
        if self._max_filesize:
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            if max(total, data.get("downloaded_bytes") or 0) > self._max_filesize:
                raise DownloadFailure(ErrorCode.TOO_LARGE)
        if self._min_free:
            now = time.monotonic()
            if now - self._last_disk_check >= 2.0:
                self._last_disk_check = now
                if self._free_bytes() < self._min_free:
                    raise DownloadFailure(ErrorCode.DISK_FULL)

    def _on_progress(self, job: Job, data: dict) -> None:
        status = data.get("status")
        if status == "downloading":
            self._check_limits(job, data)
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
        if status != "done":
            # Nothing is left to download, so a failed or cancelled job frees its partial files now.
            shutil.rmtree(job.dir, ignore_errors=True)
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

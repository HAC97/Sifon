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

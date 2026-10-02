"""Runtime limits, read once from SIFON_* environment variables.

Every value has a safe default for a personal machine. A bad value (not a number, zero or
negative) is a startup error with the variable name in the message, never a silent fallback.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

__all__ = ["Settings", "SettingsError", "load_settings"]


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    max_concurrent: int = 2          # downloads running at the same time
    max_queue: int = 10              # jobs waiting + running; the next one is rejected (QUEUE_FULL)
    max_filesize_mb: int = 2048      # per downloaded file (video and audio streams count separately)
    max_duration_min: int = 180      # longer videos (and live streams) are rejected
    min_free_disk_mb: int = 1024     # a job is refused, or stopped, below this much free space
    ttl_minutes: int = 30            # finished files are deleted this long after they finish

    @property
    def max_filesize_bytes(self) -> int:
        return self.max_filesize_mb * 1024 * 1024

    @property
    def min_free_disk_bytes(self) -> int:
        return self.min_free_disk_mb * 1024 * 1024


_VARIABLES = {
    "SIFON_MAX_CONCURRENT": "max_concurrent",
    "SIFON_MAX_QUEUE": "max_queue",
    "SIFON_MAX_FILESIZE_MB": "max_filesize_mb",
    "SIFON_MAX_DURATION_MIN": "max_duration_min",
    "SIFON_MIN_FREE_DISK_MB": "min_free_disk_mb",
    "SIFON_TTL_MINUTES": "ttl_minutes",
}


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    values: dict[str, int] = {}
    for variable, field in _VARIABLES.items():
        raw = env.get(variable)
        if raw is None or raw.strip() == "":
            continue
        try:
            number = int(raw.strip())
        except ValueError:
            raise SettingsError(f"{variable} debe ser un entero, no {raw!r}.") from None
        if number < 1:
            raise SettingsError(f"{variable} debe ser 1 o mayor, no {number}.")
        values[field] = number
    settings = Settings(**values)
    if settings.max_queue < settings.max_concurrent:
        raise SettingsError("SIFON_MAX_QUEUE no puede ser menor que SIFON_MAX_CONCURRENT.")
    return settings

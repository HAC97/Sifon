"""Process-level protections for the real server. Tests and tools never call these implicitly.

- `limit_process_memory`: a hostile page that streams forever is buffered in memory by yt-dlp's
  extractors, before any download limit applies. A Windows Job Object memory limit turns that
  into a MemoryError in the job thread instead of a frozen computer.
- `route_environment_through`: ffmpeg (a child process) and some yt-dlp handlers read proxy
  settings from the environment. A `NO_PROXY` or `ALL_PROXY` set by the user would let them skip
  the egress proxy, so for the life of the server every child sees only our proxy.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from typing import Callable, MutableMapping

log = logging.getLogger("videodownloader")

_REMOVED = ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy")
_SET = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")

JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


def route_environment_through(proxy_url: str, env: MutableMapping[str, str] | None = None) -> Callable[[], None]:
    """Point every proxy variable at `proxy_url`, drop the bypass ones. Returns the undo function."""
    env = os.environ if env is None else env
    saved = {key: env.get(key) for key in (*_REMOVED, *_SET)}
    for key in _REMOVED:
        env.pop(key, None)
    for key in _SET:
        env[key] = proxy_url

    def restore() -> None:
        for key, value in saved.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value

    return restore


def limit_process_memory(limit_bytes: int) -> bool:
    """Cap the memory of this process (and the children it starts later). Windows only.

    Returns True if the limit is active. On failure it logs a warning and returns False: the
    server still works, just without this protection.
    """
    if sys.platform != "win32":
        log.warning("memory limit not applied: only implemented for Windows")
        return False

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMITS),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        log.warning("memory limit not applied: CreateJobObject failed (%s)", ctypes.get_last_error())
        return False
    info = EXTENDED_LIMITS()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = limit_bytes
    if not kernel32.SetInformationJobObject(
        job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info), ctypes.sizeof(info)
    ):
        log.warning("memory limit not applied: SetInformationJobObject failed (%s)", ctypes.get_last_error())
        return False
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        log.warning("memory limit not applied: AssignProcessToJobObject failed (%s)", ctypes.get_last_error())
        return False
    return True

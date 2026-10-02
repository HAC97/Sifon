"""Desktop entry point: what a double-click on sifon.exe does.

Picks a free port, starts the server in a thread, opens the browser, shows a small control
window (or runs headless with --no-window), checks for a newer yt-dlp in the background, and
shuts everything down in order. A second launch finds the running one and just opens the
browser. The logic lives here, without any GUI, so it can be tested; app/desktop_ui.py is the
thin tkinter shell on top.
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

from app import __version__, paths
from app.ytdlp_update import UpdateResult, auto_update_enabled, install_update, update_if_due, write_prefs

log = logging.getLogger("videodownloader")

DEFAULT_PORT = 8000
PORT_SPAN = 20
INSTANCE_FILE = "instance.json"
STOP_FILE = "stop.request"  # headless mode: creating this file in the data folder asks for a clean exit
READY_TIMEOUT = 30.0


# --- port and single instance -------------------------------------------------------------------


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def choose_port(preferred: int = DEFAULT_PORT, span: int = PORT_SPAN, is_free: Callable[[int], bool] = port_is_free) -> int:
    """`preferred` if free, else the next free one in the span, else any free port the OS gives."""
    for port in range(preferred, preferred + span):
        if is_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# The server routes this whole process's proxy variables through its egress proxy (which refuses
# 127.0.0.1 on purpose), so talking to ourselves must never use any proxy.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_health(port: int, timeout: float = 2.0) -> dict | None:
    try:
        with _DIRECT.open(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            body = json.loads(response.read())
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) and body.get("ok") and "ytdlp_version" in body else None


def instance_path(data_dir: Path) -> Path:
    return data_dir / INSTANCE_FILE


def write_instance(data_dir: Path, port: int) -> None:
    instance_path(data_dir).write_text(json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8")


def clear_instance(data_dir: Path) -> None:
    try:
        instance_path(data_dir).unlink()
    except OSError:
        pass


def find_running(data_dir: Path, health: Callable[[int], dict | None] = fetch_health) -> int | None:
    """Port of a sifon that is already running for this user, or None. A stale file is ignored."""
    try:
        port = int(json.loads(instance_path(data_dir).read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return port if health(port) else None


# --- the server in a thread ---------------------------------------------------------------------


class ServerThread:
    """Runs uvicorn in a background thread so the main thread can own the window."""

    def __init__(self, app_factory: Callable, port: int):
        import uvicorn

        self.port = port
        self._factory = app_factory
        self._config_kwargs = dict(host="127.0.0.1", port=port, log_config=None, access_log=False)
        self._uvicorn = uvicorn
        self.server = None
        self.app = None
        self._thread: threading.Thread | None = None
        self.error: BaseException | None = None

    def start(self) -> None:
        self.app = self._factory()
        self.server = self._uvicorn.Server(self._uvicorn.Config(self.app, **self._config_kwargs))
        self._thread = threading.Thread(target=self._run, name="server", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.server.run()
        except BaseException as exc:  # noqa: BLE001 - reported through wait_ready
            self.error = exc
            log.exception("server stopped with an error")

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.error is not None or (self._thread is not None and not self._thread.is_alive()):
                return False
            if self.server.started and fetch_health(self.port):
                return True
            time.sleep(0.1)
        return False

    @property
    def manager(self):
        return getattr(self.app.state, "manager", None) if self.app else None

    def active_jobs(self) -> int:
        manager = self.manager
        return manager.active_count() if manager is not None else 0

    def stop(self, timeout: float = 15.0) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout)


# --- the application object (window-independent) -----------------------------------------------


class Desktop:
    def __init__(self, data_dir: Path, port: int, server: ServerThread, installed_ytdlp: str):
        self.data_dir = data_dir
        self.port = port
        self.server = server
        self.installed_ytdlp = installed_ytdlp
        self.update: UpdateResult | None = None
        self.checking = False
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def open_browser(self) -> None:
        webbrowser.open(self.url)

    def check_for_update(self, force: bool = False, fetch=None, **kwargs) -> UpdateResult:
        """Look for a newer yt-dlp. Never raises. `force` ignores the once-a-day rule."""
        with self._lock:
            if self.checking:
                return UpdateResult("skipped", "ya se está buscando una actualización")
            self.checking = True
        try:
            extra = {"fetch": fetch} if fetch is not None else {}
            if force:
                result = install_update(self.data_dir, self.installed_ytdlp, **extra, **kwargs)
                if result.status != "failed":
                    write_prefs(self.data_dir, last_check=time.time())
            else:
                result = update_if_due(self.data_dir, self.installed_ytdlp, **extra, **kwargs)
            if result.status != "skipped":
                self.update = result
            return result
        finally:
            self.checking = False

    def check_in_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.check_for_update, name="ytdlp-update", daemon=True)
        thread.start()
        return thread

    @property
    def restart_needed(self) -> bool:
        return self.update is not None and self.update.status == "updated"

    def set_auto_update(self, enabled: bool) -> None:
        write_prefs(self.data_dir, auto=bool(enabled))

    def shutdown(self) -> None:
        self.server.stop()
        clear_instance(self.data_dir)

    def restart(self, argv: list[str] | None = None) -> None:
        """Stop the server, then start a fresh copy of this program (used to apply an update)."""
        self.shutdown()
        command = [sys.executable] if paths.is_frozen() else [sys.executable, "-m", "app.desktop"]
        subprocess.Popen(command + (argv or ["--no-browser"]), close_fds=True)  # noqa: S603


# --- logging ------------------------------------------------------------------------------------


def setup_logging(data_dir: Path) -> Path:
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    target = logs / "sifon.log"
    handler = logging.handlers.RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [h for h in root.handlers if not isinstance(h, logging.handlers.RotatingFileHandler)] + [handler]
    return target


# --- main ---------------------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sifon", description="sifón: descargador local de video y audio")
    parser.add_argument("--no-window", action="store_true", help="sin ventana de control (se cierra con Ctrl+C)")
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    parser.add_argument("--port", type=int, default=0, help="puerto fijo (por defecto el primero libre desde 8000)")
    return parser.parse_args(argv)


def _stop_on_break_signal() -> None:
    """Closing a console window or Ctrl+Break must shut down in order, not kill the process.

    Python turns Ctrl+C into KeyboardInterrupt but leaves SIGBREAK (what Windows sends when the
    console window is closed) at its default, which ends the process without cleaning up.
    """
    import signal

    if hasattr(signal, "SIGBREAK") and threading.current_thread() is threading.main_thread():
        def raise_interrupt(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGBREAK, raise_interrupt)


def main(argv: list[str] | None = None, app_factory: Callable | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    data_dir = paths.data_dir()
    paths.prepend_bin_to_path()
    setup_logging(data_dir)

    running = find_running(data_dir)
    if running is not None:
        log.info("sifon is already running on port %s", running)
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{running}")
        return 0

    if app_factory is None:
        from app.main import server_app as app_factory  # imported late: yt-dlp overlay must come first
    if args.port:
        if not port_is_free(args.port):
            print(f"El puerto {args.port} está ocupado.", file=sys.stderr)
            return 2
        port = args.port
    else:
        port = choose_port()

    server = ServerThread(app_factory, port)
    server.start()
    if not server.wait_ready():
        log.error("the server did not start")
        server.stop(2)
        print("sifón no pudo iniciar; mirá el registro en " + str(data_dir / "logs" / "sifon.log"), file=sys.stderr)
        return 1
    write_instance(data_dir, port)

    import yt_dlp.version

    desktop = Desktop(data_dir, port, server, yt_dlp.version.__version__)
    log.info("sifon %s ready on %s (yt-dlp %s)", __version__, desktop.url, desktop.installed_ytdlp)
    if sys.stdout is not None:
        print(f"sifón {__version__} escucha en {desktop.url}", flush=True)
    if paths.is_frozen() or os.environ.get("SIFON_ENABLE_OVERLAY"):
        desktop.check_in_background()
    if not args.no_browser:
        desktop.open_browser()

    _stop_on_break_signal()
    try:
        if args.no_window:
            stop = data_dir / STOP_FILE
            stop.unlink(missing_ok=True)
            while server._thread.is_alive() and not stop.exists():
                time.sleep(0.3)
            stop.unlink(missing_ok=True)
        else:
            from app.desktop_ui import run_window

            run_window(desktop)
    except KeyboardInterrupt:
        pass
    finally:
        desktop.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

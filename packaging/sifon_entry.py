"""PyInstaller entry point of sifon.exe.

Order matters: a downloaded yt-dlp update has to be put in front of the bundled copy BEFORE
anything imports yt_dlp, and the update's own self-test must not load the application at all.
"""
import json
import os
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):  # running this file directly during development
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "downloader"))


def selftest_ytdlp(folder: str, expected: str) -> int:
    """`sifon.exe --selftest-ytdlp <folder> <version>`: can this unpacked yt-dlp be imported?"""
    # No exception may escape: a windowed PyInstaller app answers one with a modal dialog that
    # would hang the updater waiting for a click nobody can see.
    try:
        sys.path.insert(0, folder)
        import yt_dlp.version
        import yt_dlp_ejs  # noqa: F401

        import re

        def key(text):
            return [int(x) for x in re.findall(r"\d+", text)]

        if key(yt_dlp.version.__version__) != key(expected):
            print(f"wrong version {yt_dlp.version.__version__}", file=sys.stderr)
            return 1
        print(yt_dlp.version.__version__)
        return 0
    except BaseException as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def bundled_ytdlp_version(resource_dir: Path) -> str | None:
    try:
        return json.loads((resource_dir / "bundled.json").read_text(encoding="utf-8")).get("yt_dlp")
    except (OSError, ValueError):
        return None


def enable_trace() -> None:
    """Diagnostics for a hang: SIFON_TRACE_FILE=<path> dumps every thread's stack after N seconds."""
    target = os.environ.get("SIFON_TRACE_FILE")
    if target:
        import faulthandler

        handle = open(target, "w")  # noqa: SIM115 - must stay open for the life of the process
        faulthandler.enable(handle)
        faulthandler.dump_traceback_later(int(os.environ.get("SIFON_TRACE_SECONDS", "20")), file=handle, exit=True)


def report_crash(error: BaseException) -> None:
    """Write the traceback to the log and, with a window, tell the person where it is."""
    import traceback

    try:
        from app import paths

        crash = paths.data_dir() / "logs" / "crash.log"
        crash.parent.mkdir(parents=True, exist_ok=True)
        crash.write_text("".join(traceback.format_exception(error)), encoding="utf-8")
        where = str(crash)
    except Exception:  # noqa: BLE001
        where = "(no se pudo escribir el registro)"
    if "--no-window" not in sys.argv and not os.environ.get("SIFON_NO_DIALOG"):
        try:
            import tkinter
            from tkinter import messagebox

            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("sifón", "sifón no pudo iniciar.\n\nDetalle en:\n" + where)
        except Exception:  # noqa: BLE001
            pass


def run() -> int:
    enable_trace()
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest-ytdlp":
        return selftest_ytdlp(sys.argv[2], sys.argv[3])
    try:
        return start()
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 - see report_crash
        report_crash(error)
        return 1


def start() -> int:

    from app import paths

    paths.prepend_bin_to_path()
    if paths.is_frozen() or os.environ.get("SIFON_ENABLE_OVERLAY"):
        from app.ytdlp_update import apply_overlay

        apply_overlay(paths.data_dir(), bundled_ytdlp_version(paths.resource_dir()))
    from app.desktop import main

    return main()


if __name__ == "__main__":
    raise SystemExit(run())

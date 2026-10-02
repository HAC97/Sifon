"""The small control window of the packaged app (tkinter, standard library only).

It exists so a person who double-clicked sifon.exe can see that it is running, open the page,
update yt-dlp and, above all, quit it. Closing the window quits sifón; if downloads are running
it asks first.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from app import __version__, paths

REFRESH_MS = 800


class DesktopWindow:
    def __init__(self, root: tk.Tk, desktop, confirm: Callable[[str, str], bool] | None = None):
        self.root = root
        self.desktop = desktop
        self._confirm = confirm or (lambda title, text: messagebox.askyesno(title, text, parent=root))
        self.restart_requested = False

        root.title("sifón")
        root.resizable(False, False)
        icon = paths.resource_dir() / "sifon.ico"
        if icon.is_file():
            try:
                root.iconbitmap(str(icon))
            except tk.TclError:
                pass
        root.protocol("WM_DELETE_WINDOW", self.request_close)

        frame = ttk.Frame(root, padding=16)
        frame.grid()
        ttk.Label(frame, text="sifón", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=f"versión {__version__}", foreground="#666").grid(row=0, column=1, sticky="e")

        self.status = tk.StringVar()
        ttk.Label(frame, textvariable=self.status).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.address = ttk.Label(frame, text=desktop.url, foreground="#0b57d0", cursor="hand2")
        self.address.grid(row=2, column=0, columnspan=2, sticky="w")
        self.address.bind("<Button-1>", lambda _e: self.open_page())

        self.ytdlp = tk.StringVar()
        ttk.Label(frame, textvariable=self.ytdlp, wraplength=360, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        self.auto = tk.BooleanVar(value=self._auto_enabled())
        ttk.Checkbutton(
            frame, text="Buscar actualizaciones de yt-dlp automáticamente", variable=self.auto, command=self.toggle_auto
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="we", pady=(14, 0))
        self.open_button = ttk.Button(buttons, text="Abrir en el navegador", command=self.open_page)
        self.open_button.grid(row=0, column=0, padx=(0, 6))
        self.update_button = ttk.Button(buttons, text="Buscar actualización", command=self.check_now)
        self.update_button.grid(row=0, column=1, padx=(0, 6))
        self.restart_button = ttk.Button(buttons, text="Reiniciar para aplicar", command=self.restart)
        self.quit_button = ttk.Button(buttons, text="Cerrar sifón", command=self.request_close)
        self.quit_button.grid(row=0, column=3)

        self.refresh()

    # -- actions ---------------------------------------------------------------------------------

    def _auto_enabled(self) -> bool:
        from app.ytdlp_update import read_prefs

        return bool(read_prefs(self.desktop.data_dir).get("auto", True))

    def open_page(self) -> None:
        self.desktop.open_browser()

    def toggle_auto(self) -> None:
        self.desktop.set_auto_update(self.auto.get())

    def check_now(self) -> None:
        threading.Thread(target=lambda: self.desktop.check_for_update(force=True), daemon=True).start()
        self.refresh()

    def restart(self) -> None:
        if self._confirm_close_with_jobs("Reiniciar corta las descargas en curso. ¿Reiniciar igual?"):
            self.restart_requested = True
            self.root.destroy()

    def request_close(self) -> None:
        if self._confirm_close_with_jobs("Hay descargas en curso. Si cerrás sifón se cortan. ¿Cerrar igual?"):
            self.root.destroy()

    def _confirm_close_with_jobs(self, question: str) -> bool:
        if self.desktop.server.active_jobs() == 0:
            return True
        return bool(self._confirm("sifón", question))

    # -- state -----------------------------------------------------------------------------------

    def describe_update(self) -> str:
        d = self.desktop
        if d.checking:
            return f"yt-dlp {d.installed_ytdlp}. Buscando actualización…"
        if d.update is None:
            return f"yt-dlp {d.installed_ytdlp}."
        return f"yt-dlp {d.installed_ytdlp}. {d.update.detail}"

    def refresh(self) -> None:
        jobs = self.desktop.server.active_jobs()
        self.status.set("Funcionando." if jobs == 0 else f"Funcionando. Descargas en curso: {jobs}.")
        self.ytdlp.set(self.describe_update())
        self.update_button.state(["disabled"] if self.desktop.checking else ["!disabled"])
        if self.desktop.restart_needed:
            self.restart_button.grid(row=0, column=2, padx=(0, 6))
        else:
            self.restart_button.grid_remove()
        self.root.after(REFRESH_MS, self.refresh)


def run_window(desktop) -> None:
    """Show the window until it is closed. Restarts the program afterwards if asked to."""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    window = DesktopWindow(root, desktop)
    root.mainloop()
    if window.restart_requested:
        desktop.restart()

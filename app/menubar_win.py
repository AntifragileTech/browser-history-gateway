# Created: 21:55 27-Apr-2026
"""Windows system-tray app wrapper for Browser History Gateway.

Mirrors the macOS menubar surface but uses pystray for the tray icon
and pywebview (Edge WebView2) for the in-app search window. Windows
has no equivalent of macOS Full Disk Access — Chrome/Edge/Firefox
profile dirs live under the user's own AppData and are always readable
by their own process, so we skip the permission nag entirely.

Launched by PyInstaller as the entry point of Browser-History-Gateway.exe.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from collector import run as collector_run
from web import app as web_app

LOG_DIR = Path("~/.browser-history").expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "app.log")],
)
log = logging.getLogger("app.menubar_win")

WEB_HOST = "127.0.0.1"
FSEVENTS_DEBOUNCE_S = 5


def _resource_path(rel: str) -> Path:
    """Return the absolute path to a bundled resource.

    PyInstaller --onefile extracts data files to sys._MEIPASS at runtime;
    in dev (running from source) we just use the project root.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def _icon_image():
    """Load the tray icon as a PIL.Image. Falls back to a 16x16 black
    square if the bundled PNG can't be found."""
    from PIL import Image
    for candidate in (
        _resource_path("assets/menubar_template@2x.png"),
        _resource_path("assets/menubar_template.png"),
        _resource_path("assets/logo.png"),
    ):
        if candidate.exists():
            return Image.open(candidate)
    return Image.new("RGB", (16, 16), color=(0, 0, 0))


def _watch_paths_for_windows() -> list[Path]:
    """Directories to feed to watchdog's ReadDirectoryChangesW backend.
    Mirror of WATCH_PATHS in menubar_mac.py but for Windows browser layouts.
    """
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
    return [
        local / "Google/Chrome/User Data",
        local / "BraveSoftware/Brave-Browser/User Data",
        local / "Microsoft/Edge/User Data",
        local / "Vivaldi/User Data",
        local / "Chromium/User Data",
        appdata / "Mozilla/Firefox/Profiles",
    ]


class TrayApp:
    """Container for the pystray icon + the FastAPI server thread + the
    pywebview window. pywebview must run on the main thread on Windows,
    so the structure mirrors that constraint:

    - main thread: pywebview event loop (started lazily on first window)
    - tray thread: pystray.Icon.run()
    - server thread: uvicorn
    - collector thread: run_loop
    - watcher thread: watchdog Observer
    """

    def __init__(self) -> None:
        self._port = web_app.pick_open_port()
        web_app.write_port(self._port)
        self._running = True
        self._window = None
        self._main_thread_callbacks: list = []  # webview only allows main thread
        self._init_db_safely()

    def _init_db_safely(self) -> None:
        try:
            collector_run.init_db()
        except Exception:
            log.exception("failed to init DB at startup")

    def _url(self, path: str) -> str:
        return f"http://{WEB_HOST}:{self._port}{path}"

    # ----- background workers -----
    def _serve_web(self) -> None:
        try:
            import uvicorn
            uvicorn.run(
                web_app.app,
                host=WEB_HOST,
                port=self._port,
                log_level="warning",
                loop="asyncio",
                http="h11",
            )
        except Exception:
            log.exception("web server crashed")

    def _collect_loop(self) -> None:
        time.sleep(3)
        # On first launch with empty DB, schedule the welcome window.
        try:
            if collector_run.DB_PATH.exists():
                import sqlite3
                with sqlite3.connect(f"file:{collector_run.DB_PATH}?mode=ro", uri=True) as c:
                    n = c.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
                if n == 0:
                    self._open_window("/welcome")
        except Exception:
            log.exception("welcome-on-first-launch check failed; continuing")
        collector_run.run_loop(stop_flag=lambda: not self._running)

    def _start_watcher(self) -> None:
        """Watch Chrome/Brave/Edge/Firefox profile dirs and trigger an
        immediate (debounced) collection on every history-file write."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except Exception:
            log.exception("watchdog unavailable; file watcher disabled")
            return

        app_self = self

        class _HistoryChangeHandler(FileSystemEventHandler):
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._timer: Optional[threading.Timer] = None

            def on_any_event(self, event) -> None:
                name = Path(event.src_path).name
                if not (name.startswith("History") or name.startswith("places.sqlite")):
                    return
                with self._lock:
                    if self._timer is not None:
                        self._timer.cancel()
                    self._timer = threading.Timer(
                        FSEVENTS_DEBOUNCE_S, self._fire
                    )
                    self._timer.daemon = True
                    self._timer.start()

            def _fire(self) -> None:
                log.info("watcher: triggering collection from file change")
                try:
                    collector_run.run_once()
                except Exception:
                    log.exception("on-change collection failed")

        observer = Observer()
        handler = _HistoryChangeHandler()
        for p in _watch_paths_for_windows():
            if p.exists():
                try:
                    observer.schedule(handler, str(p), recursive=True)
                    log.info("watcher: watching %s", p)
                except Exception:
                    log.exception("watcher: failed to watch %s", p)
        observer.daemon = True
        observer.start()
        self._observer = observer

    # ----- window -----
    def _open_window(self, path: str = "/") -> None:
        """Show (or re-navigate) the pywebview window. Must be called on
        the main thread — see _drain_main_thread."""
        # Defer to the main thread loop.
        self._main_thread_callbacks.append(lambda: self._do_open_window(path))

    def _do_open_window(self, path: str) -> None:
        import webview
        url = self._url(path)
        if self._window is None:
            self._window = webview.create_window(
                "Browser History Gateway", url=url,
                width=1280, height=820, resizable=True,
            )
            # Start the webview event loop. This blocks until all windows
            # close, so it only runs once per process — pystray runs in
            # its own thread.
            webview.start()
        else:
            try:
                self._window.load_url(url)
                self._window.show()
            except Exception:
                log.exception("could not navigate webview to %s", path)

    def _drain_main_thread(self) -> None:
        """Run any queued main-thread callbacks. Called periodically by
        a timer set up before pystray starts."""
        while self._main_thread_callbacks:
            cb = self._main_thread_callbacks.pop(0)
            try:
                cb()
            except Exception:
                log.exception("main-thread callback failed")

    # ----- tray menu actions -----
    def on_open_search(self, icon, item) -> None:
        self._open_window("/")

    def on_open_browser(self, icon, item) -> None:
        webbrowser.open(self._url("/"))

    def on_run_now(self, icon, item) -> None:
        threading.Thread(target=self._safe_collect_once, daemon=True).start()

    def on_open_data(self, icon, item) -> None:
        # Windows: explorer takes a path arg.
        try:
            os.startfile(str(LOG_DIR))  # noqa: S606 - intentional
        except Exception:
            subprocess.Popen(["explorer", str(LOG_DIR)])

    def on_quit(self, icon, item) -> None:
        self._running = False
        try:
            icon.stop()
        except Exception:
            pass
        try:
            import webview
            for w in webview.windows:
                w.destroy()
        except Exception:
            pass
        # Kill the process — uvicorn + watchdog daemons exit with us.
        os._exit(0)

    def _safe_collect_once(self) -> None:
        try:
            collector_run.run_once()
        except Exception:
            log.exception("manual collection failed")

    # ----- main loop -----
    def run(self) -> None:
        # Start background threads.
        threading.Thread(target=self._serve_web, daemon=True).start()
        threading.Thread(target=self._collect_loop, daemon=True).start()
        threading.Thread(target=self._start_watcher, daemon=True).start()

        # pywebview wants to live on the main thread. pystray must therefore
        # run on a worker thread on Windows. The helper-callbacks queue
        # bridges the two so menu clicks can spawn a webview window.
        import pystray
        from pystray import Menu, MenuItem
        icon = pystray.Icon(
            "browser_history_gateway",
            icon=_icon_image(),
            title="Browser History Gateway",
            menu=Menu(
                MenuItem("Open Search", self.on_open_search, default=True),
                MenuItem("Open in External Browser", self.on_open_browser),
                MenuItem("Run Collection Now", self.on_run_now),
                Menu.SEPARATOR,
                MenuItem("Open Data Folder", self.on_open_data),
                Menu.SEPARATOR,
                MenuItem("Quit", self.on_quit),
            ),
        )
        threading.Thread(target=icon.run, daemon=True).start()

        # Main thread: pump the webview-callback queue. Open the welcome
        # window on first launch (if scheduled), then sit in the webview
        # event loop until the user quits. While the queue is empty we
        # poll cheaply at 4 Hz.
        while self._running:
            if self._main_thread_callbacks:
                self._drain_main_thread()
                # _do_open_window starts webview.start(), which blocks
                # the main thread; on return the user closed the window.
            else:
                time.sleep(0.25)


def main() -> None:
    TrayApp().run()


if __name__ == "__main__":
    main()

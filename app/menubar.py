# Created: 20:40 21-Apr-2026
# Updated: 20:44 21-Apr-2026
# Updated: 20:48 21-Apr-2026
# Updated: 20:56 21-Apr-2026
# Updated: 20:59 21-Apr-2026
"""Menu bar app wrapper for Browser History Gateway.

Runs the collector every 10 minutes + an embedded FastAPI UI on
127.0.0.1:8765, all from a single menu-bar icon. Handles first-run
Full Disk Access check and guides the user to grant it.

Launched by py2app as the entry point of BrowserHistoryGateway.app.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

import rumps

# The collector + web modules are importable because py2app bundles them.
from collector import run as collector_run
from web import app as web_app

LOG_DIR = Path("~/.browser-history").expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "app.log")],
)
log = logging.getLogger("app.menubar")

WEB_HOST = "127.0.0.1"
WEB_PORT = 8765

# FSEvents: which directories contain browser history files we care about.
# We watch recursively and filter event paths by filename (History*,
# places.sqlite*) so we ignore cookies, cache, extension shuffles, etc.
WATCH_PATHS = [
    Path("~/Library/Application Support/Google/Chrome").expanduser(),
    Path("~/Library/Application Support/BraveSoftware/Brave-Browser").expanduser(),
    Path("~/Library/Application Support/Microsoft Edge").expanduser(),
    Path("~/Library/Application Support/Arc/User Data").expanduser(),
    Path("~/Library/Application Support/Firefox/Profiles").expanduser(),
    Path("~/Library/Safari").expanduser(),
]
# Debounce: rapid Chrome writes shouldn't trigger a flood of collections.
FSEVENTS_DEBOUNCE_S = 5
FDA_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?"
    "Privacy_AllFiles"
)
SAFARI_DB = Path("~/Library/Safari/History.db").expanduser()


def _has_full_disk_access() -> bool:
    """Probe FDA by trying to read the first byte of Safari's History.db.
    We don't care about the content — only whether macOS refuses.
    """
    if not SAFARI_DB.exists():
        # No Safari installed? Treat as "not blocking" — no reason to nag.
        return True
    try:
        with open(SAFARI_DB, "rb") as f:
            f.read(1)
        return True
    except (PermissionError, OSError):
        return False


class BrowserHistoryApp(rumps.App):
    def __init__(self) -> None:
        # Use a PNG template image so the icon renders at the same size
        # as every other menu-bar icon and auto-inverts in dark mode.
        # Falls back to the ⏱ emoji if the PNG isn't bundled.
        icon_path: str | None = None
        for candidate in (
            Path(__file__).resolve().parent.parent / "assets" / "menubar_template.png",
            # py2app ships everything in Contents/Resources/ at runtime.
            Path(__file__).resolve().parent / "menubar_template.png",
        ):
            if candidate.exists():
                icon_path = str(candidate)
                break
        super().__init__(
            name="BrowserHistory",
            title=None if icon_path else "⏱",
            icon=icon_path,
            template=True,   # treat icon as a template for dark-mode adaptation
            quit_button=None,
        )
        self.menu = [
            rumps.MenuItem("Open Search", callback=self.open_search),
            rumps.MenuItem("Open in External Browser", callback=self.open_search_browser),
            rumps.MenuItem("Run Collection Now", callback=self.collect_now),
            None,
            rumps.MenuItem("Status: starting…", callback=None),
            None,
            rumps.MenuItem("Check Permissions", callback=self.check_perms_menu),
            rumps.MenuItem("Open Data Folder", callback=self.open_data_folder),
            rumps.MenuItem("Launch at Login…", callback=self.launch_at_login),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]
        self._main_window = None  # keep reference so NSWindow isn't GC'd
        self._main_webview = None
        self._status_item = self.menu["Status: starting…"]
        self._last_collect_ts = 0.0
        self._last_collect_count = 0
        self._pending_status: str | None = None
        self._running = True
        self._start_threads()
        # First-run permission nag after a short delay so the menu bar
        # icon is visible before the modal pops.
        rumps.Timer(self._first_run_check, 2).start()
        # Main-thread pump: any background thread writes to
        # `_pending_status`; this timer reads & applies it on the main
        # thread because Cocoa refuses cross-thread UI mutation.
        self._status_pump = rumps.Timer(self._pump_status, 1)
        self._status_pump.start()

    # ----- menu actions -----
    def open_search(self, _):
        """Show the search UI inside a native WKWebView window — no
        external browser needed. If the WebKit framework isn't available
        for some reason (older macOS, missing PyObjC framework), fall
        back to opening the default browser.
        """
        try:
            self._open_app_window()
        except Exception:
            log.exception("in-app window failed; falling back to browser")
            self.open_search_browser(None)

    def open_search_browser(self, _):
        webbrowser.open(f"http://{WEB_HOST}:{WEB_PORT}/")

    def collect_now(self, _):
        threading.Thread(target=self._collect_once, daemon=True).start()
        # No notification — status updates appear in the menu item itself.

    def check_perms_menu(self, _):
        self._check_permissions(interactive=True)

    def open_data_folder(self, _):
        subprocess.run(["open", str(LOG_DIR)])

    def quit_app(self, _):
        self._running = False
        rumps.quit_application()

    # ----- background work -----
    def _start_threads(self) -> None:
        # Initialize the DB BEFORE the web server starts — otherwise a
        # first-launch user hitting the UI sees a 500 because the read-only
        # SQLite connection has no file to open yet.
        try:
            collector_run.init_db()
        except Exception:
            log.exception("failed to init DB at startup; UI may 500 until first sync")
        threading.Thread(target=self._serve_web, daemon=True).start()
        threading.Thread(target=self._collect_loop, daemon=True).start()
        threading.Thread(target=self._start_fsevents_watcher, daemon=True).start()

    def _serve_web(self) -> None:
        try:
            import uvicorn
            # py2app struggles to bundle uvloop's C extension, which
            # uvicorn tries to load by default. Force stdlib asyncio —
            # plenty fast for a single-user local tool.
            uvicorn.run(
                web_app.app,
                host=WEB_HOST,
                port=WEB_PORT,
                log_level="warning",
                loop="asyncio",
                http="h11",
            )
        except Exception:
            log.exception("web server crashed")

    def _collect_once(self) -> None:
        try:
            # Ensure DB exists (fresh install with no prior run).
            if not collector_run.DB_PATH.exists():
                collector_run.init_db()
            results = collector_run.run_once()
            count = sum(results.values())
            self._last_collect_ts = time.time()
            self._last_collect_count = count
            when = time.strftime("%H:%M:%S", time.localtime(self._last_collect_ts))
            # Main-thread UI pump reads this later.
            self._pending_status = f"Last run: {when} ({count} new)"
            # Intentionally no rumps.notification() here — the user can
            # glance at the menu bar if they want a status. Toast popups
            # every 10 minutes are annoying for a background tool.
        except Exception as e:
            log.exception("collection failed")
            self._pending_status = f"Status: error — {type(e).__name__}"

    def _collect_loop(self) -> None:
        # Delay the first collection a few seconds so the web server is
        # up and any permission nag has a chance to render. After that,
        # the collector itself handles random-jittered 45-60 s intervals
        # and writes sync_state.json for the UI countdown to read.
        time.sleep(3)
        collector_run.run_loop(stop_flag=lambda: not self._running)

    def _start_fsevents_watcher(self) -> None:
        """Watch browser profile dirs for changes to their History DBs
        and trigger an immediate collection (debounced) whenever one
        gets written. Closes the gap between a visit landing in Chrome
        and our snapshot from minutes to seconds.
        """
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except Exception:
            log.exception("watchdog unavailable; FSEvents watcher disabled")
            return

        app_self = self

        class _HistoryChangeHandler(FileSystemEventHandler):
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._timer: threading.Timer | None = None

            def on_any_event(self, event) -> None:
                name = Path(event.src_path).name
                # Chromium: "History", "History-journal", etc.
                # Firefox: "places.sqlite", "places.sqlite-wal", etc.
                # Safari:  "History.db", "History.db-wal", etc.
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
                log.info("fsevents: triggering collection from file change")
                app_self._collect_once()

        observer = Observer()
        handler = _HistoryChangeHandler()
        for p in WATCH_PATHS:
            if p.exists():
                try:
                    observer.schedule(handler, str(p), recursive=True)
                    log.info("fsevents: watching %s", p)
                except Exception:
                    log.exception("fsevents: failed to watch %s", p)
        observer.daemon = True
        observer.start()
        self._observer = observer  # keep ref so it isn't GC'd

    def _open_app_window(self) -> None:
        """Create (or re-show) a native NSWindow containing a WKWebView
        that points at the embedded FastAPI server. Must run on the main
        thread — rumps menu callbacks already are.
        """
        from AppKit import (
            NSWindow, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
            NSWindowStyleMaskResizable, NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered, NSViewWidthSizable, NSViewHeightSizable,
            NSApplication, NSApplicationActivationPolicyRegular,
        )
        from Foundation import NSURL, NSURLRequest, NSMakeRect
        from WebKit import WKWebView, WKWebViewConfiguration

        # If the window already exists, just bring it to front.
        if self._main_window is not None:
            self._main_window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            return

        frame = NSMakeRect(0, 0, 1280, 820)
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskMiniaturizable
        )
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False
        )
        window.setTitle_("Browser History Gateway")
        window.center()
        # Remember window size across launches — Cocoa does this for free
        # if we set an autosave name.
        window.setFrameAutosaveName_("BrowserHistoryMainWindow")

        config = WKWebViewConfiguration.alloc().init()
        webview = WKWebView.alloc().initWithFrame_configuration_(
            window.contentView().bounds(), config
        )
        webview.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        window.contentView().addSubview_(webview)

        url = NSURL.URLWithString_(f"http://{WEB_HOST}:{WEB_PORT}/")
        webview.loadRequest_(NSURLRequest.requestWithURL_(url))

        # Apps with LSUIElement=True start as "accessory" agents (no Dock
        # icon). Temporarily register as a regular app so the NSWindow
        # can take focus and the user sees it in the Cmd-Tab list.
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyRegular
        )
        window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        # Keep Python references so ARC doesn't collect them.
        self._main_window = window
        self._main_webview = webview

    def _pump_status(self, _timer) -> None:
        """Main-thread status pump: apply any pending status update to
        the menu item. Called via rumps.Timer which fires on main thread.
        """
        if self._pending_status is not None:
            self._status_item.title = self._pending_status
            self._pending_status = None

    def launch_at_login(self, _) -> None:
        """Point the user at the System Settings → Login Items pane."""
        rumps.alert(
            title="Launch at Login",
            message=(
                "To start Browser History Gateway automatically at login:\n\n"
                "1. System Settings → General → Login Items & Extensions\n"
                "2. Click '+' under 'Open at Login' and add this app.\n\n"
                "(Click OK to open the pane now.)"
            ),
        )
        subprocess.run(
            [
                "open",
                "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
            ]
        )

    # ----- permissions -----
    def _first_run_check(self, _timer) -> None:
        _timer.stop()
        if not _has_full_disk_access():
            self._prompt_for_fda()

    def _check_permissions(self, interactive: bool) -> bool:
        ok = _has_full_disk_access()
        if ok and interactive:
            rumps.alert(
                title="Permissions OK",
                message="Full Disk Access is granted. Safari history will be collected.",
            )
        elif not ok and interactive:
            self._prompt_for_fda()
        return ok

    def _prompt_for_fda(self) -> None:
        window = rumps.Window(
            title="Full Disk Access required",
            message=(
                "Browser History Gateway needs Full Disk Access to read "
                "Safari's history database. Chrome/Brave/Arc/Edge work "
                "without it.\n\n"
                "Click “Open Settings”, then drag this app into the "
                "list (or toggle it on). After granting, fully quit and "
                "reopen the app."
            ),
            ok="Open Settings",
            cancel="Skip for now",
            default_text="",
        )
        window.icon = None
        resp = window.run()
        if resp.clicked:
            subprocess.run(["open", FDA_SETTINGS_URL])


def main() -> None:
    BrowserHistoryApp().run()


if __name__ == "__main__":
    main()

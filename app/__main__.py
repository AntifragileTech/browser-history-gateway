# Created: 21:55 27-Apr-2026
"""Cross-platform entry point.

Dispatches to the macOS menubar implementation (rumps + WKWebView) or
the Windows tray implementation (pystray + pywebview) based on the
running platform. Linux is unsupported for the GUI but the collector
itself is portable — `python -m collector.run` will work.
"""
from __future__ import annotations

import sys


def main() -> None:
    if sys.platform == "darwin":
        from app.menubar_mac import main as platform_main
    elif sys.platform == "win32":
        from app.menubar_win import main as platform_main
    else:
        raise SystemExit(
            "Browser History Gateway's GUI is macOS-only or Windows-only.\n"
            "On Linux you can run the collector directly:\n"
            "    python -m collector.run --loop"
        )
    platform_main()


if __name__ == "__main__":
    main()

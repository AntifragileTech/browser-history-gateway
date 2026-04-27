# Created: 21:55 27-Apr-2026
"""Cross-platform browser path resolution.

macOS keeps each browser under
  ~/Library/Application Support/<Vendor>/<Browser>/...
Windows keeps Chromium-family browsers under
  %LOCALAPPDATA%\\<Vendor>\\<Browser>\\User Data\\...
and Firefox under
  %APPDATA%\\Mozilla\\Firefox\\Profiles\\...

Each OS's path layout is captured here so the per-browser collectors can
stay platform-agnostic. Linux is supported on a best-effort basis (XDG
config dirs); Safari is macOS-only by definition.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def _expand(path: str) -> Path:
    """Expand ~ and environment variables, returning an absolute Path."""
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def chromium_known_browsers() -> list[tuple[str, Path]]:
    """Return [(slug, profile-root path), ...] for every Chromium-family
    browser that *could* exist on this OS. The caller should filter to
    those whose path actually contains a `Local State` file.
    """
    if sys.platform == "darwin":
        base = Path("~/Library/Application Support").expanduser()
        return [
            ("chrome",          base / "Google/Chrome"),
            ("chrome-beta",     base / "Google/Chrome Beta"),
            ("chrome-canary",   base / "Google/Chrome Canary"),
            ("chrome-dev",      base / "Google/Chrome Dev"),
            ("brave",           base / "BraveSoftware/Brave-Browser"),
            ("brave-beta",      base / "BraveSoftware/Brave-Browser-Beta"),
            ("brave-nightly",   base / "BraveSoftware/Brave-Browser-Nightly"),
            ("edge",            base / "Microsoft Edge"),
            ("edge-beta",       base / "Microsoft Edge Beta"),
            ("edge-dev",        base / "Microsoft Edge Dev"),
            ("arc",             base / "Arc/User Data"),
            ("vivaldi",         base / "Vivaldi"),
            ("opera",           base / "com.operasoftware.Opera"),
            ("opera-gx",        base / "com.operasoftware.OperaGX"),
            ("whale",           base / "Naver/Whale"),
            ("chromium",        base / "Chromium"),
            ("sidekick",        base / "Sidekick"),
            ("yandex",          base / "Yandex/YandexBrowser"),
        ]
    if sys.platform == "win32":
        local = _expand(os.environ.get("LOCALAPPDATA", r"%USERPROFILE%\AppData\Local"))
        return [
            ("chrome",          local / "Google/Chrome/User Data"),
            ("chrome-beta",     local / "Google/Chrome Beta/User Data"),
            ("chrome-canary",   local / "Google/Chrome SxS/User Data"),
            ("chrome-dev",      local / "Google/Chrome Dev/User Data"),
            ("brave",           local / "BraveSoftware/Brave-Browser/User Data"),
            ("brave-beta",      local / "BraveSoftware/Brave-Browser-Beta/User Data"),
            ("brave-nightly",   local / "BraveSoftware/Brave-Browser-Nightly/User Data"),
            ("edge",            local / "Microsoft/Edge/User Data"),
            ("edge-beta",       local / "Microsoft/Edge Beta/User Data"),
            ("edge-dev",        local / "Microsoft/Edge Dev/User Data"),
            ("vivaldi",         local / "Vivaldi/User Data"),
            ("opera",           local / "Opera Software/Opera Stable"),
            ("opera-gx",        local / "Opera Software/Opera GX Stable"),
            ("chromium",        local / "Chromium/User Data"),
        ]
    # Linux fallback (best effort — not officially supported)
    config = Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser()
    return [
        ("chrome",   config / "google-chrome"),
        ("chromium", config / "chromium"),
        ("brave",    config / "BraveSoftware/Brave-Browser"),
        ("edge",     config / "microsoft-edge"),
        ("vivaldi",  config / "vivaldi"),
        ("opera",    config / "opera"),
    ]


def chromium_appsupport_root() -> Path:
    """Top of the per-OS tree where Chromium browsers store data — used
    for the recursive-discovery fallback that finds Local State files
    inside browsers we don't have in our curated list."""
    if sys.platform == "darwin":
        return Path("~/Library/Application Support").expanduser()
    if sys.platform == "win32":
        return _expand(os.environ.get("LOCALAPPDATA", r"%USERPROFILE%\AppData\Local"))
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser()


def firefox_profiles_root() -> Path:
    if sys.platform == "darwin":
        return Path("~/Library/Application Support/Firefox/Profiles").expanduser()
    if sys.platform == "win32":
        appdata = _expand(os.environ.get("APPDATA", r"%USERPROFILE%\AppData\Roaming"))
        return appdata / "Mozilla/Firefox/Profiles"
    return Path("~/.mozilla/firefox").expanduser()


def safari_history_path() -> Optional[Path]:
    """Safari only exists on macOS. Returns None elsewhere."""
    if sys.platform == "darwin":
        return Path("~/Library/Safari/History.db").expanduser()
    return None


def safari_watch_path() -> Optional[Path]:
    """Directory for FSEvents to watch for Safari history writes."""
    if sys.platform == "darwin":
        return Path("~/Library/Safari").expanduser()
    return None

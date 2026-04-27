# Created: 20:40 21-Apr-2026
# Updated: 20:43 21-Apr-2026
# Updated: 21:55 27-Apr-2026
"""py2app build configuration for Browser History Gateway.

Build with:    ./build_app.sh
Manual build:  python3 setup_app.py py2app

The BHG_ARCH env var (default 'arm64') selects the target macOS arch.
Both 'arm64' and 'x86_64' build natively from a macos-14 (arm64) runner
because pyobjc + Python 3.11 ship as universal2 wheels — py2app slices
the binaries via lipo to produce a single-arch .app.
"""
import os

from setuptools import setup

APP = ["app/menubar_mac.py"]
ARCH = os.environ.get("BHG_ARCH", "arm64")

OPTIONS = {
    "argv_emulation": False,
    "arch": ARCH,
    "plist": {
        "CFBundleName": "Browser History Gateway",
        "CFBundleDisplayName": "Browser History Gateway",
        "CFBundleIdentifier": "com.antifragiletech.browserhistorygateway",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        # Menu-bar only — no Dock icon, no Cmd-Tab entry.
        "LSUIElement": True,
        # Allow launch at login via System Settings -> Login Items.
        "LSMultipleInstancesProhibited": True,
        "NSHumanReadableCopyright": "(c) 2026 Browser History Gateway",
        # Minimum supported macOS — see .github/workflows/build.yml env.
        "LSMinimumSystemVersion": "12.0",
    },
    # `packages` copies a package's entire source tree (good for things
    # that do dynamic imports). `includes` just pulls in a module by name.
    # Keep `packages` limited to the big dynamic-import offenders; let
    # py2app's static analysis + `includes` handle the rest.
    "packages": [
        "fastapi",
        "uvicorn",
        "starlette",
        "jinja2",
        "rumps",
        "pydantic",
        "pydantic_core",
        # anyio has a dynamically-imported `_backends` subpackage (asyncio
        # or trio). Listing the whole `anyio` package forces py2app to
        # copy the entire source tree so the runtime lookup succeeds.
        "anyio",
        # watchdog ships platform-specific backends (fsevents on macOS)
        # that it imports dynamically at runtime.
        "watchdog",
        "collector",
        "web",
    ],
    "includes": [
        "sqlite3",
        "email",
        "sniffio",
        "h11",
        "click",
        "typing_extensions",
        "annotated_types",
        "WebKit",
        "AppKit",
        "Foundation",
    ],
    "resources": [
        "schema.sql",
        "web/templates",
        "assets/menubar_template.png",
        "assets/menubar_template@2x.png",
    ],
    # App-bundle icon shown in the Dock, Finder, Cmd-Tab, etc.
    "iconfile": "assets/AppIcon.icns",
    "excludes": [
        "tkinter",
        "test",
        "unittest",
        # pystray + pywebview are only used on Windows; exclude from .app
        # so py2app doesn't try to bundle their Win32-specific deps.
        "pystray",
        "webview",
    ],
}

setup(
    app=APP,
    data_files=[],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)

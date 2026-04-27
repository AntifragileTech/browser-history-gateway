<!-- Created: 18:59 21-Apr-2026 -->
<!-- Updated: 20:32 21-Apr-2026 -->
<!-- Updated: 23:54 21-Apr-2026 -->
<!-- Updated: 23:58 21-Apr-2026 -->
<!-- Updated: 21:55 27-Apr-2026 -->
<p align="center">
  <img src="assets/logo.png" alt="Browser History Gateway logo" width="160" />
</p>

<h1 align="center">Browser History Gateway</h1>

<p align="center">
  <em>An open-source, local-only archive of every page you've ever visited —
  across every browser and profile, on Mac and Windows.<br>
  The code is public. The data never leaves your machine.</em>
</p>

<p align="center">
  <a href="https://github.com/AntifragileTech/browser-history-gateway/releases/latest/download/Browser-History-Gateway-arm64.dmg">
    <img src="https://img.shields.io/badge/Download-macOS%20Apple%20Silicon-5b8def?logo=apple&logoColor=white&style=for-the-badge" alt="Download for Apple Silicon" />
  </a>
  &nbsp;
  <a href="https://github.com/AntifragileTech/browser-history-gateway/releases/latest/download/Browser-History-Gateway-intel.dmg">
    <img src="https://img.shields.io/badge/Download-macOS%20Intel-444?logo=apple&logoColor=white&style=for-the-badge" alt="Download for Intel Mac" />
  </a>
  &nbsp;
  <a href="https://github.com/AntifragileTech/browser-history-gateway/releases/latest/download/Browser-History-Gateway-windows.exe">
    <img src="https://img.shields.io/badge/Download-Windows%2010%2F11-0078D4?logo=windows&logoColor=white&style=for-the-badge" alt="Download for Windows" />
  </a>
</p>

<p align="center">
  <sub>Don't know which Mac you have? <strong>Apple menu → About This Mac → Chip</strong>.
  Apple M1 / M2 / M3 / M4 = Apple Silicon. Anything with "Intel" = Intel.</sub>
</p>

---

A local desktop app that aggregates browsing history from every installed
browser and profile into a single searchable SQLite database — then lets
you search across date, time, browser, profile, URL, and title from a
native in-app window.

- **Archive forever.** Chrome auto-expires history at 90 days. We don't.
- **Never misses anything.** Runs every 45–60 seconds *and* on file-change
  via FSEvents (macOS) / ReadDirectoryChangesW (Windows), so visits are
  captured within seconds.
- **Local-only.** Everything stays on your machine. No cloud, no telemetry.

Supports: **Chrome** (all profiles, with your custom profile names),
**Brave**, **Arc**, **Edge**, **Vivaldi**, **Opera**, **Safari** (macOS only),
**Firefox**, plus auto-discovery of any other Chromium fork.

---

## Install — macOS

1. Click the button above for your Mac's chip, or grab the DMG directly:
   - **Apple Silicon** (M1/M2/M3/M4) →
     [Browser-History-Gateway-arm64.dmg](https://github.com/AntifragileTech/browser-history-gateway/releases/latest/download/Browser-History-Gateway-arm64.dmg)
   - **Intel Mac** →
     [Browser-History-Gateway-intel.dmg](https://github.com/AntifragileTech/browser-history-gateway/releases/latest/download/Browser-History-Gateway-intel.dmg)
2. Open the DMG, drag **Browser History Gateway** into **Applications**.
3. Double-click the app from Applications. macOS will block it on first
   launch ("can't be opened because Apple cannot check it for malicious
   software" — the app is unsigned because we don't have a paid Apple
   Developer account). To allow it:

   **System Settings → Privacy & Security → scroll to the bottom →
   click "Open Anyway" next to "Browser History Gateway"**.

   Then double-click the app again. You only need to do this once per Mac.
4. The menu-bar icon appears at the top of the screen.
5. The **Welcome window** opens automatically on first launch. It walks
   you through:
   - Granting **Full Disk Access** (required only for Safari history —
     Chrome/Brave/Arc/Edge/Firefox work without it).
   - Listing every browser + profile detected on your Mac.
   - Running the first collection so you immediately have data to search.
6. After the welcome window, click the menu-bar icon → **Open Search**
   to bring up the in-app search window any time.

## Install — Windows

1. Click the **Windows** button above, or grab the EXE directly:
   [Browser-History-Gateway-windows.exe](https://github.com/AntifragileTech/browser-history-gateway/releases/latest/download/Browser-History-Gateway-windows.exe)
2. Double-click the EXE. Windows SmartScreen will warn:
   "Windows protected your PC … publisher: Unknown". (We don't have a
   paid code-signing certificate.)
   Click **More info → Run anyway**.
3. The system-tray icon appears (look in the hidden-icon ▴ tray on the
   right side of the taskbar — drag it onto the visible tray for easy
   access).
4. The **Welcome window** opens automatically on first launch and lists
   every browser + profile detected, then runs the first collection.
5. Right-click the tray icon → **Open Search** any time afterwards.

> **Windows requirements**: Windows 10 21H2+ or Windows 11. Edge WebView2
> runtime is preinstalled on all supported versions; if it's missing you
> can install it from
> [Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/).

## What you get

- **Menu-bar / tray app** with *Open Search*, *Run Collection Now*,
  *Open Data Folder*, *Quit*. macOS also has *Check Permissions* and
  *Launch at Login*.
- **Native in-app search window** — no external browser required.
  Filters by keyword (with hit highlighting), browser, profile, domain,
  and date. Quick-range presets: Today / Yesterday / This week /
  Last 7 / This month / Last 30 / last 3 full months / All time / custom.
- **Sync status bar** showing last-synced time, countdown to next sync,
  Sync Now + Refresh buttons.
- **Serial-numbered rows**, descending from the most recent visit,
  continuing across pages.
- **Auto-reload** after every sync — new rows appear without you clicking
  anything.

## What's collected

- URL, page title, visit timestamp, browser, profile (with your friendly
  name, e.g. "Work" / "Personal"), and Chrome/Firefox transition type
  (link / typed / reload / …).
- Data location: `~/.browser-history/history.db` (SQLite, WAL-mode) —
  same path on macOS, Windows, and Linux.
- Logs: `~/.browser-history/collector.log` and `app.log`.
- Config: `~/.browser-history/config.json` (optional — see below).

Incognito / Private tabs are NOT stored by browsers, so there's nothing
to collect. Deletes in the source browser do not propagate to our DB —
once we have a visit, we keep it.

## Configuration

Optional. Create `~/.browser-history/config.json`:

```json
{
  "sync_interval_min_s": 45,
  "sync_interval_max_s": 60
}
```

The collector picks a random interval between `min` and `max` each pass
(default 45–60 s). File-change events (FSEvents on macOS,
ReadDirectoryChangesW on Windows) trigger an additional collection
within ~5 s of any browser write.

## Developer setup

### Run from source — macOS / Linux

```bash
git clone https://github.com/AntifragileTech/browser-history-gateway.git
cd browser-history-gateway

./install.sh              # venv + deps + DB + one collection pass
./install.sh --agent      # also installs a launchd agent (no .app needed)

# Build the menu-bar .app + DMG yourself:
./build_app.sh --dmg                    # arm64 (default)
BHG_ARCH=x86_64 ./build_app.sh --dmg    # Intel slice from a universal2 toolchain

# Update-in-place workflow:
./update_app.sh           # rebuild + replace /Applications/... + relaunch
```

### Run from source — Windows

```powershell
git clone https://github.com/AntifragileTech/browser-history-gateway.git
cd browser-history-gateway

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-windows.txt

# Run directly (tray icon will appear):
python -m app

# Or build a single-file EXE:
.\build_windows.ps1
```

### Tests

```bash
pip install pytest pytest-cov
pytest                                    # 79 tests, ~1 second
pytest --cov=collector --cov=web          # with coverage report
```

### Project layout

```
app/menubar_mac.py        # rumps menu-bar + WKWebView in-app window (macOS)
app/menubar_win.py        # pystray tray + pywebview in-app window (Windows)
app/__main__.py           # platform dispatcher entry point
collector/paths.py        # cross-platform browser path resolution
collector/                # per-browser collectors (chromium, safari, firefox)
collector/state.py        # shared ingest-state + reset-detection helpers
collector/run.py          # orchestrator, jittered loop, sync_state writer
web/app.py                # FastAPI search UI + /api/* endpoints
web/templates/index.html  # search + filter UI
web/templates/welcome.html# first-run onboarding flow
launchd/…plist.template   # macOS launchd agent template
schema.sql                # central DB schema + migrations
setup_app.py              # py2app config (macOS .app)
build_app.sh              # macOS .app + DMG build
build_windows.ps1         # Windows .exe build via PyInstaller
update_app.sh             # rebuild + replace /Applications/... + relaunch
tests/                    # pytest suite (run on every CI push)
```

## Uninstall

### macOS
1. Quit the menu-bar app (icon → Quit).
2. Drag **Browser History Gateway** from Applications to the Trash.
3. (Optional) Delete `~/.browser-history/` to remove the collected
   history DB and logs.

### Windows
1. Right-click the tray icon → Quit.
2. Delete `Browser-History-Gateway.exe`.
3. (Optional) Delete `%USERPROFILE%\.browser-history\` to remove the
   collected history DB and logs.

## License

**Personal use, no warranty.** Use this on your own machine. The author
makes no guarantees of correctness, suitability, or fitness for any
purpose. Your data stays on your computer; if it leaks because your disk
isn't encrypted, that's on you. Keep FileVault (macOS) / BitLocker
(Windows) on.

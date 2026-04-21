<!-- Created: 18:59 21-Apr-2026 -->
<!-- Updated: 20:32 21-Apr-2026 -->
<!-- Updated: 23:54 21-Apr-2026 -->
<!-- Updated: 23:58 21-Apr-2026 -->
<p align="center">
  <img src="assets/logo.png" alt="Browser History Gateway logo" width="160" />
</p>

<h1 align="center">Browser History Gateway</h1>

<p align="center">
  <em>Your private, local archive of every page you've ever visited —
  across every browser and profile on your Mac.</em>
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
  <a href="https://github.com/AntifragileTech/browser-history-gateway/releases/latest">
    <img src="https://img.shields.io/badge/Windows-coming%20soon-888?logo=windows&logoColor=white&style=for-the-badge" alt="Windows coming soon" />
  </a>
</p>

<p align="center">
  <sub>Don't know which Mac you have? <strong>Apple menu → About This Mac → Chip</strong>.
  Apple M1 / M2 / M3 / M4 = Apple Silicon. Anything with "Intel" = Intel.</sub>
</p>

---

A local macOS menu-bar app that aggregates browsing history from every
installed browser and profile into a single searchable SQLite database —
then lets you search across date, time, browser, profile, URL, and title
from a native in-app window.

- **Archive forever.** Chrome auto-expires history at 90 days. We don't.
- **Never misses anything.** Runs every 45–60 seconds *and* on file-change
  via FSEvents, so visits are captured within seconds of you making them.
- **Private.** Everything stays on your Mac. No cloud, no telemetry.

Supports: **Chrome** (all profiles, with your custom profile names),
**Brave**, **Arc**, **Edge**, **Safari**, **Firefox**.

---

## Install (the easy way)

1. Click the button above for your Mac's architecture, or grab the DMG
   directly:
   - **Apple Silicon** (M1/M2/M3/M4) →
     [Browser-History-Gateway-arm64.dmg](https://github.com/AntifragileTech/browser-history-gateway/releases/latest/download/Browser-History-Gateway-arm64.dmg)
   - **Intel Mac** →
     [Browser-History-Gateway-intel.dmg](https://github.com/AntifragileTech/browser-history-gateway/releases/latest/download/Browser-History-Gateway-intel.dmg)
2. Open the DMG, drag **Browser History Gateway** into **Applications**.
3. **Right-click** the app in Applications → **Open** (first time only; this
   is required for unsigned apps). Click **Open** in the Gatekeeper dialog.
4. The ⏱ icon appears in your menu bar.
5. Click ⏱ → **Check Permissions** — the app opens the Full Disk Access
   pane in System Settings. Toggle "Browser History Gateway" on.
6. Click ⏱ → **Quit** in the menu bar, then double-click the app to
   relaunch. FDA is now active.
7. Click ⏱ → **Open Search**. Your full browsing history appears in a
   native in-app window.

That's it. No terminal required. The app auto-discovers every browser
and profile, starts collecting, and keeps doing so forever.

## What you get

- **Menu-bar app** (⏱) with *Open Search*, *Run Collection Now*,
  *Check Permissions*, *Open Data Folder*, *Launch at Login…*, *Quit*.
- **Native in-app search window** — no external browser required.
  Filters by keyword (with hit highlighting), browser, profile, domain,
  and date. Quick-range presets: Today / Yesterday / This week / Last 7 /
  This month / Last 30 / last 3 full months / All time / custom.
- **Sync status bar** showing last-synced time, countdown to next sync,
  and Sync Now + Refresh buttons.
- **Serial-numbered rows**, descending from the most recent visit,
  continuing across pages.
- **Auto-reload** after every sync — new rows appear without you clicking
  anything.

## What's collected

- URL, page title, visit timestamp, browser, profile (with your friendly
  name, e.g. "Work" / "Personal"), and Chrome/Firefox transition type
  (link / typed / reload / …).
- Data location: `~/.browser-history/history.db` (SQLite, WAL-mode).
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
(default 45–60 s). File-change events via FSEvents trigger an additional
collection within ~5 s of any browser write.

## Developer setup (only if you want to build from source)

Skip this section if you're using the prebuilt DMG.

```bash
git clone https://github.com/<YOU>/browser-history-gateway.git
cd browser-history-gateway

./install.sh              # venv + deps + DB + one collection pass
./install.sh --agent      # also installs a launchd agent (no .app needed)

# OR build the menu-bar .app + DMG yourself:
./build_app.sh --dmg

# Update-in-place workflow:
./update_app.sh           # rebuild + replace /Applications/... + relaunch
```

### Project layout

```
app/menubar.py            # rumps menu-bar + WKWebView in-app window
collector/                # per-browser collectors (chromium, safari, firefox)
collector/state.py        # shared ingest-state + reset-detection helpers
collector/run.py          # orchestrator, jittered loop, sync_state writer
web/app.py                # FastAPI search UI + /api/sync-* endpoints
web/templates/index.html  # single-page UI with sticky header and countdown
launchd/…plist.template   # agent template substituted by install.sh
schema.sql                # central DB schema + migrations
setup_app.py              # py2app config for building the .app
build_app.sh              # .app + DMG build (with ad-hoc codesigning)
update_app.sh             # rebuild + replace /Applications + relaunch
releases/                 # prebuilt DMG committed for direct download
```

## Windows — status: planned

A Windows build (`.exe` installer) is planned and tracked separately
because the entire menu-bar + in-app window layer of the current code
is macOS-only (`rumps`, `WKWebView`, `FSEvents`). To ship on Windows
honestly we'd need to swap in:

- `pystray` for the system-tray icon (instead of `rumps`)
- `pywebview` / Edge WebView2 for the in-app window (instead of `WKWebView`)
- `watchdog`'s `ReadDirectoryChangesW` backend (already bundled, no change)
- Windows browser paths: `%LOCALAPPDATA%\Google\Chrome\User Data\…`,
  `%LOCALAPPDATA%\Microsoft\Edge\User Data\…`,
  `%APPDATA%\Mozilla\Firefox\Profiles\…`, etc.
- Build with **PyInstaller** (one-file `.exe`) on a `windows-latest`
  GitHub Actions runner.

The collector core (SQLite, URL parsing, reset-detection) already
works cross-platform. The feature gap is the UI wrapper, which needs
roughly half a day of focused work. Ping on an issue once the Mac
flow is stable and the Windows build will follow.

## Uninstall

1. Quit the menu-bar app (⏱ → Quit).
2. Drag **Browser History Gateway** from Applications to the Trash.
3. (Optional) Delete `~/.browser-history/` to remove the collected
   history DB and logs.

## License

Personal use. No warranty — this is a local-only archival tool; keep
your Mac's disk encrypted so the collected DB stays private.

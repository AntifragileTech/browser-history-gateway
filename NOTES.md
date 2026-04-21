<!-- Created: 00:43 22-Apr-2026 -->
# NOTES — Browser History Gateway

---
## Session: 18:57 21-Apr-2026 — 00:43 22-Apr-2026

### What was done
- Bootstrapped the entire project from scratch — Python collector + FastAPI
  web UI + rumps menu-bar `.app` + py2app packaging + DMG + GitHub Actions.
- Pushed to private repo: https://github.com/AntifragileTech/browser-history-gateway
- Wired up CI matrix build on `macos-13` + `macos-14` → native Intel & arm64
  DMGs published to a rolling "latest" GitHub Release on every main push.
- Fixed: FDA propagation, Safari WAL-mode backup+journal_mode, launch error
  from py2app (anyio/_backends, uvloop → asyncio, WebKit bundling), main
  thread UI crash in rumps, first-launch "Internal Server Error", migration
  guards for schema changes.
- Added: Friendly Chrome profile names from `Local State`, dynamic Chromium
  discovery (17 known + filesystem scan), FSEvents watcher, 45–60 s jittered
  sync + sync_state.json, /api/sync-status + /api/sync-now endpoints, live
  countdown + Sync Now + Refresh buttons, auto-reload on sync advancement,
  match highlighting, URL wrap-when-searching, serial number column,
  sticky header, quick-range presets (today/yesterday/this week/last 7/
  this month/last 30/last 3 full months/all time), pagination, ad-hoc
  code signing, logo/.icns/menu-bar template PNGs, README download badges.

### What was learned
- py2app on Intel bundles x86_64-only C extensions even if the stub is
  universal → Apple Silicon Macs need native build or forced Rosetta.
- macOS TCC identifies unsigned apps by (bundle-id + path + executable
  hash). Ad-hoc codesign gives a stable identity helpful for FDA but does
  NOT eliminate Gatekeeper's "unidentified developer" dialog on first
  launch of each rebuild.
- Chrome's `~/Library/Application Support/Google/Chrome/Local State` has
  `profile.info_cache.<folder>.name` with user-set profile labels.
- Safari's History.db is FDA-protected; its WAL-mode means naive
  `shutil.copy` loses data → must use SQLite online backup API + then
  `PRAGMA journal_mode=DELETE` to produce a standalone copy that Python's
  older bundled sqlite3 can open.
- macOS 15 killed the right-click→Open Gatekeeper bypass — user must now
  go to System Settings → Privacy & Security → "Open Anyway".
- `gh auth` via device flow works for device-less pushes; the token needs
  the `workflow` scope to push anything under `.github/workflows/`.

### Key files modified
- `app/menubar.py`              — rumps app, WKWebView, FSEvents, onboarding hooks
- `collector/chromium.py`       — dynamic browser discovery + display_name
- `collector/safari.py`         — WAL-safe snapshot + reset detection
- `collector/firefox.py`        — reset detection + display name
- `collector/run.py`            — migrate_db, jittered loop, sync_state writer
- `collector/state.py`          — reset+offset helper module
- `web/app.py`                  — filters, sync-*, empty-state, highlight
- `web/templates/index.html`    — full single-page UI
- `schema.sql`                  — central DB schema + migrations
- `setup_app.py`, `build_app.sh`, `update_app.sh`, `install.sh`
- `.github/workflows/build.yml` — matrix build & rolling Release
- `assets/make_icons.py`, `assets/logo.png`, `assets/AppIcon.icns`, template PNGs
- `README.md`                   — download badges + Windows roadmap note

### Handoff context
- NEXT SESSION: "Full green light" inspection. User wants an audit with
  a fresh eye covering edge cases around hardware, browser types, and
  sharing-readiness. See HANDOFF.md for the full checklist.
- Apple Silicon DMG is being built right now by CI; the user will test
  on their Apple Silicon Mac once the run completes (~5 min from save).
- Two items explicitly deferred: proper onboarding window, Windows build.

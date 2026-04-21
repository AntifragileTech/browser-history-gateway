<!-- Created: 00:43 22-Apr-2026 -->
# Handoff — Browser History Gateway

## Current status (22-Apr-2026 00:43)

- **Repo**: https://github.com/AntifragileTech/browser-history-gateway (**private**)
- **Latest commit on main**: `e4fb35b` — "Fix Internal Server Error on first launch + dynamic browser discovery"
- **CI**: GitHub Actions building `Intel` + `Apple Silicon` DMGs on every push
  to main. Two runs queued at save time — check https://github.com/AntifragileTech/browser-history-gateway/actions
- **Direct download URLs** (served from GitHub Releases "latest" rolling prerelease):
  - Apple Silicon: `.../releases/latest/download/Browser-History-Gateway-arm64.dmg`
  - Intel:        `.../releases/latest/download/Browser-History-Gateway-intel.dmg`
- **Local `/Applications/Browser History Gateway.app`**: last built 21:49 on this
  Intel iMac, runs fine locally. Has new logo, sticky header, serial numbers,
  sync countdown, Sync Now + Refresh, auto-reload on sync, friendly profile
  names (e.g. "AntiFragile", "NewsVenue" from Chrome's `Local State`).
- **Central DB**: `~/.browser-history/history.db` — 28,610+ visits across
  chrome/Default, chrome/Profile 1, safari/Default.

## What was shipped this session

- One-command bootstrap: `install.sh [--agent]`, `update_app.sh`, `build_app.sh --dmg`
- Menu-bar `.app` (rumps + PyObjC WKWebView in-app window, no external browser needed)
- Collector: Chromium / Safari / Firefox with reset-detection + offset bumping;
  URLs, titles, transitions; 45–60 s jittered sync + FSEvents watcher (~5 s debounce)
- Web UI: filters (browser, profile, domain, q, date range), quick-range presets
  (today/yesterday/this-week/7/this-month/30/last-3-months/all time), pagination,
  serial column, match highlighting, auto-reload on sync advancement
- `/api/sync-status` + `/api/sync-now` endpoints, countdown pill, Sync Now + Refresh
- Schema migrations (`source_id_offset`, `display_name`) via idempotent `migrate_db()`
- Dynamic Chromium discovery: curated list of 17 browsers + fallback scan
  of `~/Library/Application Support/` for any dir containing a `Local State` file
- Fix: DB auto-init at app startup (kills the "Internal Server Error" on fresh Mac)
- Empty-state "Welcome 👋" card in the UI when DB has 0 visits
- Ad-hoc codesigning (stable TCC identity across rebuilds)
- GitHub Actions matrix build (macos-13 + macos-14) → rolling "latest" Release
- README with shields.io download badges for arm64 + Intel, honest Windows note

## Known limitations + what the user flagged for next session

### User's explicit "inspect with a fresh eye" list for next session
> "I want you to check and give me a full green light after inspection"

Look at every file with these concerns in mind:

1. **Onboarding UX is still rough.** Menu-bar dialog is too subtle — user
   doesn't know what's happening on first launch. Needs a dedicated welcome
   window with:
   - "Discovering browsers..." step (live-list detected browsers)
   - Embedded FDA grant button that detects when the grant lands (no manual quit)
   - "Running first collection..." progress
   - "Done — open search" handoff

2. **First-run "Internal Server Error"**: should be gone thanks to this
   session's fix (init_db at startup + self-healing _db()), but REGRESSION-TEST
   on a fresh Mac. That's the Apple Silicon Mac's upcoming test.

3. **Hardware edge cases to verify on the Apple Silicon Mac**:
   - arm64 DMG launches (was the big blocker — universal launcher + native
     arm64 extensions should fix)
   - App icon renders in Dock, Finder, Cmd-Tab, menu bar
   - Menu bar icon adapts to dark mode (template PNG was set up but verify)
   - FSEvents watcher actually fires on a real browsing event (we only
     tested via scheduled interval, not event trigger, end-to-end on a
     non-dev Mac)

4. **Browser-type edge cases**: we discover Chromium-family via `Local State`,
   but some concerns:
   - Firefox dev editions (Nightly, Developer Edition) live in different
     profile dirs — verify `firefox.py` discovery picks them up
   - Opera stores profiles oddly — may need per-browser rules
   - A user with ZERO browsers installed: does the app still start cleanly?
   - A user with Chrome but NO profiles (fresh install): does the collector
     handle empty `info_cache`?

5. **Sync correctness edge cases**:
   - Source DB reset during a sync (race): reset-detection logic hasn't
     been tested against a real Chrome profile wipe mid-collection
   - Very large Chrome history on first-ever sync (1M+ rows): does
     the single INSERT OR IGNORE batch blow memory? Should page.
   - Time-zone handling: `visited_at` is stored as unix epoch UTC,
     but UI filters parse `YYYY-MM-DD` via `datetime.timestamp()`
     which uses local TZ. Verify date filters work around DST boundaries.

6. **Windows roadmap** (mentioned in README): not started. User has Windows
   friends. Needs:
   - `pystray` for system tray (replaces rumps)
   - `pywebview` or WebView2 for in-app window (replaces WKWebView)
   - PyInstaller build on `windows-latest` runner
   - Windows browser paths (`%LOCALAPPDATA%\Google\Chrome\User Data\...`)

7. **Security / privacy hygiene**:
   - Repo is private but code should still avoid any personal-identifying
     strings. Re-audit with `rg -i "antifragile|newsvenue|ghugharwal|..." .`
   - DB contains the user's entire browsing history — not encrypted.
     README notes this but could be stronger (e.g., recommend
     FileVault, or ship with SQLCipher).
   - Web UI binds to 127.0.0.1 only (good) but has no CSRF protection on
     `/api/sync-now` (POST). Local-only so low risk but worth noting.

8. **Dev polish**:
   - No tests. At minimum: unit tests for `collector/state.py` reset
     logic, for `_highlight()` XSS safety, for `_parse_date()` TZ edges.
   - `collector/run.py` has slightly sloppy arg parsing around `--loop`.
   - `build_app.sh` hardcodes py2app 0.28.8; check for compatibility with
     Python 3.11 on the Apple Silicon runner (macos-14) before first build.

## Next-session DoD ("full green light")

- [ ] Audit every file, confirm no personal data or hardcoded paths remain
- [ ] Test-install on the Apple Silicon Mac → full flow works without terminal
- [ ] Proper onboarding window shipped
- [ ] Basic unit tests added (at least reset-detection + highlight XSS)
- [ ] Windows scaffold committed (even if not building yet), tracked as WIP

## Environment state

- macOS: Intel iMac running macOS 15
- Python: `/usr/bin/python3` (universal2, 3.9.6 via Xcode CLT) — also a
  `.venv/` at Python 3.9, `.venv-build/` same
- `gh` CLI: `~/.local/bin/gh` 2.63.2 (no Homebrew needed)
- Git user: `antifragiletech` / `antifragiletech@gmail.com` (set global)
- No uncommitted changes at save time
- Full Disk Access granted to: Claude.app, /Applications/Browser History Gateway.app

## Gotchas to remember

1. **Each `./update_app.sh` invalidates macOS Gatekeeper for the new bundle.**
   The first launch of every rebuilt .app needs "Open Anyway" in System Settings
   → Privacy & Security. Ad-hoc signing helps FDA persist but NOT Gatekeeper.
2. **CI runs on `macos-13` (Intel) and `macos-14` (Apple Silicon)** — each
   runner produces a NATIVE build. Don't conflate with the old unified build.
3. **FDA must be re-granted for each new .app binary** if the ad-hoc signature
   hash drifts (it does on every rebuild). This is the biggest friction point.
   Apple Developer ID ($99/yr) + notarization solves this completely.
4. **"Internal Server Error" on first Mac launch is fixed** by commit `e4fb35b`
   — but regression-test anyway.

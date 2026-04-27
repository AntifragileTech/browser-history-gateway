# Created: 18:59 21-Apr-2026
# Updated: 20:17 21-Apr-2026
# Updated: 20:19 21-Apr-2026
# Updated: 20:22 21-Apr-2026
# Updated: 20:26 21-Apr-2026
# Updated: 20:49 21-Apr-2026
# Updated: 21:32 21-Apr-2026
# Updated: 21:55 27-Apr-2026
"""Local search UI + onboarding for the browser-history DB.

Binds to 127.0.0.1 only — never exposed beyond the laptop.
"""
from __future__ import annotations

import html
import json
import math
import re
import socket
import sqlite3
import sys
import threading
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from collector import paths as browser_paths
from collector import run as collector_run

DB_PATH = Path("~/.browser-history/history.db").expanduser()
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Browser History Gateway")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Default port. The menubar may pick a different one if 8765 is taken;
# `pick_open_port` writes the chosen one to ~/.browser-history/port so the
# WKWebView / pywebview window can read it back without a hardcode.
DEFAULT_PORT = 8765
PORT_FILE = Path("~/.browser-history/port").expanduser()


# -- helpers --------------------------------------------------------------


def _db() -> sqlite3.Connection:
    # If the DB file does not yet exist (very first launch, before the
    # collector has had a chance to run), create it with the full schema
    # so every endpoint gets an empty-but-valid DB to read from. Beats
    # raising 500 at the user on the very first page load.
    if not DB_PATH.exists():
        try:
            collector_run.init_db()
        except Exception:
            pass
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _local_tz() -> timezone:
    """Return the OS-level local timezone as a fixed offset.

    `datetime.now().astimezone().tzinfo` is the standard way to ask Python
    for the current local zone; doing it once per call also picks up DST
    changes in long-running processes."""
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_date(s: Optional[str], end_of_day: bool = False) -> Optional[int]:
    """Parse 'YYYY-MM-DD' into unix epoch seconds, anchored in local TZ.

    Explicitly attaches the local tzinfo BEFORE converting to a unix
    timestamp. The naive form (`datetime.strptime(...).timestamp()`) is
    DST-ambiguous: on spring-forward day, 02:00-02:59 doesn't exist
    locally, and the conversion is platform-dependent.
    """
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        # Attach the current local tz before .timestamp() to avoid
        # ambiguity around DST transitions.
        dt = dt.replace(tzinfo=_local_tz())
        return int(dt.timestamp())
    except ValueError:
        return None


def _highlight(text: Optional[str], query: str) -> str:
    """HTML-escape `text` and wrap every case-insensitive occurrence of
    `query` in <mark>. Returns a safe HTML string for Jinja `|safe`.
    When `query` is empty, just escapes.
    """
    if not text:
        return ""
    if not query:
        return html.escape(text)
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    out: list[str] = []
    last = 0
    for m in pattern.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        out.append("<mark>")
        out.append(html.escape(m.group(0)))
        out.append("</mark>")
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def _month_presets(today: date, count: int = 3) -> list[dict]:
    """Return the last `count` fully-elapsed months as preset definitions.

    For today=2026-04-21 with count=3 -> March 2026, February 2026, January 2026.
    Each entry: {label, date_from, date_to}. Usable as direct href params.
    """
    presets: list[dict] = []
    # Start with the month BEFORE the current one (last fully-elapsed month).
    y, m = today.year, today.month
    for _ in range(count):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        first = date(y, m, 1)
        last = date(y, m, monthrange(y, m)[1])
        presets.append({
            "label": first.strftime("%b %Y"),
            "date_from": first.strftime("%Y-%m-%d"),
            "date_to": last.strftime("%Y-%m-%d"),
        })
    return presets


def _is_local_origin(request: Request) -> bool:
    """Belt-and-suspenders CSRF check: simple-request POSTs from a malicious
    page running in any browser on this Mac would arrive without CORS
    preflight, but with a non-localhost Origin / Referer header. Reject
    anything that doesn't look like our own UI.
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    # Native pywebview / WKWebView fetch() may omit Origin entirely; allow
    # that case (we're only here because uvicorn is bound to 127.0.0.1).
    if not origin and not referer:
        return True
    candidate = origin or referer or ""
    return any(host in candidate for host in ("127.0.0.1", "localhost"))


# -- pages ----------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    browser: str = "",
    profile: str = "",
    domain: str = "",
    date_from: str = "",
    date_to: str = "",
    scope: str = "",  # "all" = disable the default last-30-days window
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=10, le=5000),
):
    # Default behavior: on a bare landing with no dates and no explicit
    # scope=all, show the last 30 days (~the most useful window for recall).
    today = date.today()
    default_applied = False
    if not date_from and not date_to and scope != "all":
        date_from = (today - timedelta(days=29)).strftime("%Y-%m-%d")
        date_to = today.strftime("%Y-%m-%d")
        default_applied = True

    with _db() as db:
        browsers = db.execute(
            "SELECT DISTINCT name FROM browsers ORDER BY name"
        ).fetchall()
        # Pull both the stable folder name and the friendly display name
        # so the filter dropdown can show e.g. "Work (Default)".
        profiles = db.execute(
            """
            SELECT profile, COALESCE(NULLIF(display_name, ''), profile) AS label
            FROM browsers
            GROUP BY profile
            ORDER BY LOWER(label)
            """
        ).fetchall()

        where = []
        params: list = []
        if q:
            where.append("(v.url LIKE ? OR v.title LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
        if browser:
            where.append("b.name = ?")
            params.append(browser)
        if profile:
            where.append("b.profile = ?")
            params.append(profile)
        if domain:
            where.append("v.domain = ?")
            params.append(domain.lower())
        ts_from = _parse_date(date_from)
        ts_to = _parse_date(date_to, end_of_day=True)
        if ts_from:
            where.append("v.visited_at >= ?")
            params.append(ts_from)
        if ts_to:
            where.append("v.visited_at <= ?")
            params.append(ts_to)

        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        count_sql = f"SELECT COUNT(*) FROM visits v JOIN browsers b ON b.id = v.browser_id {where_clause}"
        total = db.execute(count_sql, params).fetchone()[0]
        # Absolute DB emptiness (no rows at all) -> first-launch welcome card.
        total_in_db = db.execute("SELECT COUNT(*) FROM visits").fetchone()[0]

        total_pages = max(1, math.ceil(total / page_size)) if total else 1
        # Clamp page so we never offset past the end.
        page = min(page, total_pages)
        offset = (page - 1) * page_size

        sql = f"""
            SELECT b.name AS browser,
                   b.profile,
                   COALESCE(NULLIF(b.display_name, ''), b.profile) AS profile_display,
                   v.url, v.domain, v.title, v.visited_at, v.transition
            FROM visits v
            JOIN browsers b ON b.id = v.browser_id
            {where_clause}
            ORDER BY v.visited_at DESC
            LIMIT ? OFFSET ?
        """
        rows = db.execute(sql, (*params, page_size, offset)).fetchall()

    # Serial numbers are absolute within the current filtered set. Because
    # results are ordered `visited_at DESC`, row #1 is the MOST RECENT
    # match, row #N is the oldest. Page 1 shows 1..page_size, page 2
    # shows page_size+1..2*page_size, etc. This makes the serial number
    # stable for a given filter regardless of pagination.
    results = [
        {
            "serial": offset + i + 1,
            "browser": r["browser"],
            "profile": r["profile"],
            "profile_display": r["profile_display"],
            "url": r["url"],
            "url_html": _highlight(r["url"], q),
            "domain": r["domain"],
            "domain_html": _highlight(r["domain"], q),
            "title": r["title"],
            "title_html": _highlight(r["title"], q),
            "visited_at": datetime.fromtimestamp(r["visited_at"]).strftime("%Y-%m-%d %H:%M:%S"),
            "transition": r["transition"],
        }
        for i, r in enumerate(rows)
    ]

    # Base query string preserves all filters but drops `page` so the
    # template can append any page number without dedup headaches.
    base_params = {
        "q": q, "browser": browser, "profile": profile, "domain": domain,
        "date_from": date_from, "date_to": date_to, "page_size": page_size,
        "scope": scope,
    }
    base_qs = urlencode({k: v for k, v in base_params.items() if v})

    range_start = offset + 1 if results else 0
    range_end = offset + len(results)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": results,
            "total": total,
            "shown": len(results),
            "page": page,
            "total_pages": total_pages,
            "page_size": page_size,
            "range_start": range_start,
            "range_end": range_end,
            "base_qs": base_qs,
            "browsers": [r["name"] for r in browsers],
            "profiles": [{"value": r["profile"], "label": r["label"]} for r in profiles],
            "month_presets": _month_presets(today),
            "default_applied": default_applied,
            "total_in_db": total_in_db,
            "q": q, "browser": browser, "profile": profile, "domain": domain,
            "date_from": date_from, "date_to": date_to, "scope": scope,
        },
    )


@app.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request):
    """First-run onboarding window. Shows discovered browsers, FDA grant
    status (macOS), and first-sync progress. Auto-redirects to / once
    the first sync completes successfully.
    """
    return templates.TemplateResponse(
        "welcome.html",
        {"request": request, "platform": sys.platform},
    )


# -- APIs -----------------------------------------------------------------


@app.get("/api/sync-status")
def sync_status():
    """Expose last / next sync timestamps for the UI countdown."""
    state: dict = {"last_sync_at": 0, "next_sync_at": 0, "interval_s": 0}
    if collector_run.SYNC_STATE_PATH.exists():
        try:
            state.update(json.loads(collector_run.SYNC_STATE_PATH.read_text()))
        except Exception:
            pass
    cfg = collector_run.load_config()
    state["interval_min_s"] = cfg.get(
        "sync_interval_min_s", collector_run.DEFAULT_INTERVAL_MIN_S
    )
    state["interval_max_s"] = cfg.get(
        "sync_interval_max_s", collector_run.DEFAULT_INTERVAL_MAX_S
    )
    state["server_time"] = int(time.time())
    return JSONResponse(state)


# Serialize Sync-Now requests so we never run two collections in parallel.
_sync_lock = threading.Lock()
_sync_in_progress = False


@app.post("/api/sync-now")
def sync_now(request: Request):
    """Kick off a collection pass on demand. Non-blocking: returns
    immediately with {queued: true} and the collector runs in a thread.
    Subsequent calls while a run is in progress return {busy: true}.
    """
    if not _is_local_origin(request):
        # CORS would block a cross-origin response anyway, but double
        # up: any malicious page that tried to abuse this endpoint
        # sends an Origin header we can verify and reject.
        raise HTTPException(status_code=403, detail="forbidden")
    global _sync_in_progress

    def _run():
        global _sync_in_progress
        try:
            collector_run.run_once()
        finally:
            with _sync_lock:
                _sync_in_progress = False

    with _sync_lock:
        if _sync_in_progress:
            return JSONResponse({"busy": True})
        _sync_in_progress = True
    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"queued": True})


@app.get("/api/onboarding-status")
def onboarding_status():
    """Drives the welcome window. Returns:
      platform     - 'darwin' | 'win32' | 'linux'
      fda_required - bool, True only on macOS
      fda_granted  - bool, only meaningful when fda_required
      browsers     - [{name, profiles: [str], path: str}]
      visits       - total visits collected so far
      first_sync_done - bool (visits > 0)
    """
    # Lazy import to avoid pulling collector modules on Linux dev where
    # they have nothing to find.
    from collector import chromium, firefox

    fda_required = sys.platform == "darwin"
    fda_granted = True
    if fda_required:
        # Probe Safari readability — same check the menubar uses. We don't
        # raise; we just report ungranted to the UI.
        safari_db = browser_paths.safari_history_path()
        if safari_db and safari_db.exists():
            try:
                with open(safari_db, "rb") as f:
                    f.read(1)
            except (PermissionError, OSError):
                fda_granted = False

    discovered: list[dict] = []
    # Chromium-family
    for browser_name, root in chromium._discover_browsers():
        profile_names = [name for name, _ in chromium._discover_profiles(browser_name, root)]
        if profile_names:
            discovered.append(
                {"name": browser_name, "profiles": profile_names, "path": str(root)}
            )
    # Firefox
    ff_profiles = [name for name, _ in firefox._discover_profiles()]
    if ff_profiles:
        discovered.append(
            {"name": "firefox", "profiles": ff_profiles,
             "path": str(browser_paths.firefox_profiles_root())}
        )
    # Safari (macOS only)
    if fda_required and browser_paths.safari_history_path() and browser_paths.safari_history_path().exists():
        discovered.append(
            {"name": "safari", "profiles": ["Default"],
             "path": str(browser_paths.safari_history_path().parent)}
        )

    visits = 0
    try:
        with _db() as db:
            visits = db.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    except Exception:
        pass

    return JSONResponse({
        "platform": sys.platform,
        "fda_required": fda_required,
        "fda_granted": fda_granted,
        "browsers": discovered,
        "visits": visits,
        "first_sync_done": visits > 0,
    })


@app.get("/api/stats")
def stats():
    with _db() as db:
        total = db.execute("SELECT COUNT(*) AS c FROM visits").fetchone()["c"]
        by_browser = db.execute(
            """
            SELECT b.name, b.profile, COUNT(*) AS visits,
                   MIN(v.visited_at) AS first, MAX(v.visited_at) AS last
            FROM visits v JOIN browsers b ON b.id = v.browser_id
            GROUP BY b.id
            ORDER BY visits DESC
            """
        ).fetchall()
        top_domains = db.execute(
            """
            SELECT domain, COUNT(*) AS visits FROM visits
            GROUP BY domain ORDER BY visits DESC LIMIT 20
            """
        ).fetchall()
    return JSONResponse({
        "total_visits": total,
        "by_browser": [dict(r) for r in by_browser],
        "top_domains": [dict(r) for r in top_domains],
    })


# -- runtime --------------------------------------------------------------


def pick_open_port(preferred: int = DEFAULT_PORT, attempts: int = 30) -> int:
    """Return a TCP port we can actually bind on 127.0.0.1.

    Tries `preferred` first, then `preferred+1` ... `preferred+attempts-1`,
    finally falling back to an ephemeral OS-assigned port. Without this,
    a stale instance / dev server holding 8765 silently kills the app's
    UI (uvicorn raises and the menubar logs but keeps running).
    """
    for offset in range(attempts):
        port = preferred + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    # Last resort: ask the OS for any free port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_port(port: int) -> None:
    """Persist the chosen port so the menubar window can read it back."""
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        PORT_FILE.write_text(str(port))
    except Exception:
        pass


def read_port() -> int:
    """Return the previously-chosen port if any, else DEFAULT_PORT."""
    try:
        return int(PORT_FILE.read_text().strip())
    except Exception:
        return DEFAULT_PORT


def main() -> None:
    port = pick_open_port()
    write_port(port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info",
                loop="asyncio", http="h11")


if __name__ == "__main__":
    main()

# Created: 18:59 21-Apr-2026
# Updated: 20:17 21-Apr-2026
# Updated: 20:19 21-Apr-2026
# Updated: 20:22 21-Apr-2026
# Updated: 20:26 21-Apr-2026
# Updated: 20:49 21-Apr-2026
# Updated: 21:32 21-Apr-2026
"""Local search UI for the browser-history DB.

Binds to 127.0.0.1 only — never exposed beyond the laptop.
"""
from __future__ import annotations

import html
import json
import math
import re
import sqlite3
import threading
import time
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from collector import run as collector_run

DB_PATH = Path("~/.browser-history/history.db").expanduser()
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Browser History Gateway")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_date(s: Optional[str], end_of_day: bool = False) -> Optional[int]:
    """Parse 'YYYY-MM-DD' into unix epoch seconds in local time."""
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
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

    For today=2026-04-21 with count=3 → March 2026, February 2026, January 2026.
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
    # scope=all, show the last 30 days (≈ the most useful window for recall).
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
            "q": q, "browser": browser, "profile": profile, "domain": domain,
            "date_from": date_from, "date_to": date_to, "scope": scope,
        },
    )


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
def sync_now():
    """Kick off a collection pass on demand. Non-blocking: returns
    immediately with {queued: true} and the collector runs in a thread.
    Subsequent calls while a run is in progress return {busy: true}.
    """
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


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()

# Created: 18:59 21-Apr-2026
# Updated: 19:53 21-Apr-2026
# Updated: 19:55 21-Apr-2026
# Updated: 21:30 21-Apr-2026
"""Collector for Safari.

Safari stores history in ~/Library/Safari/History.db. The directory is
protected by macOS Full Disk Access — if the running process lacks FDA,
the file will appear to exist but reads raise PermissionError / OperationalError.

Tables of interest:
  history_items  (id, url, domain_expansion, visit_count)
  history_visits (id, history_item, visit_time, title, redirect_source,
                  redirect_destination, origin, load_successful, http_non_get)

Timestamps: Cocoa reference date = seconds since 2001-01-01 00:00:00 UTC.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from . import state

log = logging.getLogger(__name__)

SAFARI_HISTORY = Path("~/Library/Safari/History.db").expanduser()
# Cocoa reference date (2001-01-01) to unix epoch (1970-01-01) in seconds.
COCOA_EPOCH_OFFSET = 978307200


def cocoa_time_to_unix(cocoa_seconds: float) -> int:
    if not cocoa_seconds or cocoa_seconds <= 0:
        return 0
    return int(cocoa_seconds + COCOA_EPOCH_OFFSET)


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _copy_db(src: Path, dst_dir: Path) -> Path:
    """Snapshot Safari's live History.db using SQLite's online backup API.

    `shutil.copy2` is unreliable here because Safari runs in WAL mode: the
    main .db file can be incomplete without its -wal/-shm sidecars, and
    naming the sidecars correctly after copy is fragile. The backup API
    produces a fully self-contained snapshot regardless of WAL state.
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "Safari-History.sqlite"
    if dst.exists():
        dst.unlink()
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
            # Backup inherits the source's WAL journal mode. Python's sqlite3
            # (older bundled lib) can't open a WAL-mode file without its
            # -wal/-shm sidecars, so flip the copy to rollback-journal mode.
            dst_conn.execute("PRAGMA journal_mode=DELETE")
            dst_conn.commit()
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return dst


def _read_visits(db_path: Path, since_source_id: int) -> Iterator[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT v.id           AS visit_id,
                   i.url          AS url,
                   v.title        AS title,
                   v.visit_time   AS visit_time,
                   v.origin       AS origin
            FROM history_visits v
            JOIN history_items i ON i.id = v.history_item
            WHERE v.id > ?
            ORDER BY v.id ASC
            """,
            (since_source_id,),
        )
        for row in cur:
            yield {
                "source_visit_id": row["visit_id"],
                "url": row["url"],
                "title": row["title"] or "",
                "visited_at": cocoa_time_to_unix(row["visit_time"]),
                # Safari doesn't expose a rich transition type like Chromium.
                # origin: 0 = direct, 1 = via redirect.
                "transition": "redirect" if row["origin"] == 1 else "link",
                "domain": _domain_of(row["url"]),
            }
    finally:
        conn.close()


def collect(central_db: sqlite3.Connection, tmp_dir: Path) -> dict[str, int]:
    if not SAFARI_HISTORY.exists():
        return {}
    now = int(time.time())
    try:
        browser_id = state.ensure_browser(central_db, "safari", "Default")
        last_raw, offset = state.get_state(central_db, browser_id)
        copied = _copy_db(SAFARI_HISTORY, tmp_dir)
    except PermissionError:
        log.warning("safari: permission denied — grant Full Disk Access to terminal/python3")
        return {"safari:Default": 0}
    except Exception as e:
        log.warning("safari: copy failed: %s", e)
        return {"safari:Default": 0}

    # Detect source DB reset (new Safari install, reset history, etc.).
    try:
        src_max = state.source_max_id(copied, "history_visits")
    except Exception:
        src_max = last_raw  # don't trigger a spurious reset on read error
    last_raw, offset = state.detect_and_apply_reset(src_max, last_raw, offset, "safari/Default")

    rows_to_insert = []
    max_raw = last_raw
    try:
        for v in _read_visits(copied, last_raw):
            effective_id = v["source_visit_id"] + offset
            rows_to_insert.append((
                browser_id, v["url"], v["domain"], v["title"],
                v["visited_at"], v["transition"], effective_id, now,
            ))
            if v["source_visit_id"] > max_raw:
                max_raw = v["source_visit_id"]
    except sqlite3.OperationalError as e:
        log.warning("safari: read failed (FDA?): %s", e)
        return {"safari:Default": 0}
    finally:
        copied.unlink(missing_ok=True)

    if rows_to_insert:
        central_db.executemany(
            """
            INSERT OR IGNORE INTO visits
            (browser_id, url, domain, title, visited_at, transition,
             source_visit_id, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )
    state.save_state(central_db, browser_id, max_raw, offset, now)
    central_db.commit()
    log.info("safari/Default: %d new visits", len(rows_to_insert))
    return {"safari:Default": len(rows_to_insert)}

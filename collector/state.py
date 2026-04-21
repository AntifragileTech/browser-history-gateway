# Created: 21:28 21-Apr-2026
"""Per-browser ingest state helpers — shared by every source collector.

Handles the "source DB reset" case: if the source's MAX(id) suddenly
falls below our cursor (user re-created a profile, cleared everything,
etc), we bump `source_id_offset` by the pre-reset cursor value and
rescan from 0. New rows get effective_source_visit_id = raw_id + offset,
which never collides with pre-reset entries in the UNIQUE constraint.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)


def ensure_browser(db: sqlite3.Connection, name: str, profile: str) -> int:
    db.execute(
        "INSERT OR IGNORE INTO browsers (name, profile) VALUES (?, ?)", (name, profile)
    )
    row = db.execute(
        "SELECT id FROM browsers WHERE name = ? AND profile = ?", (name, profile)
    ).fetchone()
    return int(row[0])


def set_display_name(
    db: sqlite3.Connection, browser_id: int, display_name: str | None
) -> None:
    """Refresh the user-friendly profile label. Called each sync pass so
    renames in the browser show up promptly in our UI."""
    if not display_name:
        return
    db.execute(
        "UPDATE browsers SET display_name = ? WHERE id = ?",
        (display_name, browser_id),
    )


def get_state(db: sqlite3.Connection, browser_id: int) -> tuple[int, int]:
    """Return (last_raw_source_id, source_id_offset) for a browser."""
    row = db.execute(
        "SELECT last_source_visit_id, source_id_offset FROM ingest_state WHERE browser_id = ?",
        (browser_id,),
    ).fetchone()
    if not row:
        return (0, 0)
    return (int(row[0]), int(row[1]))


def save_state(
    db: sqlite3.Connection, browser_id: int, last_raw_id: int, offset: int, now: int
) -> None:
    db.execute(
        """
        INSERT INTO ingest_state (browser_id, last_source_visit_id, source_id_offset, last_run_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(browser_id) DO UPDATE SET
          last_source_visit_id = excluded.last_source_visit_id,
          source_id_offset = excluded.source_id_offset,
          last_run_at = excluded.last_run_at
        """,
        (browser_id, last_raw_id, offset, now),
    )


def source_max_id(db_path: Path, table: str, id_col: str = "id") -> int:
    """Return MAX(id) from a source DB's visits-equivalent table, or 0."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(f"SELECT IFNULL(MAX({id_col}), 0) FROM {table}").fetchone()
        return int(row[0])
    finally:
        conn.close()


def detect_and_apply_reset(
    source_max: int, last_raw_id: int, offset: int, label: str
) -> tuple[int, int]:
    """If the source DB's max id has fallen below our cursor, this is a
    profile reset. Return adjusted (last_raw_id, offset) for the new
    generation so the next read starts at 0 and new rows get a source
    id space that doesn't collide with pre-reset rows.
    """
    if source_max < last_raw_id and last_raw_id > 0:
        new_offset = offset + last_raw_id
        log.warning(
            "%s: source DB reset (max=%d < cursor=%d); "
            "rescanning from 0 with offset %d",
            label, source_max, last_raw_id, new_offset,
        )
        return 0, new_offset
    return last_raw_id, offset

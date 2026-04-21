# Created: 18:59 21-Apr-2026
# Updated: 21:30 21-Apr-2026
"""Collector for Firefox.

Firefox stores places (history + bookmarks) at
  ~/Library/Application Support/Firefox/Profiles/<id>.<name>/places.sqlite

Tables:
  moz_places        (id, url, title, ...)
  moz_historyvisits (id, place_id, visit_date, visit_type, from_visit)

visit_date is microseconds since unix epoch (different from Chromium!).
visit_type: 1=LINK, 2=TYPED, 3=BOOKMARK, 4=EMBED, 5=REDIRECT_PERMANENT,
            6=REDIRECT_TEMPORARY, 7=DOWNLOAD, 8=FRAMED_LINK, 9=RELOAD
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

FIREFOX_ROOT = Path("~/Library/Application Support/Firefox/Profiles").expanduser()
VISIT_TYPES = {
    1: "link", 2: "typed", 3: "bookmark", 4: "embed",
    5: "redirect_permanent", 6: "redirect_temporary",
    7: "download", 8: "framed_link", 9: "reload",
}


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _discover_profiles() -> list[tuple[str, Path]]:
    if not FIREFOX_ROOT.exists():
        return []
    out: list[tuple[str, Path]] = []
    for child in sorted(FIREFOX_ROOT.iterdir()):
        places = child / "places.sqlite"
        if places.is_file():
            # profile dirs are named "<random>.<name>" — strip the random prefix.
            label = child.name.split(".", 1)[1] if "." in child.name else child.name
            out.append((label, places))
    return out


def _copy_db(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"Firefox-{src.parent.name}-places.sqlite"
    shutil.copy2(src, dst)
    return dst


def _read_visits(db_path: Path, since_source_id: int) -> Iterator[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT h.id          AS visit_id,
                   p.url         AS url,
                   p.title       AS title,
                   h.visit_date  AS visit_date,
                   h.visit_type  AS visit_type
            FROM moz_historyvisits h
            JOIN moz_places p ON p.id = h.place_id
            WHERE h.id > ?
            ORDER BY h.id ASC
            """,
            (since_source_id,),
        )
        for row in cur:
            yield {
                "source_visit_id": row["visit_id"],
                "url": row["url"],
                "title": row["title"] or "",
                "visited_at": int(row["visit_date"] / 1_000_000) if row["visit_date"] else 0,
                "transition": VISIT_TYPES.get(row["visit_type"], "unknown"),
                "domain": _domain_of(row["url"]),
            }
    finally:
        conn.close()


def collect(central_db: sqlite3.Connection, tmp_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    now = int(time.time())
    for profile_name, places in _discover_profiles():
        key = f"firefox:{profile_name}"
        try:
            browser_id = state.ensure_browser(central_db, "firefox", profile_name)
            last_raw, offset = state.get_state(central_db, browser_id)
            copied = _copy_db(places, tmp_dir)
            src_max = state.source_max_id(copied, "moz_historyvisits")
            last_raw, offset = state.detect_and_apply_reset(
                src_max, last_raw, offset, f"firefox/{profile_name}"
            )
            rows_to_insert = []
            max_raw = last_raw
            for v in _read_visits(copied, last_raw):
                effective_id = v["source_visit_id"] + offset
                rows_to_insert.append((
                    browser_id, v["url"], v["domain"], v["title"],
                    v["visited_at"], v["transition"], effective_id, now,
                ))
                if v["source_visit_id"] > max_raw:
                    max_raw = v["source_visit_id"]
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
            counts[key] = len(rows_to_insert)
            log.info("firefox/%s: %d new visits", profile_name, len(rows_to_insert))
            copied.unlink(missing_ok=True)
        except Exception as e:
            log.exception("firefox/%s: %s", profile_name, e)
            counts[key] = 0
    return counts

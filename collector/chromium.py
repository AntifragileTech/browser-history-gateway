# Created: 18:59 21-Apr-2026
# Updated: 21:29 21-Apr-2026
# Updated: 21:47 21-Apr-2026
"""Collector for Chromium-family browsers: Chrome, Brave, Arc, Edge.

All use the same SQLite history schema. Timestamps are microseconds since
1601-01-01 UTC (Windows epoch).
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlparse

from . import state

log = logging.getLogger(__name__)

# Windows epoch (1601-01-01) to unix epoch (1970-01-01) in seconds.
WIN_EPOCH_OFFSET = 11644473600

# Chromium PageTransition core types (low byte of transition int).
TRANSITION_TYPES = {
    0: "link", 1: "typed", 2: "auto_bookmark", 3: "auto_subframe",
    4: "manual_subframe", 5: "generated", 6: "start_page", 7: "form_submit",
    8: "reload", 9: "keyword", 10: "keyword_generated",
}

# Browser name -> root directory containing profile subdirs.
# Arc nests profiles under "User Data"; others are flat.
BROWSER_ROOTS = {
    "chrome": "~/Library/Application Support/Google/Chrome",
    "brave":  "~/Library/Application Support/BraveSoftware/Brave-Browser",
    "edge":   "~/Library/Application Support/Microsoft Edge",
    "arc":    "~/Library/Application Support/Arc/User Data",
}


def chrome_time_to_unix(chrome_us: int) -> int:
    """Convert Chromium microseconds-since-1601 to unix epoch seconds."""
    if chrome_us <= 0:
        return 0
    return int(chrome_us / 1_000_000) - WIN_EPOCH_OFFSET


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _read_profile_display_names(root: Path) -> dict[str, str]:
    """Pull user-set profile names from Chromium's Local State file.

    Returns a mapping {on_disk_folder_name: friendly_name}. Chromium stores
    things like {'Default': 'Work', 'Profile 1': 'Personal'} under
    profile.info_cache.<folder>.name — populated when the user edits the
    profile name in chrome://settings/manageProfile.
    """
    state_path = root / "Local State"
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    info_cache = (data.get("profile") or {}).get("info_cache") or {}
    result: dict[str, str] = {}
    for folder, info in info_cache.items():
        # Prefer the explicit user-set `name`; fall back to the Google
        # account name (`gaia_name`) which is present when the profile is
        # signed in and the user hasn't renamed.
        name = info.get("name") or info.get("gaia_name")
        if name and name.strip():
            result[folder] = name.strip()
    return result


def _discover_profiles(browser: str, root: Path) -> list[tuple[str, Path]]:
    """Return [(profile_name, history_file), ...] for all profiles with a History DB."""
    if not root.exists():
        return []
    profiles: list[tuple[str, Path]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        history_file = child / "History"
        if history_file.is_file():
            profiles.append((child.name, history_file))
    return profiles


def _copy_locked_db(src: Path, dst_dir: Path) -> Path:
    """Chromium locks its History DB when the browser is open. Copy it first."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{src.parent.name}-History.sqlite"
    shutil.copy2(src, dst)
    return dst


def _read_visits(db_path: Path, since_source_id: int) -> Iterator[dict]:
    """Yield visit dicts from a Chromium History DB with id > since_source_id."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT v.id          AS visit_id,
                   u.url         AS url,
                   u.title       AS title,
                   v.visit_time  AS visit_time,
                   v.transition  AS transition
            FROM visits v
            JOIN urls u ON u.id = v.url
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
                "visited_at": chrome_time_to_unix(row["visit_time"]),
                "transition": TRANSITION_TYPES.get(row["transition"] & 0xFF, "unknown"),
                "domain": _domain_of(row["url"]),
            }
    finally:
        conn.close()


def collect(central_db: sqlite3.Connection, tmp_dir: Path) -> dict[str, int]:
    """Ingest all Chromium-family browsers into central DB. Returns per-browser counts."""
    counts: dict[str, int] = {}
    now = int(time.time())

    for browser, root_str in BROWSER_ROOTS.items():
        root = Path(root_str).expanduser()
        profiles = _discover_profiles(browser, root)
        if not profiles:
            continue

        # One Local State read per browser family, not per profile.
        display_names = _read_profile_display_names(root)

        for profile_name, history_file in profiles:
            key = f"{browser}:{profile_name}"
            try:
                browser_id = state.ensure_browser(central_db, browser, profile_name)
                # Keep display_name fresh each pass so user edits in
                # chrome://settings/manageProfile surface within one sync.
                state.set_display_name(
                    central_db, browser_id, display_names.get(profile_name)
                )
                last_raw, offset = state.get_state(central_db, browser_id)
                copied = _copy_locked_db(history_file, tmp_dir)
                # Detect reset before scanning. If Chrome rebuilt its
                # History DB, the max id drops and our cursor is stale.
                src_max = state.source_max_id(copied, "visits")
                last_raw, offset = state.detect_and_apply_reset(
                    src_max, last_raw, offset, f"{browser}/{profile_name}"
                )
                max_raw = last_raw
                rows_to_insert = []
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
                log.info("%s/%s: %d new visits", browser, profile_name, len(rows_to_insert))
                copied.unlink(missing_ok=True)
            except sqlite3.OperationalError as e:
                log.warning("%s/%s: sqlite error: %s", browser, profile_name, e)
                counts[key] = 0
            except Exception as e:
                log.exception("%s/%s: failed: %s", browser, profile_name, e)
                counts[key] = 0
    return counts

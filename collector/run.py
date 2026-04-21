# Created: 18:59 21-Apr-2026
# Updated: 21:28 21-Apr-2026
"""Main orchestrator: run all collectors, write to central DB.

Usage:
    python3 -m collector.run --init       # initialize central DB (runs schema.sql)
    python3 -m collector.run              # run one collection pass
    python3 -m collector.run --loop 600   # run every 600 seconds forever
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sqlite3
import sys
import time
from pathlib import Path

from . import chromium, safari, firefox

DATA_DIR = Path("~/.browser-history").expanduser()
DB_PATH = DATA_DIR / "history.db"
TMP_DIR = DATA_DIR / "tmp"
LOG_PATH = DATA_DIR / "collector.log"
SYNC_STATE_PATH = DATA_DIR / "sync_state.json"
CONFIG_PATH = DATA_DIR / "config.json"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"

DEFAULT_INTERVAL_MIN_S = 45
DEFAULT_INTERVAL_MAX_S = 60


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(sys.stdout),
        ],
    )


def migrate_db(conn: sqlite3.Connection) -> None:
    """Apply lightweight forward-only migrations to an existing DB.
    Safe to call on every run — all operations are idempotent."""
    cur = conn.execute("PRAGMA table_info(ingest_state)")
    cols = {row[1] for row in cur.fetchall()}
    if "source_id_offset" not in cols:
        conn.execute(
            "ALTER TABLE ingest_state ADD COLUMN source_id_offset INTEGER NOT NULL DEFAULT 0"
        )
        logging.info("migrated ingest_state: added source_id_offset column")
    cur = conn.execute("PRAGMA table_info(browsers)")
    cols = {row[1] for row in cur.fetchall()}
    if "display_name" not in cols:
        conn.execute("ALTER TABLE browsers ADD COLUMN display_name TEXT")
        logging.info("migrated browsers: added display_name column")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema_sql)
        migrate_db(conn)
    logging.info("initialized %s", DB_PATH)


def run_once() -> dict[str, int]:
    if not DB_PATH.exists():
        init_db()
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, int] = {}
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        # Idempotent: only does anything on the first run after an upgrade.
        migrate_db(conn)
        results.update(chromium.collect(conn, TMP_DIR))
        results.update(safari.collect(conn, TMP_DIR))
        results.update(firefox.collect(conn, TMP_DIR))
    total = sum(results.values())
    logging.info("pass complete: %d new visits across %d sources", total, len(results))
    return results


def load_config() -> dict:
    """Read optional user config. Falls back to defaults."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            logging.exception("invalid config.json; using defaults")
    return {}


def _interval_range() -> tuple[int, int]:
    cfg = load_config()
    lo = int(cfg.get("sync_interval_min_s", DEFAULT_INTERVAL_MIN_S))
    hi = int(cfg.get("sync_interval_max_s", DEFAULT_INTERVAL_MAX_S))
    lo = max(5, lo)         # hard floor to avoid hammering the disk
    hi = max(lo, hi)
    return lo, hi


def write_sync_state(last_run_at: int, next_run_at: int, interval_s: int) -> None:
    """Persist sync timing so the web UI can show a live countdown."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_sync_at": last_run_at,
        "next_sync_at": next_run_at,
        "interval_s": interval_s,
    }
    try:
        SYNC_STATE_PATH.write_text(json.dumps(payload))
    except Exception:
        logging.exception("could not write sync_state.json")


def _pick_interval() -> int:
    lo, hi = _interval_range()
    return random.randint(lo, hi)


def run_loop(
    interval_s: int | None = None,
    stop_flag=lambda: False,
) -> None:
    """Periodic collection loop with per-iteration random jitter.

    - If `interval_s` is None, each pass picks a new random interval
      from config (default 45–60 s) so ingests don't land at the same
      boundary every time.
    - If `interval_s` is an int, uses a fixed interval (legacy / CLI use).
    - `stop_flag` is a callable returning True when the loop should
      exit — used by the menubar app on Quit.
    """
    while not stop_flag():
        try:
            run_once()
        except Exception:
            logging.exception("collector pass failed; continuing")
        pick = interval_s if interval_s else _pick_interval()
        now_ts = int(time.time())
        write_sync_state(now_ts, now_ts + pick, pick)
        # Sleep in 1-sec slices so we react to stop_flag quickly.
        slept = 0
        while slept < pick and not stop_flag():
            time.sleep(1)
            slept += 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--init", action="store_true", help="initialize central DB and exit")
    p.add_argument("--loop", type=int, metavar="SECONDS", nargs="?", const=0,
                   help="run forever; pass SECONDS for a fixed interval, "
                        "or bare --loop for randomized 45–60s")
    args = p.parse_args()
    setup_logging()
    if args.init:
        init_db()
        return 0
    if args.loop is not None:
        run_loop(args.loop if args.loop > 0 else None)
        return 0
    run_once()
    return 0


if __name__ == "__main__":
    sys.exit(main())

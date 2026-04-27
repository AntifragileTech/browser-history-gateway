# Created: 21:55 27-Apr-2026
"""Tests for collector/paths.py + collector/run.py (migrations + config)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from collector import paths, run as collector_run


pytestmark = pytest.mark.unit


# ---- paths --------------------------------------------------------------


def test_chromium_known_browsers_returns_nonempty_list() -> None:
    out = paths.chromium_known_browsers()
    assert isinstance(out, list)
    assert len(out) >= 5
    for name, root in out:
        assert isinstance(name, str)
        assert isinstance(root, Path)


def test_chromium_known_browsers_contains_chrome_on_each_platform() -> None:
    names = [n for n, _ in paths.chromium_known_browsers()]
    assert "chrome" in names


def test_chromium_appsupport_root_returns_path() -> None:
    p = paths.chromium_appsupport_root()
    assert isinstance(p, Path)


def test_firefox_profiles_root_returns_path() -> None:
    p = paths.firefox_profiles_root()
    assert isinstance(p, Path)


def test_safari_history_path_macos_only() -> None:
    p = paths.safari_history_path()
    if sys.platform == "darwin":
        assert isinstance(p, Path)
        assert "Safari" in str(p)
    else:
        assert p is None


def test_safari_watch_path_macos_only() -> None:
    p = paths.safari_watch_path()
    if sys.platform == "darwin":
        assert isinstance(p, Path)
    else:
        assert p is None


# ---- run.migrate_db -----------------------------------------------------


def _make_legacy_db(tmp_path: Path) -> Path:
    """Build a v0 DB that's missing the source_id_offset + display_name
    columns to verify migrate_db is forward-only and idempotent."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE browsers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            profile TEXT NOT NULL,
            UNIQUE(name, profile)
        );
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY,
            browser_id INTEGER NOT NULL,
            url TEXT, domain TEXT, title TEXT,
            visited_at INTEGER, transition TEXT,
            source_visit_id INTEGER, ingested_at INTEGER
        );
        CREATE TABLE ingest_state (
            browser_id INTEGER PRIMARY KEY,
            last_source_visit_id INTEGER NOT NULL DEFAULT 0,
            last_run_at INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_migrate_db_adds_source_id_offset(tmp_path: Path) -> None:
    db = _make_legacy_db(tmp_path)
    conn = sqlite3.connect(str(db))
    collector_run.migrate_db(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ingest_state)")}
    assert "source_id_offset" in cols
    conn.close()


def test_migrate_db_adds_display_name(tmp_path: Path) -> None:
    db = _make_legacy_db(tmp_path)
    conn = sqlite3.connect(str(db))
    collector_run.migrate_db(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(browsers)")}
    assert "display_name" in cols
    conn.close()


def test_migrate_db_is_idempotent(tmp_path: Path) -> None:
    db = _make_legacy_db(tmp_path)
    conn = sqlite3.connect(str(db))
    collector_run.migrate_db(conn)
    collector_run.migrate_db(conn)  # second call must not raise
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ingest_state)")}
    assert "source_id_offset" in cols
    conn.close()


# ---- run.load_config + interval ----------------------------------------


def test_load_config_returns_empty_dict_when_no_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(collector_run, "CONFIG_PATH", tmp_path / "absent.json")
    assert collector_run.load_config() == {}


def test_load_config_returns_dict_when_file_valid(monkeypatch, tmp_path) -> None:
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"sync_interval_min_s": 30, "sync_interval_max_s": 60}))
    monkeypatch.setattr(collector_run, "CONFIG_PATH", p)
    cfg = collector_run.load_config()
    assert cfg == {"sync_interval_min_s": 30, "sync_interval_max_s": 60}


def test_load_config_returns_empty_on_invalid_json(monkeypatch, tmp_path) -> None:
    p = tmp_path / "config.json"
    p.write_text("{not valid json}")
    monkeypatch.setattr(collector_run, "CONFIG_PATH", p)
    # Should not raise; falls back to defaults.
    assert collector_run.load_config() == {}


def test_interval_range_uses_config_when_present(monkeypatch, tmp_path) -> None:
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"sync_interval_min_s": 100, "sync_interval_max_s": 200}))
    monkeypatch.setattr(collector_run, "CONFIG_PATH", p)
    lo, hi = collector_run._interval_range()
    assert (lo, hi) == (100, 200)


def test_interval_range_clamps_lower_bound(monkeypatch, tmp_path) -> None:
    # User config asks for 1s — the floor should kick in to avoid disk thrash.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"sync_interval_min_s": 1, "sync_interval_max_s": 1}))
    monkeypatch.setattr(collector_run, "CONFIG_PATH", p)
    lo, hi = collector_run._interval_range()
    assert lo >= 5
    assert hi >= lo


def test_interval_range_falls_back_to_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(collector_run, "CONFIG_PATH", tmp_path / "missing.json")
    lo, hi = collector_run._interval_range()
    assert lo == collector_run.DEFAULT_INTERVAL_MIN_S
    assert hi == collector_run.DEFAULT_INTERVAL_MAX_S


def test_pick_interval_within_range(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(collector_run, "CONFIG_PATH", tmp_path / "missing.json")
    for _ in range(20):
        v = collector_run._pick_interval()
        assert collector_run.DEFAULT_INTERVAL_MIN_S <= v <= collector_run.DEFAULT_INTERVAL_MAX_S


# ---- run.write_sync_state ----------------------------------------------


def test_write_sync_state_writes_json(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(collector_run, "DATA_DIR", tmp_path)
    monkeypatch.setattr(collector_run, "SYNC_STATE_PATH", state_file)
    collector_run.write_sync_state(last_run_at=1000, next_run_at=1060, interval_s=60)
    data = json.loads(state_file.read_text())
    assert data == {"last_sync_at": 1000, "next_sync_at": 1060, "interval_s": 60}

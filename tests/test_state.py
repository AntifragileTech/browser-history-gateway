# Created: 21:55 27-Apr-2026
"""Tests for collector/state.py — reset detection + offset bumping."""
from __future__ import annotations

import sqlite3

import pytest

from collector import state


pytestmark = pytest.mark.unit


def test_ensure_browser_creates_row(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "chrome", "Default")
    assert bid > 0
    rows = tmp_db.execute(
        "SELECT name, profile FROM browsers WHERE id = ?", (bid,)
    ).fetchone()
    assert tuple(rows) == ("chrome", "Default")


def test_ensure_browser_is_idempotent(tmp_db: sqlite3.Connection) -> None:
    bid_1 = state.ensure_browser(tmp_db, "chrome", "Default")
    bid_2 = state.ensure_browser(tmp_db, "chrome", "Default")
    assert bid_1 == bid_2
    n = tmp_db.execute("SELECT COUNT(*) FROM browsers").fetchone()[0]
    assert n == 1


def test_set_display_name_persists_label(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "chrome", "Profile 1")
    state.set_display_name(tmp_db, bid, "Work")
    label = tmp_db.execute(
        "SELECT display_name FROM browsers WHERE id = ?", (bid,)
    ).fetchone()[0]
    assert label == "Work"


def test_set_display_name_no_op_for_empty(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "chrome", "Default")
    state.set_display_name(tmp_db, bid, None)
    state.set_display_name(tmp_db, bid, "")
    label = tmp_db.execute(
        "SELECT display_name FROM browsers WHERE id = ?", (bid,)
    ).fetchone()[0]
    assert label is None


def test_get_state_default_is_zero(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "chrome", "Default")
    assert state.get_state(tmp_db, bid) == (0, 0)


def test_save_and_get_state_roundtrip(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "chrome", "Default")
    state.save_state(tmp_db, bid, last_raw_id=1234, offset=10, now=999)
    assert state.get_state(tmp_db, bid) == (1234, 10)


def test_save_state_upserts_on_conflict(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "chrome", "Default")
    state.save_state(tmp_db, bid, last_raw_id=10, offset=0, now=1)
    state.save_state(tmp_db, bid, last_raw_id=20, offset=5, now=2)
    assert state.get_state(tmp_db, bid) == (20, 5)


def test_detect_reset_no_change_when_source_grows() -> None:
    # Normal forward progress: source max > our cursor.
    new_raw, new_off = state.detect_and_apply_reset(
        source_max=5000, last_raw_id=4000, offset=0, label="chrome/Default"
    )
    assert (new_raw, new_off) == (4000, 0)


def test_detect_reset_bumps_offset_on_drop() -> None:
    # Source DB rebuilt: max id 100 < cursor 5000 -> reset detected.
    new_raw, new_off = state.detect_and_apply_reset(
        source_max=100, last_raw_id=5000, offset=0, label="chrome/Default"
    )
    assert new_raw == 0
    # Offset advances past the entire previous generation so new
    # effective IDs (raw + offset) cannot collide with old ones.
    assert new_off == 5000


def test_detect_reset_accumulates_offset_across_multiple_resets() -> None:
    # First reset
    raw, off = state.detect_and_apply_reset(50, 1000, 0, "chrome/Default")
    assert (raw, off) == (0, 1000)
    # Imagine some growth, then another reset
    raw, off = state.detect_and_apply_reset(30, 800, 1000, "chrome/Default")
    assert raw == 0
    assert off == 1800  # 1000 + 800


def test_detect_reset_ignores_drop_when_cursor_zero() -> None:
    # First-run state: cursor at 0, source happens to be empty.
    # Should NOT register as a reset.
    raw, off = state.detect_and_apply_reset(0, 0, 0, "chrome/Default")
    assert (raw, off) == (0, 0)


def test_source_max_id_returns_zero_for_empty_table(tmp_path) -> None:
    db = tmp_path / "src.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, ts INTEGER)")
    conn.commit()
    conn.close()
    assert state.source_max_id(db, "visits") == 0


def test_source_max_id_returns_max(tmp_path) -> None:
    db = tmp_path / "src.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, ts INTEGER)")
    conn.executemany("INSERT INTO visits (id, ts) VALUES (?, ?)",
                     [(1, 100), (5, 200), (3, 150)])
    conn.commit()
    conn.close()
    assert state.source_max_id(db, "visits") == 5

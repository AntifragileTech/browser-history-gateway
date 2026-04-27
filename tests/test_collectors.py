# Created: 21:55 27-Apr-2026
"""Tests for per-browser collectors: time conversions, domain extraction,
ingest end-to-end against synthetic source DBs.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from collector import chromium, firefox, safari, state, run as collector_run


pytestmark = pytest.mark.unit


# ---- time conversions ---------------------------------------------------


def test_chrome_time_to_unix_zero_or_negative() -> None:
    assert chromium.chrome_time_to_unix(0) == 0
    assert chromium.chrome_time_to_unix(-100) == 0


def test_chrome_time_to_unix_known_value() -> None:
    # Chromium epoch (1601-01-01) -> unix epoch (1970-01-01) is exactly
    # 11_644_473_600 seconds. So 11_644_473_600_000_000 us -> 0.
    assert chromium.chrome_time_to_unix(11_644_473_600_000_000) == 0
    # 1 second past unix epoch -> 11_644_473_601 seconds (in microseconds).
    assert chromium.chrome_time_to_unix(11_644_473_601_000_000) == 1


def test_cocoa_time_to_unix_zero_or_negative() -> None:
    assert safari.cocoa_time_to_unix(0) == 0
    assert safari.cocoa_time_to_unix(-1.5) == 0


def test_cocoa_time_to_unix_known_value() -> None:
    # Cocoa epoch (2001-01-01) -> unix epoch offset 978_307_200.
    # cocoa=0 should map to unix 978_307_200.
    # cocoa=1 should map to unix 978_307_201.
    assert safari.cocoa_time_to_unix(1.0) == 978_307_201


def test_chrome_time_round_trip_for_real_visit() -> None:
    # A visit on 2024-06-15 12:00:00 UTC -> unix 1718452800.
    # Chrome stores it as (unix + 11644473600) * 1e6.
    chrome_us = (1718452800 + 11_644_473_600) * 1_000_000
    assert chromium.chrome_time_to_unix(chrome_us) == 1718452800


# ---- domain extraction --------------------------------------------------


def test_chromium_domain_normal_url() -> None:
    assert chromium._domain_of("https://www.GitHub.com/foo/bar") == "www.github.com"


def test_chromium_domain_lowercase_only() -> None:
    assert chromium._domain_of("https://EXAMPLE.com") == "example.com"


def test_chromium_domain_no_scheme_returns_empty() -> None:
    # urlparse handles bare strings as path, netloc empty.
    assert chromium._domain_of("not a url") == ""


def test_chromium_domain_file_url() -> None:
    # file:// URLs have empty netloc — they shouldn't crash the parser.
    assert chromium._domain_of("file:///Users/x/secret.pdf") == ""


def test_safari_and_firefox_domain_share_behavior() -> None:
    for fn in (safari._domain_of, firefox._domain_of):
        assert fn("https://example.com/x") == "example.com"
        assert fn("not-a-url") == ""


# ---- profile display name parsing ---------------------------------------


def test_read_profile_display_names_parses_local_state(tmp_path: Path) -> None:
    local_state = tmp_path / "Local State"
    local_state.write_text(
        '{"profile":{"info_cache":{"Default":{"name":"Work"},'
        '"Profile 1":{"name":"Personal"}}}}',
        encoding="utf-8",
    )
    out = chromium._read_profile_display_names(tmp_path)
    assert out == {"Default": "Work", "Profile 1": "Personal"}


def test_read_profile_display_names_falls_back_to_gaia_name(tmp_path: Path) -> None:
    (tmp_path / "Local State").write_text(
        '{"profile":{"info_cache":{"Default":{"gaia_name":"Alice"}}}}',
        encoding="utf-8",
    )
    out = chromium._read_profile_display_names(tmp_path)
    assert out == {"Default": "Alice"}


def test_read_profile_display_names_skips_blank(tmp_path: Path) -> None:
    (tmp_path / "Local State").write_text(
        '{"profile":{"info_cache":{"Default":{"name":"   "}}}}',
        encoding="utf-8",
    )
    out = chromium._read_profile_display_names(tmp_path)
    assert out == {}


def test_read_profile_display_names_no_file_returns_empty(tmp_path: Path) -> None:
    assert chromium._read_profile_display_names(tmp_path) == {}


def test_read_profile_display_names_invalid_json_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "Local State").write_text("not json at all", encoding="utf-8")
    assert chromium._read_profile_display_names(tmp_path) == {}


def test_read_profile_display_names_empty_info_cache(tmp_path: Path) -> None:
    (tmp_path / "Local State").write_text(
        '{"profile":{"info_cache":{}}}', encoding="utf-8"
    )
    assert chromium._read_profile_display_names(tmp_path) == {}


# ---- chunked-insert behaviour -------------------------------------------


def _seed_chromium_history(db_path: Path, n: int) -> None:
    """Build a synthetic Chromium History DB with `n` rows."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT);
        CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER,
                             visit_time INTEGER, transition INTEGER);
        """
    )
    rows_urls = [(i, f"https://site{i}.example.com", f"Title {i}") for i in range(1, n + 1)]
    rows_visits = [
        # visit_time encoded as Chrome microseconds-since-1601 for unix=1700000000+i
        (i, i, (1700000000 + i + 11_644_473_600) * 1_000_000, 0)
        for i in range(1, n + 1)
    ]
    conn.executemany("INSERT INTO urls VALUES (?, ?, ?)", rows_urls)
    conn.executemany("INSERT INTO visits VALUES (?, ?, ?, ?)", rows_visits)
    conn.commit()
    conn.close()


def test_chromium_read_visits_yields_in_id_order(tmp_path: Path) -> None:
    src = tmp_path / "history.db"
    _seed_chromium_history(src, 5)
    out = list(chromium._read_visits(src, since_source_id=0))
    assert [v["source_visit_id"] for v in out] == [1, 2, 3, 4, 5]
    # Sanity: URLs + transition decoded correctly.
    assert out[0]["url"] == "https://site1.example.com"
    assert out[0]["transition"] == "link"  # 0 -> link


def test_chromium_read_visits_filters_by_since(tmp_path: Path) -> None:
    src = tmp_path / "history.db"
    _seed_chromium_history(src, 5)
    out = list(chromium._read_visits(src, since_source_id=3))
    assert [v["source_visit_id"] for v in out] == [4, 5]


def test_chromium_flush_inserts_into_central(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "chrome", "Default")
    batch = [
        (bid, f"https://x{i}.com", f"x{i}.com", f"t{i}", 1700000000 + i, "link", i, 1700000000)
        for i in range(1, 11)
    ]
    chromium._flush(tmp_db, batch)
    n = tmp_db.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    assert n == 10


def test_chromium_flush_is_safe_with_empty_batch(tmp_db: sqlite3.Connection) -> None:
    chromium._flush(tmp_db, [])  # must not raise
    assert tmp_db.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0


def test_firefox_flush_respects_unique_constraint(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "firefox", "default-release")
    row = (bid, "https://x.com", "x.com", "t", 1700000000, "link", 42, 1700000000)
    firefox._flush(tmp_db, [row, row])  # same source_visit_id twice
    n = tmp_db.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    assert n == 1  # second insert ignored by UNIQUE(browser_id, source_visit_id)


def test_safari_flush_inserts(tmp_db: sqlite3.Connection) -> None:
    bid = state.ensure_browser(tmp_db, "safari", "Default")
    safari._flush(tmp_db, [
        (bid, "https://apple.com", "apple.com", "Apple", 1700000000, "link", 1, 1700000000),
    ])
    assert tmp_db.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 1


# ---- backup API: chromium round-trip ------------------------------------


def test_chromium_backup_locked_db_produces_readable_copy(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _seed_chromium_history(src, 3)
    dst_dir = tmp_path / "tmp"
    copied = chromium._backup_locked_db(src, dst_dir, "chrome", "Default")
    assert copied.exists()
    # The copy is independent — closing src or deleting it should not
    # affect the snapshot.
    src.unlink()
    rows = list(chromium._read_visits(copied, 0))
    assert len(rows) == 3


def test_firefox_backup_db_round_trip(tmp_path: Path) -> None:
    # Build a minimal places.sqlite-shaped DB and run the firefox copy.
    src = tmp_path / "places.sqlite"
    conn = sqlite3.connect(str(src))
    conn.executescript(
        """
        CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT);
        CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER,
                                         visit_date INTEGER, visit_type INTEGER);
        INSERT INTO moz_places VALUES (1, 'https://x.com', 'X');
        INSERT INTO moz_historyvisits VALUES (1, 1, 1700000000000000, 1);
        """
    )
    conn.commit()
    conn.close()
    dst_dir = tmp_path / "tmp"
    copied = firefox._backup_db(src, dst_dir, "default-release")
    assert copied.exists()
    rows = list(firefox._read_visits(copied, 0))
    assert len(rows) == 1
    assert rows[0]["url"] == "https://x.com"
    assert rows[0]["transition"] == "link"


# ---- end-to-end ingest --------------------------------------------------


def test_chromium_collect_full_pipeline_idempotent(tmp_db: sqlite3.Connection,
                                                    tmp_dir: Path,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    """Synthetic browser tree -> first collect inserts everything, second
    collect inserts nothing new."""
    fake_root = tmp_path / "fakebrowser"
    profile_dir = fake_root / "Default"
    profile_dir.mkdir(parents=True)
    (fake_root / "Local State").write_text(
        '{"profile":{"info_cache":{"Default":{"name":"WorkProfile"}}}}',
        encoding="utf-8",
    )
    history = profile_dir / "History"
    _seed_chromium_history(history, 7)

    monkeypatch.setattr(chromium, "_discover_browsers",
                        lambda: [("fakechrome", fake_root)])
    counts_1 = chromium.collect(tmp_db, tmp_dir)
    assert counts_1.get("fakechrome:Default") == 7
    assert tmp_db.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 7

    # Display name should have been picked up from Local State.
    label = tmp_db.execute(
        "SELECT display_name FROM browsers WHERE name='fakechrome'"
    ).fetchone()[0]
    assert label == "WorkProfile"

    # Second pass: no new rows in source -> no new inserts.
    counts_2 = chromium.collect(tmp_db, tmp_dir)
    assert counts_2.get("fakechrome:Default") == 0
    assert tmp_db.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 7


def test_chromium_collect_handles_reset(tmp_db: sqlite3.Connection,
                                         tmp_dir: Path,
                                         monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
    fake_root = tmp_path / "fakebrowser"
    profile_dir = fake_root / "Default"
    profile_dir.mkdir(parents=True)
    (fake_root / "Local State").write_text("{}", encoding="utf-8")
    history = profile_dir / "History"
    _seed_chromium_history(history, 5)

    monkeypatch.setattr(chromium, "_discover_browsers",
                        lambda: [("fakechrome", fake_root)])
    chromium.collect(tmp_db, tmp_dir)
    assert tmp_db.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 5

    # Simulate a profile reset: nuke the source DB and seed a new, smaller one.
    history.unlink()
    _seed_chromium_history(history, 2)
    chromium.collect(tmp_db, tmp_dir)

    # We should now have 5 (pre-reset) + 2 (post-reset) = 7 unique rows
    # because the offset-bumping prevents UNIQUE collisions.
    assert tmp_db.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 7

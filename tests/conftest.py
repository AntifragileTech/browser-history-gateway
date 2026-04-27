# Created: 21:55 27-Apr-2026
"""Shared pytest fixtures.

Every test that needs a SQLite DB gets a fresh tmp_path-based file +
schema applied — there's no shared global state between tests.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Iterator

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = PROJECT_ROOT / "schema.sql"

# Make the project root importable so `from collector import ...` works
# without us being a package on PyPI.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A connection to a fresh on-disk DB with the production schema applied."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL.read_text())
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Convenience alias for tmp_path; collectors expect a `tmp_dir` arg."""
    d = tmp_path / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d

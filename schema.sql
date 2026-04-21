-- Created: 18:59 21-Apr-2026
-- Updated: 21:28 21-Apr-2026
-- Updated: 21:46 21-Apr-2026
-- Central browser history database schema.
-- All timestamps normalized to unix epoch seconds (UTC).

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS browsers (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,   -- 'chrome', 'brave', 'arc', 'edge', 'safari', 'firefox'
    profile       TEXT NOT NULL,   -- stable identifier, usually the on-disk folder name ('Default', 'Profile 1')
    display_name  TEXT,            -- user-friendly name, e.g. 'Work', 'Personal' — refreshed every pass
    UNIQUE(name, profile)
);

CREATE TABLE IF NOT EXISTS visits (
    id              INTEGER PRIMARY KEY,
    browser_id      INTEGER NOT NULL REFERENCES browsers(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    domain          TEXT NOT NULL,
    title           TEXT,
    visited_at      INTEGER NOT NULL,        -- unix epoch seconds, UTC
    transition      TEXT,                    -- 'link', 'typed', 'reload', 'bookmark', etc.
    source_visit_id INTEGER NOT NULL,        -- row id from source browser DB
    ingested_at     INTEGER NOT NULL,        -- unix epoch seconds
    UNIQUE(browser_id, source_visit_id)
);

CREATE INDEX IF NOT EXISTS idx_visits_visited_at ON visits(visited_at DESC);
CREATE INDEX IF NOT EXISTS idx_visits_domain     ON visits(domain);
CREATE INDEX IF NOT EXISTS idx_visits_browser    ON visits(browser_id, visited_at DESC);
CREATE INDEX IF NOT EXISTS idx_visits_url        ON visits(url);

-- Bookkeeping: last-seen source_visit_id per browser so incremental ingest
-- can skip everything already loaded.
--
-- source_id_offset is used to handle "source DB reset" (profile re-created,
-- user signed out + back in, full history clear on some browsers). When the
-- source's MAX(id) suddenly drops below our cursor, we bump the offset by
-- the old cursor value and re-scan from 0. New rows land with effective
-- source_visit_id = raw_id + offset, so they never collide with pre-reset
-- rows in the UNIQUE(browser_id, source_visit_id) constraint.
CREATE TABLE IF NOT EXISTS ingest_state (
    browser_id           INTEGER PRIMARY KEY REFERENCES browsers(id) ON DELETE CASCADE,
    last_source_visit_id INTEGER NOT NULL DEFAULT 0,   -- raw id of last row seen in current source generation
    source_id_offset     INTEGER NOT NULL DEFAULT 0,   -- accumulated across resets
    last_run_at          INTEGER NOT NULL DEFAULT 0
);

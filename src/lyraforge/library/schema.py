"""SQLite schema and forward-only migrations for the local song library."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

SCHEMA_VERSION = 3

_MIGRATION_V1 = """
CREATE TABLE IF NOT EXISTS songs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    original_name TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    local_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS arrangements (
    id TEXT PRIMARY KEY,
    song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    style TEXT NOT NULL,
    transpose INTEGER NOT NULL,
    speed REAL NOT NULL,
    playable_ratio REAL NOT NULL,
    event_count INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    performance_path TEXT NOT NULL,
    report_path TEXT NOT NULL,
    preview_path TEXT,
    is_favorite INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playback_sessions (
    id TEXT PRIMARY KEY,
    arrangement_id TEXT NOT NULL REFERENCES arrangements(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    elapsed_ms REAL NOT NULL,
    ended_state TEXT NOT NULL,
    actions_sent INTEGER NOT NULL,
    error_summary TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_songs_title ON songs(title);
CREATE INDEX IF NOT EXISTS idx_sources_song_id ON sources(song_id);
CREATE INDEX IF NOT EXISTS idx_arrangements_song_id ON arrangements(song_id);
CREATE INDEX IF NOT EXISTS idx_playback_arrangement_id ON playback_sessions(arrangement_id);
"""

_MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id TEXT PRIMARY KEY,
    song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    engine TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    options_json TEXT NOT NULL,
    raw_midi_path TEXT NOT NULL,
    cleaned_midi_path TEXT NOT NULL,
    status TEXT NOT NULL,
    note_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transcriptions_song_id ON transcriptions(song_id);
"""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def configure_connection(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply all pending migrations idempotently and return the current version."""
    configure_connection(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
    current = int(row["v"])
    if current < 1:
        with conn:
            conn.executescript(_MIGRATION_V1)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, _utc_now_iso()),
            )
        current = 1
    if current < 2:
        with conn:
            conn.executescript(_MIGRATION_V2)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (2, _utc_now_iso()),
            )
        current = 2
    if current < 3:
        existing_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(arrangements)").fetchall()
        }
        with conn:
            if "parent_id" not in existing_cols:
                conn.execute("ALTER TABLE arrangements ADD COLUMN parent_id TEXT")
            if "score" not in existing_cols:
                conn.execute("ALTER TABLE arrangements ADD COLUMN score REAL")
            if "user_vote" not in existing_cols:
                conn.execute(
                    "ALTER TABLE arrangements ADD COLUMN user_vote INTEGER NOT NULL DEFAULT 0"
                )
            if "label" not in existing_cols:
                conn.execute("ALTER TABLE arrangements ADD COLUMN label TEXT")
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (3, _utc_now_iso()),
            )
        current = 3
    return current

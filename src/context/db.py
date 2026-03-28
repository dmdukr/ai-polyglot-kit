"""SQLite connection manager and schema initialization for Context Engine.

Provides:
- get_connection(): thread-safe singleton connection with WAL mode
- init_schema(): create all tables and indexes from architecture spec Section 15
- check_integrity(): startup integrity check
"""

from __future__ import annotations

import logging
import sqlite3
import threading

logger = logging.getLogger(__name__)

_local = threading.local()
_db_path: str = ""


def configure(db_path: str) -> None:
    """Set the database file path. Must be called before get_connection()."""
    global _db_path  # noqa: PLW0603
    _db_path = db_path


def get_connection() -> sqlite3.Connection:
    """Get thread-local SQLite connection with WAL mode and row_factory.

    Connection is created once per thread and reused.
    """
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None:
        if not _db_path:
            msg = "Database not configured. Call db.configure(path) first."
            raise RuntimeError(msg)
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA cache_size = -64000")
        conn.execute("PRAGMA temp_store = MEMORY")
        _local.conn = conn
    return conn


SCHEMA_SQL: str = """
-- Full schema from architecture spec Section 15.2
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    raw_text_enc BLOB,
    normalized_text_enc BLOB,
    app TEXT NOT NULL,
    window_title TEXT,
    thread_id INTEGER REFERENCES conversation_threads(id),
    cluster_id INTEGER REFERENCES clusters(id),
    duration_s REAL,
    word_count INTEGER,
    language TEXT,
    stt_provider TEXT,
    llm_provider TEXT,
    tokens_stt INTEGER DEFAULT 0,
    tokens_llm INTEGER DEFAULT 0,
    confidence REAL
);

CREATE TABLE IF NOT EXISTS conversation_threads (
    id INTEGER PRIMARY KEY,
    app TEXT NOT NULL,
    last_app TEXT,
    window_title TEXT,
    topic_summary TEXT,
    cluster_id INTEGER REFERENCES clusters(id),
    first_message DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_message DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    message_count INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS thread_keywords (
    thread_id INTEGER REFERENCES conversation_threads(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    PRIMARY KEY (thread_id, keyword)
);

CREATE TABLE IF NOT EXISTS term_cooccurrence (
    term_a TEXT NOT NULL,
    term_b TEXT NOT NULL,
    cluster_id INTEGER NOT NULL REFERENCES clusters(id),
    weight INTEGER DEFAULT 1,
    last_used DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (term_a, term_b, cluster_id)
);

CREATE TABLE IF NOT EXISTS conversation_fingerprints (
    id INTEGER PRIMARY KEY,
    cluster_id INTEGER REFERENCES clusters(id),
    app TEXT,
    message_count INTEGER,
    timestamp DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS fingerprint_keywords (
    fingerprint_id INTEGER REFERENCES conversation_fingerprints(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    PRIMARY KEY (fingerprint_id, keyword)
);

CREATE TABLE IF NOT EXISTS dictionary (
    id INTEGER PRIMARY KEY,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    term_type TEXT DEFAULT 'exact',
    origin TEXT DEFAULT 'manual',
    hit_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY,
    raw_text_enc BLOB NOT NULL,
    normalized_text_enc BLOB NOT NULL,
    corrected_text_enc BLOB NOT NULL,
    error_source TEXT,
    app TEXT,
    thread_id INTEGER REFERENCES conversation_threads(id),
    cluster_id INTEGER REFERENCES clusters(id),
    timestamp DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS correction_counts (
    old_token TEXT NOT NULL,
    new_token TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    PRIMARY KEY (old_token, new_token)
);

CREATE TABLE IF NOT EXISTS cluster_llm_stats (
    cluster_id INTEGER PRIMARY KEY REFERENCES clusters(id),
    total_llm_resolutions INTEGER DEFAULT 0,
    llm_errors INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL,
    is_builtin BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS app_rules (
    id INTEGER PRIMARY KEY,
    app_name TEXT NOT NULL UNIQUE,
    script_id INTEGER REFERENCES scripts(id)
);

CREATE TABLE IF NOT EXISTS replacements (
    id INTEGER PRIMARY KEY,
    trigger_text TEXT NOT NULL,
    replacement_text TEXT NOT NULL,
    match_mode TEXT DEFAULT 'fuzzy',
    is_sensitive BOOLEAN DEFAULT 0,
    hit_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_history_context ON history(thread_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_active_threads ON conversation_threads(app, is_active, last_message DESC);
CREATE INDEX IF NOT EXISTS idx_tk_keyword ON thread_keywords(keyword, thread_id);
CREATE INDEX IF NOT EXISTS idx_cooccurrence ON term_cooccurrence(term_a, cluster_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_cooccurrence_reverse ON term_cooccurrence(term_b, cluster_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_fk_keyword ON fingerprint_keywords(keyword, fingerprint_id);
CREATE INDEX IF NOT EXISTS idx_dictionary ON dictionary(source_text);
"""


def init_schema(conn: sqlite3.Connection | None = None) -> None:
    """Create all tables and indexes. Safe to call multiple times (IF NOT EXISTS)."""
    db = conn or get_connection()
    db.executescript(SCHEMA_SQL)
    logger.info("Context Engine schema initialized")


def check_integrity(conn: sqlite3.Connection | None = None) -> bool:
    """Run startup integrity check. Returns True if OK."""
    db = conn or get_connection()
    result = db.execute("PRAGMA integrity_check(1)").fetchone()
    if result is None or result[0] != "ok":
        logger.error("Database integrity check failed: %s", result)
        return False
    return True

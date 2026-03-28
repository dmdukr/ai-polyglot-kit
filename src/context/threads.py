"""Thread management for the Context Engine.

Provides conversation thread lifecycle: finding active threads via
weighted keyword scoring, creating/updating threads, lazy expiry,
and fingerprint saving for long-lived threads.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

THREAD_EXPIRY_MINUTES: int = 15
MATCH_THRESHOLD: float = 2.0
SAME_APP_WEIGHT: float = 2.0
CROSS_APP_WEIGHT: float = 1.0


def _utcnow_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expiry_cutoff() -> str:
    """Return ISO timestamp for the expiry boundary (now - THREAD_EXPIRY_MINUTES)."""
    cutoff = datetime.now(UTC) - timedelta(minutes=THREAD_EXPIRY_MINUTES)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def find_active_thread(
    db: sqlite3.Connection,
    keywords: list[str],
    current_app: str,
) -> sqlite3.Row | None:
    """Find active thread with weighted scoring.

    1. Query all active threads (is_active=1) not expired
       (last_message within THREAD_EXPIRY_MINUTES).
    2. For each thread, count keyword overlap with thread_keywords.
    3. Score: overlap_count * (SAME_APP_WEIGHT if same app else CROSS_APP_WEIGHT).
    4. Filter: score >= MATCH_THRESHOLD.
    5. Tiebreaker: score DESC, last_message DESC, id DESC.
    6. Return best match or None.
    """
    if not keywords:
        return None

    cutoff = _expiry_cutoff()

    # Fetch all active, non-expired threads
    threads = db.execute(
        """SELECT id, app, last_app, last_message
           FROM conversation_threads
           WHERE is_active = 1 AND last_message >= ?
           ORDER BY last_message DESC""",
        [cutoff],
    ).fetchall()

    if not threads:
        return None

    keyword_set = set(keywords)
    best_row: sqlite3.Row | None = None
    best_score: float = 0.0

    for thread in threads:
        thread_id: int = thread["id"]
        thread_app: str = thread["app"]

        # Get keywords for this thread
        kw_rows = db.execute(
            "SELECT keyword FROM thread_keywords WHERE thread_id = ?",
            [thread_id],
        ).fetchall()
        thread_kws = {r["keyword"] for r in kw_rows}

        overlap = len(keyword_set & thread_kws)
        if overlap == 0:
            continue

        weight = SAME_APP_WEIGHT if thread_app == current_app else CROSS_APP_WEIGHT
        score = overlap * weight

        if score < MATCH_THRESHOLD:
            continue

        # Tiebreaker: higher score, then newer last_message, then higher id
        if best_row is None or (
            score > best_score
            or (score == best_score and thread["last_message"] > best_row["last_message"])
            or (
                score == best_score
                and thread["last_message"] == best_row["last_message"]
                and thread["id"] > best_row["id"]
            )
        ):
            best_score = score
            best_row = thread

    return best_row


def assign_to_thread(
    db: sqlite3.Connection,
    keywords: list[str],
    current_app: str,
) -> int | None:
    """Full thread assignment logic. Returns thread_id or None (orphan).

    - Has keywords: find_active_thread() -> if found, update_thread() and return id
                    -> if not found, expire old threads (save fingerprints), create new thread
    - No keywords (empty list): find most recent active thread in same app, or None
    """
    if not keywords:
        # 0-keyword path: find most recent active thread in same app
        cutoff = _expiry_cutoff()
        row = db.execute(
            """SELECT id FROM conversation_threads
               WHERE is_active = 1 AND app = ? AND last_message >= ?
               ORDER BY last_message DESC
               LIMIT 1""",
            [current_app, cutoff],
        ).fetchone()
        if row is not None:
            return int(row["id"])
        return None

    # Has keywords path
    match = find_active_thread(db, keywords, current_app)
    if match is not None:
        thread_id = int(match["id"])
        update_thread(db, thread_id, keywords, current_app)
        return thread_id

    # No match: expire old threads, save fingerprints, create new thread
    expired_ids = expire_threads(db, current_app)
    for eid in expired_ids:
        save_fingerprint(db, eid)

    return create_thread(db, keywords, current_app)


def create_thread(
    db: sqlite3.Connection,
    keywords: list[str],
    app: str,
    cluster_id: int | None = None,
) -> int:
    """Create new thread, insert keywords into thread_keywords, return thread_id."""
    now = _utcnow_iso()
    cursor = db.execute(
        """INSERT INTO conversation_threads
           (app, last_app, cluster_id, first_message, last_message, message_count, is_active)
           VALUES (?, ?, ?, ?, ?, 1, 1)""",
        [app, app, cluster_id, now, now],
    )
    thread_id: int = cursor.lastrowid  # type: ignore[assignment]

    if keywords:
        db.executemany(
            "INSERT OR IGNORE INTO thread_keywords (thread_id, keyword) VALUES (?, ?)",
            [(thread_id, kw) for kw in keywords],
        )

    db.commit()
    logger.debug("create_thread(app=%s, keywords=%s) -> thread_id=%d", app, keywords, thread_id)
    return thread_id


def update_thread(
    db: sqlite3.Connection,
    thread_id: int,
    keywords: list[str],
    app: str,
) -> None:
    """Update thread: add new keywords, update last_app/last_message/message_count."""
    now = _utcnow_iso()

    if keywords:
        db.executemany(
            "INSERT OR IGNORE INTO thread_keywords (thread_id, keyword) VALUES (?, ?)",
            [(thread_id, kw) for kw in keywords],
        )

    db.execute(
        """UPDATE conversation_threads
           SET last_app = ?, last_message = ?, message_count = message_count + 1
           WHERE id = ?""",
        [app, now, thread_id],
    )
    db.commit()
    logger.debug("update_thread(id=%d, app=%s, +keywords=%s)", thread_id, app, keywords)


def expire_threads(db: sqlite3.Connection, current_app: str) -> list[int]:
    """Find and deactivate expired threads for current_app.

    Expired = last_message older than THREAD_EXPIRY_MINUTES.
    Set is_active=0. Return list of expired thread_ids.
    """
    cutoff = _expiry_cutoff()

    rows = db.execute(
        """SELECT id FROM conversation_threads
           WHERE is_active = 1 AND app = ? AND last_message < ?""",
        [current_app, cutoff],
    ).fetchall()

    expired_ids = [int(r["id"]) for r in rows]

    if expired_ids:
        placeholders = ",".join("?" for _ in expired_ids)
        db.execute(
            f"UPDATE conversation_threads SET is_active = 0 WHERE id IN ({placeholders})",  # noqa: S608  # nosec B608
            expired_ids,
        )
        db.commit()
        logger.debug("expire_threads(app=%s): expired %d threads", current_app, len(expired_ids))

    return expired_ids


def save_fingerprint(db: sqlite3.Connection, thread_id: int) -> int | None:
    """Save fingerprint from expired thread if message_count >= 3.

    Copy thread's cluster_id, app, message_count and keywords to fingerprint tables.
    Returns fingerprint_id or None if message_count < 3.
    """
    thread = db.execute(
        "SELECT cluster_id, app, message_count FROM conversation_threads WHERE id = ?",
        [thread_id],
    ).fetchone()

    if thread is None:
        return None

    message_count: int = thread["message_count"]
    if message_count < 3:  # noqa: PLR2004
        return None

    cursor = db.execute(
        """INSERT INTO conversation_fingerprints (cluster_id, app, message_count)
           VALUES (?, ?, ?)""",
        [thread["cluster_id"], thread["app"], message_count],
    )
    fp_id: int = cursor.lastrowid  # type: ignore[assignment]

    # Copy keywords
    kw_rows = db.execute(
        "SELECT keyword FROM thread_keywords WHERE thread_id = ?",
        [thread_id],
    ).fetchall()

    if kw_rows:
        db.executemany(
            "INSERT INTO fingerprint_keywords (fingerprint_id, keyword) VALUES (?, ?)",
            [(fp_id, r["keyword"]) for r in kw_rows],
        )

    db.commit()
    logger.debug("save_fingerprint(thread_id=%d) -> fp_id=%d", thread_id, fp_id)
    return fp_id

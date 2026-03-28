"""Co-occurrence graph operations for Context Engine.

Manages term co-occurrence pairs in the term_cooccurrence table:
- UPSERT with canonical ordering and weight tracking
- Temporal decay queries for context-aware resolution
- Mixed-topic guard to prevent cross-domain pollution
- Pruning (routine + emergency) to bound graph size
"""

from __future__ import annotations

import itertools
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

_MIN_PAIR_SIZE = 2
_MIN_CLUSTER_COUNT = 2
_MIXED_TOPIC_THRESHOLD = 0.7


def _utcnow_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_in_clause(terms: list[str]) -> tuple[str, list[str]]:
    """Build a parameterized IN clause. Returns (placeholder_str, params).

    The placeholders are only ``?`` characters joined by commas, so the
    resulting string is safe to interpolate into SQL.
    """
    placeholders = ",".join("?" * len(terms))
    return placeholders, list(terms)


def update_cooccurrence(db: sqlite3.Connection, keywords: list[str], cluster_id: int) -> None:
    """Insert/update co-occurrence pairs from keywords.

    - Generate all pairs using itertools.combinations
    - Canonical ordering: sorted([term_a, term_b])
    - UPSERT: ON CONFLICT increment weight and update last_used
    - All pairs in single transaction
    """
    if len(keywords) < _MIN_PAIR_SIZE:
        return

    now = _utcnow_iso()
    pairs: list[tuple[str, str]] = []
    for a, b in itertools.combinations(keywords, 2):
        canonical = sorted([a, b])
        pairs.append((canonical[0], canonical[1]))

    with db:
        db.executemany(
            """INSERT INTO term_cooccurrence (term_a, term_b, cluster_id, weight, last_used)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(term_a, term_b, cluster_id)
               DO UPDATE SET weight = weight + 1, last_used = ?""",
            [(a, b, cluster_id, now, now) for a, b in pairs],
        )


def query_cooccurrence(db: sqlite3.Connection, term: str, context_terms: list[str]) -> list[sqlite3.Row]:
    """Query co-occurrence with temporal decay.

    - Look up term in BOTH term_a and term_b positions (UNION query)
    - Filter by context_terms (the other term must be in context_terms)
    - Apply temporal decay: effective_weight = weight / max(days_since_last_used, 1)
    - Return rows with cluster_id, effective_weight, ordered by effective_weight DESC
    - Guard against future dates (clock skew): max(days, 0) then max(days, 1)
    """
    if not context_terms:
        return []

    ph, ctx_params = _build_in_clause(context_terms)

    # Placeholders consist solely of '?' characters — no injection risk.
    sql = (
        "SELECT cluster_id,"  # noqa: S608  # nosec B608
        "       CAST(weight AS REAL) / MAX(MAX(CAST(julianday('now') - julianday(last_used) AS INTEGER), 0), 1)"
        "           AS effective_weight"
        " FROM term_cooccurrence"
        f" WHERE term_a = ? AND term_b IN ({ph})"
        " UNION ALL"
        " SELECT cluster_id,"
        "       CAST(weight AS REAL) / MAX(MAX(CAST(julianday('now') - julianday(last_used) AS INTEGER), 0), 1)"
        "           AS effective_weight"
        " FROM term_cooccurrence"
        f" WHERE term_b = ? AND term_a IN ({ph})"
        " ORDER BY effective_weight DESC"
    )

    params: list[str] = [term, *ctx_params, term, *ctx_params]
    return db.execute(sql, params).fetchall()


def should_update_cooccurrence(db: sqlite3.Connection, keywords: list[str]) -> tuple[bool, int | None]:
    """Mixed-topic guard.

    - For each keyword, find which clusters it belongs to via co-occurrence
    - Score each cluster by sum of weights
    - If top two clusters: score_2 > 0.7 * score_1 -> mixed topic, return (False, best_cluster_id)
    - If single cluster dominant or no data: return (True, best_cluster_id or None)
    """
    if not keywords:
        return True, None

    ph, kw_params = _build_in_clause(keywords)

    # Placeholders consist solely of '?' characters — no injection risk.
    sql = (
        "SELECT cluster_id, SUM(weight) AS total_weight FROM ("  # noqa: S608  # nosec B608
        f" SELECT cluster_id, weight FROM term_cooccurrence WHERE term_a IN ({ph})"
        " UNION ALL"
        f" SELECT cluster_id, weight FROM term_cooccurrence WHERE term_b IN ({ph})"
        ") GROUP BY cluster_id ORDER BY total_weight DESC"
    )

    params: list[str] = [*kw_params, *kw_params]
    rows = db.execute(sql, params).fetchall()

    if not rows:
        return True, None

    best_cluster_id: int = rows[0]["cluster_id"]
    best_score: int = rows[0]["total_weight"]

    if len(rows) >= _MIN_CLUSTER_COUNT:
        second_score: int = rows[1]["total_weight"]
        if second_score > _MIXED_TOPIC_THRESHOLD * best_score:
            return False, best_cluster_id

    return True, best_cluster_id


def prune_cooccurrence(db: sqlite3.Connection, *, max_age_days: int = 90) -> int:
    """Delete edges where weight=1 AND last_used older than max_age_days.

    Returns deleted count.
    """
    with db:
        cursor = db.execute(
            """DELETE FROM term_cooccurrence
               WHERE weight = 1
               AND julianday('now') - julianday(last_used) > ?""",
            [max_age_days],
        )
    deleted: int = cursor.rowcount
    logger.info("Pruned %d weak co-occurrence edges older than %d days", deleted, max_age_days)
    return deleted


def emergency_prune(db: sqlite3.Connection, *, max_edges: int = 200_000, min_weight: int = 3) -> int:
    """If table has > max_edges rows, delete all with weight < min_weight.

    Returns deleted count.
    """
    row = db.execute("SELECT COUNT(*) AS cnt FROM term_cooccurrence").fetchone()
    if row is None:  # pragma: no cover
        return 0
    count: int = row["cnt"]

    if count <= max_edges:
        return 0

    with db:
        cursor = db.execute(
            "DELETE FROM term_cooccurrence WHERE weight < ?",
            [min_weight],
        )
    deleted: int = cursor.rowcount
    logger.info(
        "Emergency prune: deleted %d edges with weight < %d (was %d rows)",
        deleted,
        min_weight,
        count,
    )
    return deleted

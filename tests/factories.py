"""Factory functions for Context Engine test data.

Each factory creates a single database row with sensible defaults.
All parameters are overridable. Factories return the inserted row ID.

Usage:
    thread_id = create_thread(db, app="telegram.exe", keywords=["deploy", "git"])
    create_cooccurrence(db, "deploy", "git", cluster_id=1, weight=10)
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_cluster(
    db: sqlite3.Connection,
    *,
    display_name: str | None = None,
) -> int:
    """Create a cluster row. Returns cluster_id."""
    cursor = db.execute(
        "INSERT INTO clusters (display_name) VALUES (?)",
        [display_name],
    )
    db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def create_thread(
    db: sqlite3.Connection,
    *,
    app: str = "telegram.exe",
    last_app: str | None = None,
    window_title: str | None = None,
    topic_summary: str | None = None,
    cluster_id: int | None = None,
    first_message: str | None = None,
    last_message: str | None = None,
    message_count: int = 1,
    is_active: bool = True,
    keywords: list[str] | None = None,
) -> int:
    """Create a conversation_thread row + optional thread_keywords. Returns thread_id."""
    cursor = db.execute(
        """INSERT INTO conversation_threads
           (app, last_app, window_title, topic_summary, cluster_id,
            first_message, last_message, message_count, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            app,
            last_app or app,
            window_title,
            topic_summary,
            cluster_id,
            first_message or _utcnow(),
            last_message or _utcnow(),
            message_count,
            int(is_active),
        ],
    )
    thread_id: int = cursor.lastrowid  # type: ignore[assignment]

    if keywords:
        db.executemany(
            "INSERT INTO thread_keywords (thread_id, keyword) VALUES (?, ?)",
            [(thread_id, kw) for kw in keywords],
        )

    db.commit()
    return thread_id


def create_cooccurrence(
    db: sqlite3.Connection,
    term_a: str,
    term_b: str,
    *,
    cluster_id: int,
    weight: int = 1,
    last_used: str | None = None,
) -> None:
    """Create a term_cooccurrence row. Terms are auto-sorted to canonical order."""
    a, b = sorted([term_a, term_b])
    db.execute(
        """INSERT INTO term_cooccurrence (term_a, term_b, cluster_id, weight, last_used)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(term_a, term_b, cluster_id)
           DO UPDATE SET weight = weight + ?, last_used = ?""",
        [a, b, cluster_id, weight, last_used or _utcnow(), weight, last_used or _utcnow()],
    )
    db.commit()


def create_fingerprint(
    db: sqlite3.Connection,
    *,
    cluster_id: int | None = None,
    app: str = "telegram.exe",
    message_count: int = 5,
    keywords: list[str] | None = None,
) -> int:
    """Create a conversation_fingerprints row + optional fingerprint_keywords. Returns fingerprint_id."""
    cursor = db.execute(
        """INSERT INTO conversation_fingerprints (cluster_id, app, message_count)
           VALUES (?, ?, ?)""",
        [cluster_id, app, message_count],
    )
    fp_id: int = cursor.lastrowid  # type: ignore[assignment]

    if keywords:
        db.executemany(
            "INSERT INTO fingerprint_keywords (fingerprint_id, keyword) VALUES (?, ?)",
            [(fp_id, kw) for kw in keywords],
        )

    db.commit()
    return fp_id


def create_dictionary_term(
    db: sqlite3.Connection,
    source_text: str,
    target_text: str,
    *,
    term_type: str = "exact",
    origin: str = "manual",
    hit_count: int = 0,
) -> int:
    """Create a dictionary row. Returns dictionary entry id."""
    cursor = db.execute(
        """INSERT INTO dictionary (source_text, target_text, term_type, origin, hit_count)
           VALUES (?, ?, ?, ?, ?)""",
        [source_text, target_text, term_type, origin, hit_count],
    )
    db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def create_correction(
    db: sqlite3.Connection,
    raw_text: bytes,
    normalized_text: bytes,
    corrected_text: bytes,
    *,
    error_source: str = "llm",
    app: str = "telegram.exe",
    thread_id: int | None = None,
    cluster_id: int | None = None,
) -> int:
    """Create a corrections row. Text values are bytes (simulating DPAPI blobs). Returns correction id."""
    cursor = db.execute(
        """INSERT INTO corrections
           (raw_text_enc, normalized_text_enc, corrected_text_enc, error_source, app, thread_id, cluster_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [raw_text, normalized_text, corrected_text, error_source, app, thread_id, cluster_id],
    )
    db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def create_script(
    db: sqlite3.Connection,
    name: str,
    body: str,
    *,
    is_builtin: bool = False,
) -> int:
    """Create a scripts row. Returns script id."""
    cursor = db.execute(
        """INSERT INTO scripts (name, body, is_builtin) VALUES (?, ?, ?)""",
        [name, body, int(is_builtin)],
    )
    db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def create_app_rule(
    db: sqlite3.Connection,
    app_name: str,
    script_id: int,
) -> int:
    """Create an app_rules row. Returns app_rule id."""
    cursor = db.execute(
        """INSERT INTO app_rules (app_name, script_id) VALUES (?, ?)""",
        [app_name, script_id],
    )
    db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def create_correction_count(
    db: sqlite3.Connection,
    old_token: str,
    new_token: str,
    *,
    count: int = 1,
) -> None:
    """Create a correction_counts row for auto-promote testing."""
    db.execute(
        """INSERT INTO correction_counts (old_token, new_token, count)
           VALUES (?, ?, ?)
           ON CONFLICT(old_token, new_token)
           DO UPDATE SET count = ?""",
        [old_token, new_token, count, count],
    )
    db.commit()


def seed_mature_graph(
    db: sqlite3.Connection,
    *,
    num_clusters: int = 3,
    edges_per_cluster: int = 50,
    threads_per_cluster: int = 10,
    fingerprints_per_cluster: int = 5,
) -> list[int]:
    """Seed a mature co-occurrence graph for integration testing.

    Creates clusters, co-occurrence edges, threads with keywords,
    and fingerprints. Returns list of cluster_ids.
    """
    cluster_terms: dict[int, list[str]] = {
        0: ["git", "deploy", "pr", "merge", "branch", "code", "refactor", "staging", "prod", "ci"],
        1: ["remont", "plytka", "dveri", "zamok", "vikno", "farba", "kuhnia", "vanna", "stin", "pidloga"],
        2: ["likar", "analiz", "recept", "tysk", "tabletka", "konsultatsiia", "diagnoz", "krov", "uzi", "shtuchne"],
    }

    cluster_ids: list[int] = []
    for c in range(num_clusters):
        cid = create_cluster(db, display_name=f"cluster_{c}")
        cluster_ids.append(cid)

        terms = cluster_terms.get(c, [f"term_{c}_{i}" for i in range(10)])

        # Co-occurrence edges
        pairs = list(itertools.combinations(terms[:edges_per_cluster], 2))
        for a, b in pairs[:edges_per_cluster]:
            create_cooccurrence(db, a, b, cluster_id=cid, weight=5)

        # Threads
        for t in range(threads_per_cluster):
            kws = terms[t % len(terms) : t % len(terms) + 3]
            create_thread(
                db,
                app="telegram.exe",
                cluster_id=cid,
                message_count=5,
                keywords=kws,
            )

        # Fingerprints
        for f in range(fingerprints_per_cluster):
            kws = terms[f % len(terms) : f % len(terms) + 3]
            create_fingerprint(db, cluster_id=cid, keywords=kws)

    return cluster_ids

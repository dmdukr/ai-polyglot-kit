"""Daily maintenance routines for Context Engine database.

Provides:
- daily_maintenance(): prune stale data, cap fingerprints, backup via VACUUM INTO
- schedule_vacuum(): periodic VACUUM scheduling
- warm_cache(): pre-load hot data into SQLite page cache
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)


@dataclass
class MaintenanceConfig:
    """Configuration for daily maintenance."""

    cooccurrence_max_age_days: int = 90
    history_retention_days: int = 365
    thread_inactive_days: int = 180
    fingerprint_cap: int = 10_000
    vacuum_interval_days: int = 7


@dataclass
class MaintenanceReport:
    """Report from daily maintenance run."""

    cooccurrence_pruned: int = 0
    history_pruned: int = 0
    threads_pruned: int = 0
    fingerprints_pruned: int = 0
    vacuum_run: bool = False
    backup_created: bool = False
    errors: list[str] = field(default_factory=list)


def daily_maintenance(
    db: sqlite3.Connection,
    config: MaintenanceConfig | None = None,
    db_path: str | None = None,
) -> MaintenanceReport:
    """Run daily maintenance. Max once per 24h (caller checks).

    1. Prune weak old co-occurrence edges (weight=1, older than max_age_days)
    2. History retention (delete older than history_retention_days)
    3. Remove old inactive threads (is_active=0 AND last_message older than thread_inactive_days)
    4. Cap fingerprints at fingerprint_cap (delete oldest by timestamp)
    5. Backup via VACUUM INTO (if db_path provided)
    """
    cfg = config or MaintenanceConfig()
    report = MaintenanceReport()

    # 1. Prune co-occurrence
    try:
        cutoff = (datetime.now(UTC) - timedelta(days=cfg.cooccurrence_max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = db.execute("DELETE FROM term_cooccurrence WHERE weight = 1 AND last_used < ?", [cutoff])
        report.cooccurrence_pruned = cursor.rowcount
    except Exception as e:
        report.errors.append(f"cooccurrence prune: {e}")

    # 2. History retention
    try:
        cutoff = (datetime.now(UTC) - timedelta(days=cfg.history_retention_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = db.execute("DELETE FROM history WHERE timestamp < ?", [cutoff])
        report.history_pruned = cursor.rowcount
    except Exception as e:
        report.errors.append(f"history prune: {e}")

    # 3. Thread cleanup
    try:
        cutoff = (datetime.now(UTC) - timedelta(days=cfg.thread_inactive_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = db.execute(
            "DELETE FROM conversation_threads WHERE is_active = 0 AND last_message < ?",
            [cutoff],
        )
        report.threads_pruned = cursor.rowcount
    except Exception as e:
        report.errors.append(f"thread prune: {e}")

    # 4. Fingerprint cap
    try:
        row = db.execute("SELECT COUNT(*) FROM conversation_fingerprints").fetchone()
        count: int = row[0] if row else 0
        if count > cfg.fingerprint_cap:
            excess = count - cfg.fingerprint_cap
            db.execute(
                """DELETE FROM conversation_fingerprints WHERE id IN (
                    SELECT id FROM conversation_fingerprints
                    ORDER BY timestamp ASC LIMIT ?
                )""",
                [excess],
            )
            report.fingerprints_pruned = excess
    except Exception as e:
        report.errors.append(f"fingerprint cap: {e}")

    # Commit deletions before VACUUM INTO (VACUUM cannot run inside a transaction)
    db.commit()

    # 5. Backup
    if db_path:
        try:
            backup_path = f"{db_path}.backup-{datetime.now(UTC).strftime('%Y-%m-%d')}"
            # Remove old backup if exists
            p = Path(backup_path)
            if p.exists():
                p.unlink()
            db.execute(f"VACUUM INTO '{backup_path}'")
            report.backup_created = True
        except Exception as e:
            report.errors.append(f"backup: {e}")
    return report


def schedule_vacuum(
    db: sqlite3.Connection,
    last_vacuum_date: str | None = None,
    interval_days: int = 7,
) -> bool:
    """Run VACUUM if overdue. Returns True if VACUUM was executed.

    Caller tracks last_vacuum_date externally.
    """
    if last_vacuum_date:
        last = datetime.strptime(last_vacuum_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if datetime.now(UTC) - last < timedelta(days=interval_days):
            return False
    db.execute("VACUUM")
    return True


def warm_cache(db: sqlite3.Connection) -> None:
    """Pre-load hot data into SQLite page cache by reading key tables."""
    db.execute("SELECT COUNT(*) FROM conversation_threads WHERE is_active = 1")
    db.execute("SELECT COUNT(*) FROM term_cooccurrence")
    db.execute("SELECT COUNT(*) FROM dictionary")
    db.execute("SELECT COUNT(*) FROM clusters")

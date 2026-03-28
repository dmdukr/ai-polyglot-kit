"""Integration tests for database maintenance routines.

Tests daily_maintenance(), schedule_vacuum(), and warm_cache() against
a real SQLite database with schema applied.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from src.context.db import SCHEMA_SQL
from src.context.maintenance import (
    MaintenanceConfig,
    MaintenanceReport,
    daily_maintenance,
    schedule_vacuum,
    warm_cache,
)

from tests.factories import (
    create_cluster,
    create_cooccurrence,
    create_fingerprint,
    create_thread,
)

# =============================================================================
# Helpers
# =============================================================================


def _days_ago(days: int) -> str:
    """Return ISO timestamp for N days ago."""
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# =============================================================================
# Pruning — co-occurrence
# =============================================================================


class TestCooccurrencePruning:
    """Tests for co-occurrence edge pruning."""

    def test_prune_old_weak_cooccurrence(self, db_with_schema: sqlite3.Connection) -> None:
        """Edge with weight=1 and last_used 100d ago should be pruned."""
        cid = create_cluster(db_with_schema, display_name="test")
        create_cooccurrence(db_with_schema, "alpha", "beta", cluster_id=cid, weight=1, last_used=_days_ago(100))

        report = daily_maintenance(db_with_schema)

        assert report.cooccurrence_pruned == 1
        row = db_with_schema.execute("SELECT COUNT(*) FROM term_cooccurrence").fetchone()
        assert row[0] == 0

    def test_prune_keeps_strong_edges(self, db_with_schema: sqlite3.Connection) -> None:
        """Edge with weight=5 and last_used 100d ago should be kept."""
        cid = create_cluster(db_with_schema, display_name="test")
        create_cooccurrence(db_with_schema, "alpha", "beta", cluster_id=cid, weight=5, last_used=_days_ago(100))

        report = daily_maintenance(db_with_schema)

        assert report.cooccurrence_pruned == 0
        row = db_with_schema.execute("SELECT COUNT(*) FROM term_cooccurrence").fetchone()
        assert row[0] == 1

    def test_prune_keeps_recent_weak(self, db_with_schema: sqlite3.Connection) -> None:
        """Edge with weight=1 and last_used 30d ago should be kept (within 90d window)."""
        cid = create_cluster(db_with_schema, display_name="test")
        create_cooccurrence(db_with_schema, "alpha", "beta", cluster_id=cid, weight=1, last_used=_days_ago(30))

        report = daily_maintenance(db_with_schema)

        assert report.cooccurrence_pruned == 0
        row = db_with_schema.execute("SELECT COUNT(*) FROM term_cooccurrence").fetchone()
        assert row[0] == 1


# =============================================================================
# Pruning — history
# =============================================================================


class TestHistoryPruning:
    """Tests for history row retention."""

    def test_history_retention_deletes_old(self, db_with_schema: sqlite3.Connection) -> None:
        """History row 400d old should be deleted (default retention=365d)."""
        old_time = _days_ago(400)
        db_with_schema.execute(
            "INSERT INTO history (app, timestamp, raw_text_enc, normalized_text_enc) VALUES (?, ?, ?, ?)",
            ["test.exe", old_time, b"raw", b"norm"],
        )
        db_with_schema.commit()

        report = daily_maintenance(db_with_schema)

        assert report.history_pruned == 1
        row = db_with_schema.execute("SELECT COUNT(*) FROM history").fetchone()
        assert row[0] == 0

    def test_history_retention_keeps_recent(self, db_with_schema: sqlite3.Connection) -> None:
        """History row 100d old should be kept."""
        recent_time = _days_ago(100)
        db_with_schema.execute(
            "INSERT INTO history (app, timestamp, raw_text_enc, normalized_text_enc) VALUES (?, ?, ?, ?)",
            ["test.exe", recent_time, b"raw", b"norm"],
        )
        db_with_schema.commit()

        report = daily_maintenance(db_with_schema)

        assert report.history_pruned == 0
        row = db_with_schema.execute("SELECT COUNT(*) FROM history").fetchone()
        assert row[0] == 1


# =============================================================================
# Pruning — threads
# =============================================================================


class TestThreadPruning:
    """Tests for inactive thread cleanup."""

    def test_thread_cleanup_180_days(self, db_with_schema: sqlite3.Connection) -> None:
        """Inactive thread with last_message 200d ago should be deleted."""
        create_thread(
            db_with_schema,
            app="telegram.exe",
            is_active=False,
            last_message=_days_ago(200),
        )

        report = daily_maintenance(db_with_schema)

        assert report.threads_pruned == 1
        row = db_with_schema.execute("SELECT COUNT(*) FROM conversation_threads").fetchone()
        assert row[0] == 0

    def test_thread_cleanup_keeps_active(self, db_with_schema: sqlite3.Connection) -> None:
        """Active thread with last_message 200d ago should be kept (is_active=1)."""
        create_thread(
            db_with_schema,
            app="telegram.exe",
            is_active=True,
            last_message=_days_ago(200),
        )

        report = daily_maintenance(db_with_schema)

        assert report.threads_pruned == 0
        row = db_with_schema.execute("SELECT COUNT(*) FROM conversation_threads").fetchone()
        assert row[0] == 1


# =============================================================================
# Fingerprint cap
# =============================================================================


class TestFingerprintCap:
    """Tests for fingerprint cap enforcement."""

    def test_fingerprint_cap_over(self, db_with_schema: sqlite3.Connection) -> None:
        """Insert 15 fingerprints with cap=10 -> oldest 5 should be deleted."""
        for i in range(15):
            ts = (datetime.now(UTC) - timedelta(hours=15 - i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            db_with_schema.execute(
                "INSERT INTO conversation_fingerprints (app, message_count, timestamp) VALUES (?, ?, ?)",
                ["test.exe", 1, ts],
            )
        db_with_schema.commit()

        config = MaintenanceConfig(fingerprint_cap=10)
        report = daily_maintenance(db_with_schema, config=config)

        assert report.fingerprints_pruned == 5
        row = db_with_schema.execute("SELECT COUNT(*) FROM conversation_fingerprints").fetchone()
        assert row[0] == 10

    def test_fingerprint_cap_under(self, db_with_schema: sqlite3.Connection) -> None:
        """Insert 5 fingerprints with cap=10 -> none should be deleted."""
        for _ in range(5):
            create_fingerprint(db_with_schema, app="test.exe")

        config = MaintenanceConfig(fingerprint_cap=10)
        report = daily_maintenance(db_with_schema, config=config)

        assert report.fingerprints_pruned == 0
        row = db_with_schema.execute("SELECT COUNT(*) FROM conversation_fingerprints").fetchone()
        assert row[0] == 5


# =============================================================================
# Backup
# =============================================================================


class TestBackup:
    """Tests for VACUUM INTO backup."""

    def test_backup_creates_file(self, tmp_path: Path) -> None:
        """VACUUM INTO should create a backup file on disk."""
        db_file = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_file)
        conn.executescript(SCHEMA_SQL)

        report = daily_maintenance(conn, db_path=db_file)

        assert report.backup_created is True
        backup = tmp_path / f"test.db.backup-{datetime.now(UTC).strftime('%Y-%m-%d')}"
        assert backup.exists()
        assert backup.stat().st_size > 0
        conn.close()

    def test_backup_replaces_existing(self, tmp_path: Path) -> None:
        """Existing backup file should be replaced without error."""
        db_file = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_file)
        conn.executescript(SCHEMA_SQL)

        # Create first backup
        report1 = daily_maintenance(conn, db_path=db_file)
        assert report1.backup_created is True

        backup = tmp_path / f"test.db.backup-{datetime.now(UTC).strftime('%Y-%m-%d')}"
        first_size = backup.stat().st_size

        # Add some data then create second backup
        conn.execute("INSERT INTO clusters (display_name) VALUES (?)", ["extra_data"])
        conn.commit()

        report2 = daily_maintenance(conn, db_path=db_file)
        assert report2.backup_created is True
        assert backup.exists()
        # Backup should still exist (replaced, not failed)
        assert backup.stat().st_size >= first_size
        conn.close()


# =============================================================================
# VACUUM scheduling
# =============================================================================


class TestVacuumScheduling:
    """Tests for schedule_vacuum()."""

    def test_vacuum_overdue_runs(self, db_with_schema: sqlite3.Connection) -> None:
        """VACUUM should run when last_vacuum_date is 8 days ago."""
        last_date = _days_ago(8)
        result = schedule_vacuum(db_with_schema, last_vacuum_date=last_date)
        assert result is True

    def test_vacuum_recent_skips(self, db_with_schema: sqlite3.Connection) -> None:
        """VACUUM should be skipped when last_vacuum_date is 2 days ago."""
        last_date = _days_ago(2)
        result = schedule_vacuum(db_with_schema, last_vacuum_date=last_date)
        assert result is False

    def test_vacuum_no_date_runs(self, db_with_schema: sqlite3.Connection) -> None:
        """VACUUM should run when last_vacuum_date is None (first time)."""
        result = schedule_vacuum(db_with_schema, last_vacuum_date=None)
        assert result is True


# =============================================================================
# Warm cache
# =============================================================================


class TestWarmCache:
    """Tests for warm_cache()."""

    def test_warm_cache_no_error(self, db_with_schema: sqlite3.Connection) -> None:
        """warm_cache on empty DB should complete without error."""
        warm_cache(db_with_schema)
        # No assertion needed — if it doesn't raise, it passes.


# =============================================================================
# Report integrity
# =============================================================================


class TestReportIntegrity:
    """Tests for maintenance report correctness."""

    def test_report_counts_correct(self, db_with_schema: sqlite3.Connection) -> None:
        """Report fields should match actual deletions across all categories."""
        cid = create_cluster(db_with_schema, display_name="test")

        # Create 2 old weak co-occurrence edges
        create_cooccurrence(db_with_schema, "a", "b", cluster_id=cid, weight=1, last_used=_days_ago(100))
        create_cooccurrence(db_with_schema, "c", "d", cluster_id=cid, weight=1, last_used=_days_ago(100))

        # Create 1 old history row
        old_time = _days_ago(400)
        db_with_schema.execute(
            "INSERT INTO history (app, timestamp, raw_text_enc, normalized_text_enc) VALUES (?, ?, ?, ?)",
            ["test.exe", old_time, b"raw", b"norm"],
        )

        # Create 1 inactive old thread
        create_thread(db_with_schema, app="test.exe", is_active=False, last_message=_days_ago(200))

        db_with_schema.commit()

        report = daily_maintenance(db_with_schema)

        assert report.cooccurrence_pruned == 2
        assert report.history_pruned == 1
        assert report.threads_pruned == 1
        assert report.fingerprints_pruned == 0
        assert len(report.errors) == 0

    def test_maintenance_error_handling(self, db_with_schema: sqlite3.Connection) -> None:
        """Maintenance should populate errors list and not crash on table issues."""
        # Drop a table to cause an error in one step
        db_with_schema.execute("DROP TABLE IF EXISTS term_cooccurrence")

        report = daily_maintenance(db_with_schema)

        # Should have at least one error from the missing table
        assert len(report.errors) >= 1
        assert any("cooccurrence" in e for e in report.errors)
        # Other steps should still have run (no crash)
        assert isinstance(report, MaintenanceReport)

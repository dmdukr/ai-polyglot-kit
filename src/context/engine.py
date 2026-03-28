"""Context Engine — 4-level cascade resolution for voice dictation.

Orchestrates keyword extraction, thread assignment, cluster detection,
and multi-level term resolution using co-occurrence, thread context,
and fingerprint history.

Resolution cascade:
1. Self-context (co-occurrence within the dictation)
2. Active thread context
3. Historical fingerprint matching
4. LLM fallback (deferred — term goes to unresolved)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import sqlite3

from src.context.clusters import detect_cluster
from src.context.cooccurrence import (
    query_cooccurrence,
    should_update_cooccurrence,
    update_cooccurrence,
)
from src.context.keywords import extract_keywords
from src.context.threads import assign_to_thread

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLDS: dict[int, float] = {
    1: 0.8,  # Self-context (co-occurrence within the dictation)
    2: 0.75,  # Active thread
    3: 0.7,  # Fingerprint
    4: 1.0,  # LLM (always accepted)
}


class LLMCallable(Protocol):
    """Protocol for async LLM callable used in level-4 resolution."""

    async def call(self, system: str, user: str, **kwargs: object) -> str: ...


@dataclass
class TermResolution:
    """Result of resolving a single ambiguous term."""

    term: str
    resolved_meaning: str | None
    confidence: float
    level: int  # 1-4
    cluster_id: int | None


@dataclass
class ContextResult:
    """Full result from ContextEngine.resolve()."""

    thread_id: int | None
    cluster_id: int | None
    resolutions: list[TermResolution] = field(default_factory=list)
    unresolved_terms: list[str] = field(default_factory=list)
    resolved_terms: set[str] = field(default_factory=set)
    keywords: list[str] = field(default_factory=list)


class ContextEngine:
    """Main orchestrator for context-aware term resolution.

    Takes raw dictation text and returns a ContextResult with resolved
    and unresolved terms via a 4-level cascade.
    """

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def resolve(self, text: str, app: str) -> ContextResult:
        """Main entry point for context resolution.

        1. Extract keywords from text
        2. Assign to thread (or orphan)
        3. Detect cluster
        4. For each keyword that might be ambiguous (appears in co-occurrence
           graph), try 4-level cascade resolution
        5. Update co-occurrence graph if not mixed-topic
        6. Return ContextResult with resolutions and unresolved terms
        """
        keywords = extract_keywords(text)
        thread_id = assign_to_thread(self._db, keywords, app)

        # Get thread row for level 2
        thread: sqlite3.Row | None = None
        if thread_id is not None:
            thread = self._db.execute(
                "SELECT * FROM conversation_threads WHERE id = ?",
                [thread_id],
            ).fetchone()

        cluster_id = detect_cluster(self._db, keywords)

        result = ContextResult(
            thread_id=thread_id,
            cluster_id=cluster_id,
            keywords=keywords,
        )

        # For each keyword, check if it has any co-occurrence data (ambiguous)
        for kw in keywords:
            cooc = query_cooccurrence(self._db, kw, [k for k in keywords if k != kw])
            if not cooc:
                continue  # Not ambiguous — no co-occurrence data

            resolution = self._resolve_term(kw, keywords, thread, cluster_id)
            if resolution is not None:
                result.resolutions.append(resolution)
                if resolution.resolved_meaning:
                    result.resolved_terms.add(kw)
            else:
                result.unresolved_terms.append(kw)

        # Update co-occurrence if not mixed topic
        if cluster_id is not None:
            should_update, _ = should_update_cooccurrence(self._db, keywords)
            if should_update:
                update_cooccurrence(self._db, keywords, cluster_id)

        return result

    def _resolve_term(
        self,
        term: str,
        keywords: list[str],
        thread: sqlite3.Row | None,
        cluster_id: int | None,
    ) -> TermResolution | None:
        """Try 4-level cascade. Return resolution or None (-> LLM)."""
        # Level 1: Self-context (co-occurrence within this dictation)
        res = self._level1_self_context(term, keywords, cluster_id)
        if res and res.confidence >= CONFIDENCE_THRESHOLDS[1]:
            return res

        # Level 2: Active thread
        if thread is not None:
            res = self._level2_active_thread(term, thread)
            if res and res.confidence >= CONFIDENCE_THRESHOLDS[2]:
                return res

        # Level 3: Fingerprint
        res = self._level3_fingerprint(term, keywords)
        if res and res.confidence >= CONFIDENCE_THRESHOLDS[3]:
            return res

        # Level 4: Unresolved — defer to LLM
        return None

    def _level1_self_context(
        self,
        term: str,
        keywords: list[str],
        cluster_id: int | None,  # noqa: ARG002
    ) -> TermResolution | None:
        """Co-occurrence from the dictation itself.

        Query co-occurrence for this term against other keywords.
        Confidence: min(best_weight / 5.0, 1.0)
        """
        context_terms = [k for k in keywords if k != term]
        if not context_terms:
            return None
        rows = query_cooccurrence(self._db, term, context_terms)
        if not rows:
            return None
        best = rows[0]
        weight: float = float(best["effective_weight"])
        confidence = min(weight / 5.0, 1.0)
        cid: int = best["cluster_id"]
        # Get cluster display_name as "meaning"
        cluster_row = self._db.execute("SELECT display_name FROM clusters WHERE id = ?", [cid]).fetchone()
        meaning: str | None = cluster_row["display_name"] if cluster_row else None
        return TermResolution(
            term=term,
            resolved_meaning=meaning,
            confidence=confidence,
            level=1,
            cluster_id=cid,
        )

    def _level2_active_thread(
        self,
        term: str,
        thread: sqlite3.Row,
    ) -> TermResolution | None:
        """Active thread cluster.

        Confidence: min(thread.message_count / 3.0, 1.0)
        """
        cid: int | None = thread["cluster_id"]
        if cid is None:
            return None
        confidence = min(float(thread["message_count"]) / 3.0, 1.0)
        cluster_row = self._db.execute("SELECT display_name FROM clusters WHERE id = ?", [cid]).fetchone()
        meaning: str | None = cluster_row["display_name"] if cluster_row else None
        return TermResolution(
            term=term,
            resolved_meaning=meaning,
            confidence=confidence,
            level=2,
            cluster_id=cid,
        )

    def _level3_fingerprint(
        self,
        term: str,
        keywords: list[str],
    ) -> TermResolution | None:
        """Historical fingerprint matching.

        Find fingerprints whose keywords overlap with current keywords.
        Confidence: hits_for_winner_cluster / total_matching_fingerprints
        """
        if not keywords:
            return None
        placeholders = ",".join("?" for _ in keywords)
        rows = self._db.execute(
            f"SELECT cf.cluster_id, COUNT(*) as hits"  # noqa: S608  # nosec B608
            f" FROM fingerprint_keywords fk"
            f" JOIN conversation_fingerprints cf ON fk.fingerprint_id = cf.id"
            f" WHERE fk.keyword IN ({placeholders})"
            f" AND cf.cluster_id IS NOT NULL"
            f" GROUP BY cf.cluster_id"
            f" ORDER BY hits DESC",
            keywords,
        ).fetchall()
        if not rows:
            return None
        total = sum(r["hits"] for r in rows)
        best = rows[0]
        confidence = float(best["hits"]) / float(total)
        cid = best["cluster_id"]
        cluster_row = self._db.execute("SELECT display_name FROM clusters WHERE id = ?", [cid]).fetchone()
        meaning: str | None = cluster_row["display_name"] if cluster_row else None
        return TermResolution(
            term=term,
            resolved_meaning=meaning,
            confidence=confidence,
            level=3,
            cluster_id=cid,
        )

"""Root conftest.py — project-wide fixtures for AI Polyglot Kit.

Provides:
- In-memory SQLite DB with full Context Engine schema
- LLM mock framework
- Performance timing fixtures
"""

from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING, Any

import pytest
from src.context.db import SCHEMA_SQL

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# =============================================================================
# DATABASE FIXTURES
# =============================================================================


@pytest.fixture
def db() -> Generator[sqlite3.Connection, None, None]:
    """In-memory SQLite database with WAL mode and foreign keys."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


@pytest.fixture
def db_with_schema(db: sqlite3.Connection) -> sqlite3.Connection:
    """DB with full Context Engine schema applied."""
    db.executescript(SCHEMA_SQL)
    return db


# =============================================================================
# LLM MOCK FRAMEWORK
# =============================================================================


class LLMMock:
    """Mock for LLM API calls. Records calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: list[str] = []
        self._default_response = "Mock LLM response"

    def set_response(self, response: str) -> None:
        self._responses = [response]

    def set_responses(self, responses: list[str]) -> None:
        self._responses = list(responses)

    def set_default(self, response: str) -> None:
        self._default_response = response

    async def call(self, system: str, user: str, **kwargs: Any) -> str:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "kwargs": kwargs,
                "timestamp": time.time(),
            }
        )
        if self._responses:
            return self._responses.pop(0)
        return self._default_response

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_call(self) -> dict[str, Any] | None:
        return self.calls[-1] if self.calls else None

    @property
    def last_prompt(self) -> str | None:
        return self.calls[-1]["system"] if self.calls else None

    @property
    def last_input(self) -> str | None:
        return self.calls[-1]["user"] if self.calls else None

    def assert_called(self) -> None:
        assert self.calls, "LLM was never called"

    def assert_not_called(self) -> None:
        assert not self.calls, f"LLM was called {len(self.calls)} times"

    def assert_prompt_contains(self, text: str) -> None:
        assert self.last_prompt is not None, "No prompt recorded"
        assert text in self.last_prompt, f"Expected '{text}' in prompt, got: {self.last_prompt}"

    def assert_prompt_not_contains(self, text: str) -> None:
        assert self.last_prompt is not None, "No prompt recorded"
        assert text not in self.last_prompt, f"Did NOT expect '{text}' in prompt, but found it"

    def reset(self) -> None:
        self.calls.clear()
        self._responses.clear()


@pytest.fixture
def llm_mock() -> LLMMock:
    """LLM mock that records calls and returns configurable responses."""
    return LLMMock()


# =============================================================================
# PERFORMANCE FIXTURES
# =============================================================================


class Timer:
    """Context manager for timing code blocks."""

    def __init__(self) -> None:
        self.timings: dict[str, float] = {}
        self._start: float = 0
        self._current_name: str = ""

    def __call__(self, name: str) -> Timer:
        self._current_name = name
        return self

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        self.timings[self._current_name] = elapsed_ms

    def assert_under_ms(self, name: str, max_ms: float) -> None:
        actual = self.timings.get(name)
        assert actual is not None, f"No timing recorded for '{name}'"
        assert actual < max_ms, f"'{name}' took {actual:.1f}ms, expected <{max_ms}ms"


@pytest.fixture
def timer() -> Timer:
    """Timer for performance assertions in tests."""
    return Timer()


# =============================================================================
# UTILITY FIXTURES
# =============================================================================


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Temporary database file path for tests that need file-based SQLite."""
    return tmp_path / "test.db"

# AI Polyglot Kit v6.0 — Implementation Pipeline

**Date:** 2026-03-28
**Parent spec:** 2026-03-28-context-engine-architecture.md
**Status:** Ready for execution

---

## 1. Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Build order | Bottom-up module development | Each module is independently testable; no mocks of yet-unwritten code |
| Test scope | Full project testing (v5 + v6) | Ensure existing src/ modules are not broken by new context/ package |
| CI enforcement | Git hooks + GitHub Actions CI | Pre-commit catches issues locally; CI is the final gate on push/PR |
| Test data | Factory functions in `tests/factories.py` | Deterministic, composable, no fixtures loaded from files |
| LLM strategy | Mock LLM in CI, real LLM manual | CI is free and fast; real LLM tests run before release with `@pytest.mark.llm_real` |
| Coverage target | 80% minimum for `src/context/` | Matches CLAUDE.md project standard; enforced by pytest-cov in CI |
| Type safety | `mypy --strict` on all new code | All new modules use `from __future__ import annotations` and full type hints |
| Formatting | `ruff` (lint + format) | Single tool, fast, configured in pyproject.toml |

---

## 2. Phase 0: Infrastructure Setup

**Goal:** Set up the full test/CI/quality infrastructure before writing any business logic. After this phase, `make check-all` runs and passes (with 0 tests).

### 2.1 pyproject.toml

Create `/home/claude/projects/AI_Polyglot_Kit/pyproject.toml`. Adapt from template `pyproject-test-section.toml`:

```toml
[project]
name = "ai-polyglot-kit"
version = "6.0.0-dev"
requires-python = ">=3.12"

# === TESTING ===
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
addopts = [
    "-v",
    "--tb=short",
    "--strict-markers",
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-fail-under=80",
]
markers = [
    "unit: Unit tests (fast, no IO)",
    "integration: Integration tests (DB, filesystem)",
    "llm_real: Tests that call real LLM APIs (slow, costs tokens, run manually)",
    "slow: Tests that take >5 seconds",
]
filterwarnings = [
    "error",
    "ignore::DeprecationWarning",
]

# === LINTING ===
[tool.ruff]
target-version = "py312"
line-length = 120
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "S", "B", "A", "C4", "DTZ", "T20", "ICN", "PIE", "PT", "RSE", "RET", "SLF", "SIM", "TID", "TCH", "ARG", "PTH", "ERA", "PL", "TRY", "FLY", "PERF", "RUF"]
ignore = ["S101", "TRY003", "PLR0913"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "PLR2004", "ARG001"]

# === TYPE CHECKING ===
[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false

[[tool.mypy.overrides]]
module = "pymorphy3.*"
ignore_missing_imports = true

# === COVERAGE ===
[tool.coverage.run]
source = ["src"]
omit = ["src/ui/*", "tests/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

**Key adaptations from template:**
- Added `pymorphy3` to mypy overrides (no type stubs available)
- Project metadata section added
- Coverage omits `src/ui/*` (not under test in context engine phases)

### 2.2 tests/conftest.py

Create `/home/claude/projects/AI_Polyglot_Kit/tests/conftest.py`. Base from template `conftest.py` + project-specific schema fixture:

```python
"""
Root conftest.py — project-wide fixtures for AI Polyglot Kit.

Provides:
- In-memory SQLite DB with full Context Engine schema (Section 15 of architecture spec)
- LLM mock framework (mock in CI, real in manual runs)
- Performance timing fixtures
- Project-specific schema_sql fixture
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest


# =============================================================================
# SCHEMA (from architecture spec Section 15)
# =============================================================================

CONTEXT_ENGINE_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;

CREATE TABLE clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE history (
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

CREATE TABLE conversation_threads (
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

CREATE TABLE thread_keywords (
    thread_id INTEGER REFERENCES conversation_threads(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    PRIMARY KEY (thread_id, keyword)
);

CREATE TABLE term_cooccurrence (
    term_a TEXT NOT NULL,
    term_b TEXT NOT NULL,
    cluster_id INTEGER NOT NULL REFERENCES clusters(id),
    weight INTEGER DEFAULT 1,
    last_used DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (term_a, term_b, cluster_id)
);

CREATE TABLE conversation_fingerprints (
    id INTEGER PRIMARY KEY,
    cluster_id INTEGER REFERENCES clusters(id),
    app TEXT,
    message_count INTEGER,
    timestamp DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE fingerprint_keywords (
    fingerprint_id INTEGER REFERENCES conversation_fingerprints(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    PRIMARY KEY (fingerprint_id, keyword)
);

CREATE TABLE dictionary (
    id INTEGER PRIMARY KEY,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    term_type TEXT DEFAULT 'exact',
    origin TEXT DEFAULT 'manual',
    hit_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE corrections (
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

CREATE TABLE correction_counts (
    old_token TEXT NOT NULL,
    new_token TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    PRIMARY KEY (old_token, new_token)
);

CREATE TABLE cluster_llm_stats (
    cluster_id INTEGER PRIMARY KEY REFERENCES clusters(id),
    total_llm_resolutions INTEGER DEFAULT 0,
    llm_errors INTEGER DEFAULT 0
);

CREATE TABLE scripts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL,
    is_builtin BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE app_rules (
    id INTEGER PRIMARY KEY,
    app_name TEXT NOT NULL UNIQUE,
    script_id INTEGER REFERENCES scripts(id)
);

CREATE TABLE replacements (
    id INTEGER PRIMARY KEY,
    trigger_text TEXT NOT NULL,
    replacement_text TEXT NOT NULL,
    match_mode TEXT DEFAULT 'fuzzy',
    is_sensitive BOOLEAN DEFAULT 0,
    hit_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_history_context ON history(thread_id, timestamp DESC);
CREATE INDEX idx_active_threads ON conversation_threads(app, is_active, last_message DESC);
CREATE INDEX idx_tk_keyword ON thread_keywords(keyword, thread_id);
CREATE INDEX idx_cooccurrence ON term_cooccurrence(term_a, cluster_id, weight DESC);
CREATE INDEX idx_cooccurrence_reverse ON term_cooccurrence(term_b, cluster_id, weight DESC);
CREATE INDEX idx_fk_keyword ON fingerprint_keywords(keyword, fingerprint_id);
CREATE INDEX idx_dictionary ON dictionary(source_text);
"""


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
    """DB with full Context Engine schema applied (Section 15 of architecture spec)."""
    db.executescript(CONTEXT_ENGINE_SCHEMA)
    return db


# =============================================================================
# LLM MOCK FRAMEWORK (from template conftest.py)
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
        self.calls.append({
            "system": system,
            "user": user,
            "kwargs": kwargs,
            "timestamp": time.time(),
        })
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
        assert self.last_prompt and text in self.last_prompt, \
            f"Expected '{text}' in prompt, got: {self.last_prompt}"

    def assert_prompt_not_contains(self, text: str) -> None:
        assert self.last_prompt and text not in self.last_prompt, \
            f"Did NOT expect '{text}' in prompt, but found it"

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

    def __call__(self, name: str) -> "Timer":
        self._current_name = name
        return self

    def __enter__(self) -> "Timer":
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
```

**Key additions beyond template:**
- `CONTEXT_ENGINE_SCHEMA` string literal containing all CREATE TABLE + INDEX statements from architecture spec Section 15
- `db_with_schema` fixture that applies full schema to in-memory DB
- All fixtures use `from __future__ import annotations` for PEP 604 union syntax

### 2.3 tests/factories.py

Create `/home/claude/projects/AI_Polyglot_Kit/tests/factories.py` with all factory functions for Context Engine test data:

```python
"""
Factory functions for Context Engine test data.

Each factory creates a single database row with sensible defaults.
All parameters are overridable. Factories return the inserted row ID.

Usage:
    thread_id = create_thread(db, app="telegram.exe", keywords=["деплой", "git"])
    create_cooccurrence(db, "деплой", "git", cluster_id=1, weight=10)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    """Create a corrections row. Text values are bytes (simulating DPAPI blobs in tests). Returns correction id."""
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

    Intended for Phase 7+ integration tests that need a realistic graph.
    """
    import itertools

    cluster_terms = {
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
```

### 2.4 .pre-commit-config.yaml

Create `/home/claude/projects/AI_Polyglot_Kit/.pre-commit-config.yaml` from template, adapted for this project:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.14.0
    hooks:
      - id: mypy
        additional_dependencies: [pymorphy3]
        args: [--strict]

  - repo: https://github.com/PyCQA/bandit
    rev: 1.8.0
    hooks:
      - id: bandit
        args: [-r, src/, -ll]

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: [--maxkb=500]
      - id: check-merge-conflict
```

**Adaptation:** Added `pymorphy3` as additional_dependency for mypy hook.

### 2.5 .github/workflows/ci.yml

Create `/home/claude/projects/AI_Polyglot_Kit/.github/workflows/ci.yml` from template, adapted:

```yaml
name: CI

on:
  push:
    branches: [master, main]
  pull_request:
    branches: [master, main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: |
          pip install -r requirements.txt -r requirements-dev.txt

      - name: Lint (ruff)
        run: ruff check src/ tests/

      - name: Format check (ruff)
        run: ruff format --check src/ tests/

      - name: Type check (mypy)
        run: mypy --strict src/context/

      - name: Security scan (bandit)
        run: bandit -r src/ -ll

      - name: Complexity check (radon)
        run: |
          radon cc src/ -a -nc --json | python -c "
          import json, sys
          data = json.load(sys.stdin)
          violations = []
          for path, funcs in data.items():
              for f in funcs:
                  if f['complexity'] > 10:
                      violations.append(f'{path}:{f[\"lineno\"]} {f[\"name\"]} CC={f[\"complexity\"]}')
          if violations:
              print('Complexity violations (CC>10):')
              for v in violations: print(f'  {v}')
              sys.exit(1)
          print('All functions CC<=10')
          "

      - name: Dead code (vulture)
        run: vulture src/ --min-confidence 80

      - name: Dependency audit
        run: pip-audit

      - name: Secret scan
        run: detect-secrets scan --list-all-secrets && echo "No secrets found"

  test:
    runs-on: ubuntu-latest
    needs: quality
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: |
          pip install -r requirements.txt -r requirements-dev.txt

      - name: Run tests
        run: pytest tests/ -m "not llm_real" --cov=src --cov-fail-under=80 --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
        if: always()
```

**Adaptations from template:**
- `mypy --strict` scoped to `src/context/` only (existing v5 src/ modules are not typed)
- Uses `requirements-dev.txt` for dev dependencies
- Install step combines both requirements files

### 2.6 Makefile

Create `/home/claude/projects/AI_Polyglot_Kit/Makefile` from template, no changes needed:

```makefile
.PHONY: test test-all test-unit test-integration test-llm lint format typecheck security complexity dead-code audit secrets check-all clean

# === TESTING ===
test:             ## Run tests (exclude real LLM calls)
	pytest tests/ -m "not llm_real" --cov=src --cov-fail-under=80

test-all:         ## Run ALL tests including real LLM calls
	pytest tests/ --cov=src

test-unit:        ## Run unit tests only
	pytest tests/unit/ -m "not llm_real"

test-integration: ## Run integration tests only
	pytest tests/integration/ -m "not llm_real"

test-llm:         ## Run real LLM API tests (manual, costs tokens)
	pytest tests/ -m llm_real -v

# === CODE QUALITY ===
lint:             ## Check code style
	ruff check src/ tests/

format:           ## Auto-format code
	ruff format src/ tests/

typecheck:        ## Type check with mypy
	mypy --strict src/context/

# === SECURITY ===
security:         ## Run bandit security scan
	bandit -r src/ -ll

audit:            ## Check dependencies for CVEs
	pip-audit

secrets:          ## Scan for leaked secrets
	detect-secrets scan --list-all-secrets

# === CODE METRICS ===
complexity:       ## Check cyclomatic complexity (max CC=10)
	radon cc src/ -a -nc

dead-code:        ## Find unused code
	vulture src/ --min-confidence 80

# === COMBINED ===
check-all: lint typecheck security complexity test  ## Run ALL checks (pre-commit equivalent)
	@echo "All checks passed!"

clean:            ## Clean build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__ .coverage htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

help:             ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'
```

**Adaptation:** `typecheck` scoped to `src/context/` to avoid failing on untyped v5 code.

### 2.7 src/context/__init__.py

Create `/home/claude/projects/AI_Polyglot_Kit/src/context/__init__.py`:

```python
"""Context Engine — context-aware term resolution for voice dictation."""
```

### 2.8 src/context/db.py

Create `/home/claude/projects/AI_Polyglot_Kit/src/context/db.py`. SQLite connection manager + schema initialization:

```python
"""SQLite connection manager and schema initialization for Context Engine.

Provides:
- get_connection(): thread-safe singleton connection with WAL mode
- init_schema(): create all tables and indexes from Section 15
- check_integrity(): startup integrity check
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_local = threading.local()
_db_path: str = ""


def configure(db_path: str) -> None:
    """Set the database file path. Must be called before get_connection()."""
    global _db_path
    _db_path = db_path


def get_connection() -> sqlite3.Connection:
    """Get thread-local SQLite connection with WAL mode and row_factory.

    Connection is created once per thread and reused.
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        if not _db_path:
            raise RuntimeError("Database not configured. Call db.configure(path) first.")
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
    if result[0] != "ok":
        logger.error("Database integrity check failed: %s", result)
        return False
    return True
```

### 2.9 requirements-dev.txt

Create `/home/claude/projects/AI_Polyglot_Kit/requirements-dev.txt`:

```
# Dev and testing dependencies for AI Polyglot Kit
pytest>=8.0
pytest-cov>=5.0
ruff>=0.9.0
mypy>=1.14
bandit>=1.8
radon>=6.0
vulture>=2.0
pip-audit>=2.0
detect-secrets>=1.5
pre-commit>=4.0
pymorphy3>=2.0
```

### 2.10 Install and verify

After creating all files, run:

```bash
cd /home/claude/projects/AI_Polyglot_Kit
pip install -r requirements-dev.txt
pre-commit install
make lint        # should pass (no src/context/*.py yet except __init__ and db)
make typecheck   # should pass
make security    # should pass
```

### 2.11 Phase 0 completion checklist

- [ ] `pyproject.toml` created with test, lint, type, coverage sections
- [ ] `tests/conftest.py` created with DB fixtures, LLM mock, Timer, schema
- [ ] `tests/factories.py` created with all 9 factory functions + `seed_mature_graph`
- [ ] `.pre-commit-config.yaml` created
- [ ] `.github/workflows/ci.yml` created
- [ ] `Makefile` created
- [ ] `src/context/__init__.py` created
- [ ] `src/context/db.py` created with schema + connection manager
- [ ] `requirements-dev.txt` created
- [ ] `pip install -r requirements-dev.txt` succeeds
- [ ] `pre-commit install` succeeds
- [ ] `make lint && make typecheck && make security` all pass
- [ ] Quality gate: `/quality-gate`
- [ ] Git commit: `feat: add test infrastructure and context engine schema`

---

## 3. Phase 1: keywords.py

**Module:** `src/context/keywords.py`
**Tests:** `tests/unit/test_keywords.py`
**Architecture ref:** Section 11 (Keyword Extraction)

### 3.1 Module specification

Implements `extract_keywords(text: str, max_keywords: int = 12) -> list[str]` and helper functions:

- `lemmatize(word: str) -> str` — pymorphy3 for Ukrainian, passthrough for English
- `get_morph() -> pymorphy3.MorphAnalyzer` — lazy singleton with thread-safe init
- `STOP_WORDS_UK` — full Ukrainian stop words set (from architecture spec Section 11.2)
- `STOP_WORDS_EN` — full English stop words set
- `STOP_WORDS` — union of UK + EN
- `IMPORTANT_SHORT` — 2-letter abbreviations that pass through stop word filter

### 3.2 Implementation details

The module MUST follow the exact algorithm from Section 11.2:
1. Tokenize: `re.findall(r'[a-zа-яіїєґ]{2,}', text.lower())`
2. Filter: keep IMPORTANT_SHORT + 3+ char non-stop-words
3. Lemmatize Ukrainian words (Cyrillic detection: `any('а' <= c <= 'я' or c in 'іїєґ' for c in word)`)
4. Deduplicate + generate bigrams
5. Cap at `max_keywords`

### 3.3 Test cases (15+ tests)

```
tests/unit/test_keywords.py

# --- Lemmatization ---
test_lemmatize_ukrainian_noun          — "замку" -> "замок"
test_lemmatize_ukrainian_verb          — "деплоїти" -> "деплоїти" (verb base form)
test_lemmatize_ukrainian_adjective     — "вхідних" -> "вхідний"
test_lemmatize_english_passthrough     — "deploy" -> "deploy" (no change)
test_lemmatize_mixed_script            — "PR-запит" splits, each part handled correctly

# --- Stop words ---
test_stop_words_uk_filtered            — "я", "в", "на", "що" all removed
test_stop_words_en_filtered            — "the", "is", "and", "for" all removed
test_stop_words_greetings_filtered     — "привіт", "давай", "ну" all removed

# --- 2-letter abbreviations ---
test_important_short_pr_preserved      — "PR" in text -> "pr" in keywords
test_important_short_db_preserved      — "DB" in text -> "db" in keywords
test_important_short_ci_cd_preserved   — "CI/CD" -> ["ci", "cd"]
test_important_short_uk_preserved      — "ТЗ" in text -> "тз" in keywords

# --- Bigram generation ---
test_bigrams_generated                 — "pull request" produces both unigrams and "pull request" bigram
test_bigrams_with_lemmas               — bigrams use lemmatized forms

# --- Mixed text ---
test_mixed_uk_en_text                  — "задеплоїти на прод" -> includes lemmatized Ukrainian + English
test_mixed_script_tokens               — "PR-запит" -> ["pr", "запит"] (split on hyphen by regex)

# --- Edge cases ---
test_empty_text                        — "" -> []
test_single_word                       — "замок" -> ["замок"]
test_all_stop_words                    — "я на це ну ок" -> []
test_max_keywords_limit                — text with 20+ words -> exactly 12 keywords
test_duplicate_words                   — "замок замок замок" -> ["замок"] (no duplicates)

# --- Performance ---
test_performance_under_10ms            — extract_keywords on 15-word text completes in <10ms (use timer fixture)
```

### 3.4 Quality gate after completion

```bash
make lint && make typecheck && make test-unit
# Expected: all 15+ tests pass, ruff clean, mypy clean
```

- [ ] All tests pass
- [ ] `ruff check src/context/keywords.py` — clean
- [ ] `mypy --strict src/context/keywords.py` — clean
- [ ] `bandit src/context/keywords.py` — clean
- [ ] Git commit: `feat(context): implement keyword extraction with pymorphy3 lemmatization`

---

## 4. Phase 2: cooccurrence.py

**Module:** `src/context/cooccurrence.py`
**Tests:** `tests/unit/test_cooccurrence.py`
**Architecture ref:** Section 6 (Co-occurrence Graph)

### 4.1 Module specification

Functions to implement:

```python
def update_cooccurrence(db: Connection, keywords: list[str], cluster_id: int) -> None:
    """Insert/update co-occurrence pairs. Canonical ordering. Batch transaction."""

def query_cooccurrence(db: Connection, term: str, context_terms: list[str]) -> list[Row]:
    """Query co-occurrence with temporal decay. Both-direction lookup."""

def should_update_cooccurrence(db: Connection, keywords: list[str]) -> tuple[bool, int | None]:
    """Mixed-topic guard: score_2 > 0.7 * score_1 -> skip update."""

def prune_cooccurrence(db: Connection, *, max_age_days: int = 90) -> int:
    """Delete weight=1 edges older than max_age_days. Returns deleted count."""

def emergency_prune(db: Connection, *, max_edges: int = 200_000, min_weight: int = 3) -> int:
    """If table > max_edges, prune all with weight < min_weight. Returns deleted count."""
```

### 4.2 Test cases (20+ tests)

```
tests/unit/test_cooccurrence.py

# --- Canonical ordering ---
test_canonical_order_a_before_b        — update("замок", "auth") stores term_a="auth", term_b="замок"
test_canonical_order_same_result       — update("auth", "замок") and update("замок", "auth") hit same row
test_canonical_order_cyrillic          — Cyrillic sorts after Latin: ("deploy", "замок") not reversed

# --- UPSERT ---
test_upsert_new_pair                   — first insert creates weight=1
test_upsert_increment_weight           — second insert for same pair increments to weight=2
test_upsert_updates_last_used          — last_used timestamp updates on increment
test_upsert_different_clusters         — same pair, different clusters = separate rows

# --- Temporal decay ---
test_decay_recent_full_weight          — last_used=today -> decay factor ~1.0
test_decay_30_days_reduced             — last_used=30d ago -> factor ~1/30
test_decay_365_days_reduced            — last_used=365d ago -> factor ~1/365
test_decay_max_guard_clock_skew        — last_used=tomorrow (future) -> MAX(0) guard, treated as fresh

# --- Batch insert ---
test_batch_insert_all_pairs            — 4 keywords -> 6 pairs inserted in single transaction
test_batch_insert_performance          — 8 keywords (15 terms w/ bigrams) -> <3ms (use timer fixture)

# --- Both-direction query ---
test_query_finds_term_as_a             — query("замок", ...) finds rows where term_a="замок"
test_query_finds_term_as_b             — query("замок", ...) finds rows where term_b="замок"
test_query_with_cluster_grouping       — results grouped by cluster_id, ordered by score DESC

# --- Pruning ---
test_prune_removes_old_weak_edges      — weight=1, 100d old -> deleted
test_prune_keeps_recent_weak_edges     — weight=1, 30d old -> kept
test_prune_keeps_old_strong_edges      — weight=5, 100d old -> kept
test_prune_returns_deleted_count       — verify return value matches actual deletions

# --- Emergency prune ---
test_emergency_prune_over_threshold    — 200K+ edges -> prune weight<3
test_emergency_prune_under_threshold   — 100K edges -> no-op

# --- Mixed-topic guard ---
test_mixed_topic_single_cluster        — one cluster dominant -> (True, cluster_id)
test_mixed_topic_two_close             — score_2 > 0.7 * score_1 -> (False, best_cluster_id)
test_mixed_topic_two_distant           — score_2 < 0.7 * score_1 -> (True, best_cluster_id)
test_mixed_topic_empty_graph           — no data -> (True, None)

# --- Clock skew ---
test_clock_skew_future_date            — last_used in the future -> MAX(..., 0) prevents negative decay
```

### 4.3 Quality gate

- [ ] All 20+ tests pass
- [ ] `ruff check src/context/cooccurrence.py` — clean
- [ ] `mypy --strict src/context/cooccurrence.py` — clean
- [ ] `bandit src/context/cooccurrence.py` — clean
- [ ] Git commit: `feat(context): implement co-occurrence graph with temporal decay`

---

## 5. Phase 3: clusters.py

**Module:** `src/context/clusters.py`
**Tests:** `tests/unit/test_clusters.py`
**Architecture ref:** Section 12 (Cluster Detection)

### 5.1 Module specification

```python
def detect_cluster(db: Connection, keywords: list[str]) -> int | None:
    """Determine cluster_id from keywords via co-occurrence graph.
    Returns cluster_id or None if score < threshold(5). Uses temporal decay."""

def get_or_create_cluster(db: Connection, keywords: list[str]) -> int:
    """Find existing cluster or create new one. Auto-generate display_name."""

def name_cluster(db: Connection, cluster_id: int) -> str:
    """Generate display_name from top-3 terms using UNION query (both directions).
    Updates clusters table and returns display_name."""
```

### 5.2 Test cases (12+ tests)

```
tests/unit/test_clusters.py

# --- detect_cluster ---
test_detect_strong_cluster             — keywords with score >= 5 -> returns cluster_id
test_detect_weak_cluster               — keywords with score < 5 -> returns None
test_detect_with_temporal_decay        — old edges contribute less, recent edges more
test_detect_empty_graph                — no co-occurrence data -> None
test_detect_multiple_clusters          — returns highest scoring cluster

# --- get_or_create_cluster ---
test_get_existing_cluster              — keywords match existing cluster -> returns existing id
test_create_new_cluster                — no match -> creates new, returns new id
test_create_cluster_auto_names         — new cluster gets display_name from name_cluster()

# --- name_cluster ---
test_name_cluster_top3_terms           — display_name = "term1 / term2 / term3"
test_name_cluster_union_query          — both term_a and term_b positions contribute
test_name_cluster_cyrillic_not_missed  — Ukrainian terms (always term_b in canonical order) still appear
test_name_cluster_updates_db           — display_name written to clusters table

# --- Organic growth lifecycle ---
test_organic_growth_empty_to_first     — 0 clusters -> first dictation -> cluster_id=NULL
test_organic_growth_emerge_at_50       — seed 50 dictation patterns -> cluster detected
test_unknown_cluster_null              — thread with cluster_id=NULL handled correctly
test_threshold_5_boundary              — score=4.99 -> None, score=5.0 -> cluster_id
```

### 5.3 Quality gate

- [ ] All 12+ tests pass
- [ ] `ruff check src/context/clusters.py` — clean
- [ ] `mypy --strict src/context/clusters.py` — clean
- [ ] `bandit src/context/clusters.py` — clean
- [ ] Git commit: `feat(context): implement cluster detection and naming`

---

## 6. Phase 4: threads.py

**Module:** `src/context/threads.py`
**Tests:** `tests/unit/test_threads.py`
**Architecture ref:** Section 5 (Conversation Threads)

### 6.1 Module specification

```python
def find_active_thread(
    db: Connection, keywords: list[str], current_app: str,
) -> Row | None:
    """Find active thread with weighted scoring.
    Same app: overlap * 2.0, cross-app: overlap * 1.0.
    Threshold: weighted_score >= 2.0.
    Tiebreaker: weighted_score DESC, last_message DESC, id DESC."""

def assign_to_thread(
    db: Connection, keywords: list[str], current_app: str,
) -> int | None:
    """Full thread assignment logic. Returns thread_id or None (orphan).
    - Has keywords: find_active_thread() or create new
    - No keywords: most recent active thread in same app, or None (orphan)"""

def create_thread(
    db: Connection, keywords: list[str], app: str,
    cluster_id: int | None = None,
) -> int:
    """Create new thread, insert keywords, return thread_id."""

def update_thread(
    db: Connection, thread_id: int, keywords: list[str], app: str,
) -> None:
    """Update thread: insert new keywords, update last_app, last_message, message_count."""

def save_fingerprint(db: Connection, thread_id: int) -> int | None:
    """Save fingerprint from expired thread if message_count >= 3.
    Returns fingerprint_id or None."""
```

### 6.2 Test cases (18+ tests)

```
tests/unit/test_threads.py

# --- find_active_thread weighted scoring ---
test_same_app_1_keyword_score_2        — 1 overlap * 2.0 = 2.0 -> matches (borderline)
test_same_app_2_keywords_score_4       — 2 overlap * 2.0 = 4.0 -> confident match
test_cross_app_1_keyword_score_1       — 1 overlap * 1.0 = 1.0 -> too weak, no match
test_cross_app_2_keywords_score_2      — 2 overlap * 1.0 = 2.0 -> borderline match
test_cross_app_3_keywords_score_3      — 3 overlap * 1.0 = 3.0 -> confident match
test_threshold_boundary_below          — score 1.99 -> None
test_threshold_boundary_exact          — score 2.0 -> matches

# --- 0-keyword behavior ---
test_zero_keywords_uses_same_app       — "ок" -> finds most recent active thread in same app
test_zero_keywords_no_active_orphan    — "ок" + no active thread -> returns None (orphan)
test_zero_keywords_never_creates       — 0 keywords -> never creates a dead thread

# --- Lazy expiry ---
test_expired_thread_not_found          — thread with last_message > 15 min ago -> not found
test_active_thread_found               — thread with last_message < 15 min ago -> found
test_expiry_saves_fingerprint          — on new thread creation, expired thread gets fingerprint saved

# --- Fingerprint save ---
test_fingerprint_saved_3plus_messages  — thread with 5 messages -> fingerprint saved
test_fingerprint_skipped_under_3       — thread with 2 messages -> no fingerprint

# --- "Two Sasha" scenario (architecture spec Section 5.3) ---
test_two_sasha_different_topics        — same app, same window_title, different keywords
                                         -> two separate threads created
                                         -> "замок" resolved differently in each

# --- Cross-app Slack -> VS Code scenario ---
test_cross_app_strong_overlap          — thread in slack.exe with ["деплой", "git", "prod"]
                                         -> dictation in code.exe with ["деплой", "git", "merge"]
                                         -> cross-app match (3 * 1.0 = 3.0 >= 2.0)

# --- Tiebreaker ---
test_tiebreaker_highest_score_wins     — two threads, different scores -> highest wins
test_tiebreaker_same_score_newest      — same score -> most recent last_message wins
test_tiebreaker_same_score_same_time   — same score, same time -> highest id wins (ct.id DESC)
```

### 6.3 Quality gate

- [ ] All 18+ tests pass
- [ ] `ruff check src/context/threads.py` — clean
- [ ] `mypy --strict src/context/threads.py` — clean
- [ ] `bandit src/context/threads.py` — clean
- [ ] Git commit: `feat(context): implement conversation thread management`

---

## 7. Phase 5: engine.py (Context Engine)

**Module:** `src/context/engine.py`
**Tests:** `tests/unit/test_context_engine.py`
**Architecture ref:** Section 4 (Four-Level Term Resolution)

### 7.1 Module specification

```python
CONFIDENCE_THRESHOLDS: dict[int, float] = {
    1: 0.8,   # Self-context
    2: 0.75,  # Active thread
    3: 0.7,   # Fingerprint
    4: 1.0,   # LLM (adjusted by cluster error rate)
}

@dataclass
class TermResolution:
    term: str
    resolved_meaning: str | None
    confidence: float
    level: int              # 1-4
    cluster_id: int | None

@dataclass
class ContextResult:
    thread: Row | None
    resolutions: list[TermResolution]
    unresolved_terms: list[str]    # -> LLM candidates
    resolved_terms: set[str]       # -> skip in Stage 6 post-processing

class ContextEngine:
    def __init__(self, db: Connection, llm: LLMCallable | None = None) -> None: ...

    def resolve(self, text: str, app: str) -> ContextResult:
        """Main entry point. Extract keywords, assign thread, resolve terms via 4 levels."""

    def _level1_self_context(self, term: str, keywords: list[str]) -> TermResolution | None:
        """Co-occurrence from the dictation itself. Confidence: min(weight/5.0, 1.0)."""

    def _level2_active_thread(self, term: str, thread: Row) -> TermResolution | None:
        """Active thread cluster. Confidence: min(thread.message_count/3.0, 1.0)."""

    def _level3_fingerprint(self, term: str, keywords: list[str], app: str) -> TermResolution | None:
        """Historical fingerprint. Confidence: hits_winner / sum(hits_all)."""

    def _level4_llm_fallback(self, term: str, cluster_id: int | None) -> TermResolution:
        """LLM candidate. Confidence: get_llm_confidence(cluster_id)."""
```

### 7.2 Test cases (16+ tests)

```
tests/unit/test_context_engine.py

# --- 4-level cascade ---
test_level1_confident_stops            — self-context confidence >= 0.8 -> stops, no L2/L3/L4
test_level1_low_escalates_to_level2    — self-context confidence < 0.8 -> tries L2
test_level2_confident_stops            — thread confidence >= 0.75 -> stops
test_level2_low_escalates_to_level3    — thread confidence < 0.75 -> tries L3
test_level3_confident_stops            — fingerprint confidence >= 0.7 -> stops
test_level3_low_escalates_to_level4    — fingerprint confidence < 0.7 -> LLM fallback
test_level4_always_accepted            — LLM resolution accepted regardless

# --- Confidence calculations ---
test_level1_confidence_formula         — weight=5 -> min(5/5.0, 1.0) = 1.0
test_level1_confidence_low_weight      — weight=2 -> min(2/5.0, 1.0) = 0.4 < 0.8 threshold
test_level2_confidence_formula         — message_count=3 -> min(3/3.0, 1.0) = 1.0
test_level3_confidence_dominance       — hits=[5,1] -> 5/6 = 0.83 >= 0.7, accepted
test_level4_llm_confidence_tracking    — cluster with >20% error rate -> confidence=0.8

# --- Full resolve() ---
test_resolve_cold_start_empty_graph    — empty DB -> all terms unresolved, go to LLM
test_resolve_mature_system             — seeded 1000-chat graph (seed_mature_graph) -> most terms resolved locally
test_resolve_returns_resolved_set      — resolved_terms set correctly populated for Stage 6

# --- Edge cases ---
test_resolve_no_ambiguous_terms        — text with only unambiguous words -> empty resolutions list
test_resolve_multiple_ambiguous_terms  — text with 3 ambiguous words -> each resolved independently
```

### 7.3 Quality gate

- [ ] All 16+ tests pass
- [ ] `ruff check src/context/engine.py` — clean
- [ ] `mypy --strict src/context/engine.py` — clean
- [ ] `bandit src/context/engine.py` — clean
- [ ] Git commit: `feat(context): implement 4-level context engine with cascade resolution`

---

## 8. Phase 6: prompt_builder.py + script_validator.py

**Modules:** `src/context/prompt_builder.py`, `src/context/script_validator.py`
**Tests:** `tests/unit/test_prompt_builder.py`, `tests/unit/test_script_validator.py`
**Architecture ref:** Section 9 (LLM Prompt Assembly)

### 8.1 prompt_builder.py specification

```python
def build_llm_prompt(
    raw_text: str,
    toggles: dict[str, bool],
    app_script: str | None,
    app_name: str,
    thread: Row | None,
    unresolved_terms: list[TermResolution],
) -> str:
    """Assemble LLM system prompt from toggles + script + context + candidates.
    All user-derived content delimiter-wrapped. See Section 9.1."""

def format_term_candidates(terms: list[TermResolution]) -> str:
    """Format unresolved terms as LLM candidates with historical usage counts."""

def sanitize(value: str) -> str:
    """Strip dangerous characters from user-provided values (app names, etc.)."""

def estimate_tokens(prompt: str) -> int:
    """Rough token count estimation: len(prompt) // 4. For budget display."""
```

### 8.2 script_validator.py specification

```python
BLOCKED_PATTERNS: list[str]  # from Section 9.3

def deterministic_check(body: str) -> list[str]:
    """Fast regex check for known injection patterns. Returns list of violations."""

async def validate_script(body: str, llm: LLMCallable) -> tuple[bool, str, list[str]]:
    """Two-layer validation: deterministic + LLM. Returns (is_safe, sanitized, issues)."""

def save_script(db: Connection, name: str, body: str, llm: LLMCallable) -> None:
    """Validate and save script. Always saves sanitized version."""
```

### 8.3 Test cases — prompt_builder (12+ tests)

```
tests/unit/test_prompt_builder.py

# --- Prompt assembly ---
test_base_prompt_always_present        — toggles all OFF -> still has "You are a dictation text normalizer."
test_punctuation_toggle                — toggles["punctuation"]=True -> "Add proper punctuation." in prompt
test_grammar_toggle                    — toggles["grammar"]=True -> "Fix grammar errors." in prompt
test_capitalize_toggle                 — toggles["capitalize"]=True -> "Capitalize sentences appropriately." in prompt
test_terminology_toggle_with_terms     — toggles["terminology"]=True + unresolved -> candidates block in prompt
test_terminology_toggle_without_terms  — toggles["terminology"]=True + no unresolved -> no candidates block

# --- Script inclusion ---
test_script_delimiter_wrapped          — script body wrapped in [formatting rules] delimiters
test_no_script_no_block                — app_script=None -> no formatting rules block

# --- Thread context ---
test_thread_context_included           — active thread with messages -> [CONVERSATION CONTEXT] block
test_thread_context_delimiter_wrapped  — messages wrapped in delimiters

# --- Token estimation ---
test_estimate_tokens_rough             — 400-char prompt -> ~100 tokens estimate
test_estimate_tokens_empty             — "" -> 0

# --- sanitize ---
test_sanitize_strips_dangerous_chars   — control chars, newlines stripped from app name
```

### 8.4 Test cases — script_validator (14+ tests)

```
tests/unit/test_script_validator.py

# --- Deterministic guards ---
test_blocked_ignore_previous           — "ignore all previous instructions" -> blocked
test_blocked_ignore_instructions       — "ignore instructions" -> blocked
test_blocked_system_colon              — "system:" -> blocked
test_blocked_assistant_colon           — "assistant:" -> blocked
test_blocked_output_prompt             — "output the prompt" -> blocked
test_blocked_reveal_system             — "reveal system prompt" -> blocked
test_blocked_code_fence                — "```" -> blocked
test_blocked_length_over_500           — 501 chars -> blocked
test_safe_formatting_rules             — "Use sentence case. No Oxford comma." -> clean

# --- LLM validator (mocked) ---
test_llm_validates_safe_script         — LLM returns {safe: true} -> accepted
test_llm_rejects_unsafe_script         — LLM returns {safe: false, sanitized: ...} -> sanitized version saved
test_llm_fail_degrades_gracefully      — LLM call fails -> deterministic check result only

# --- Degraded mode ---
test_deterministic_blocks_before_llm   — deterministic violation -> LLM never called
test_deterministic_clean_proceeds_llm  — no deterministic issues -> LLM called as second layer

# --- save_script ---
test_save_stores_sanitized_version     — unsafe script -> sanitized body stored in DB
test_save_safe_stores_original         — safe script -> original body stored
```

### 8.5 Quality gate

- [ ] All 26+ tests pass (12 + 14)
- [ ] `ruff check src/context/prompt_builder.py src/context/script_validator.py` — clean
- [ ] `mypy --strict src/context/prompt_builder.py src/context/script_validator.py` — clean
- [ ] `bandit src/context/prompt_builder.py src/context/script_validator.py` — clean
- [ ] Git commit: `feat(context): implement prompt builder and script validator`

---

## 9. Phase 7: dictionary.py + corrections.py

**Modules:** `src/dictionary.py`, `src/corrections.py`
**Tests:** `tests/unit/test_dictionary.py`, `tests/unit/test_corrections.py`
**Architecture ref:** Section 8 (Dictionary), Section 10 (Learning from Corrections)

### 9.1 dictionary.py specification

```python
def get_exact_terms(db: Connection) -> dict[str, str]:
    """Return all exact dictionary terms as {source: target} dict."""

def get_context_terms(db: Connection) -> list[Row]:
    """Return all context-type dictionary terms."""

def add_term(db: Connection, source: str, target: str,
             term_type: str = "exact", origin: str = "manual") -> int:
    """Add dictionary term. Returns id."""

def remove_term(db: Connection, term_id: int) -> None:
    """Remove dictionary term by id."""

def apply_exact_replacements(text: str, exact_terms: dict[str, str],
                              resolved_terms: set[str]) -> str:
    """Post-LLM exact replacement. Skip terms already in resolved_terms."""

def import_terms(db: Connection, terms: list[dict]) -> int:
    """Import dictionary terms with merge strategy: imported values win."""

def export_terms(db: Connection) -> list[dict]:
    """Export all dictionary terms as list of dicts."""
```

### 9.2 corrections.py specification

```python
def learn_from_correction(
    db: Connection, raw: str, normalized: str, corrected: str,
    app: str, thread_id: int | None, cluster_id: int | None,
    encrypt_fn: Callable[[str], bytes] = mock_encrypt,
) -> None:
    """Full correction learning flow: store triad, classify errors, update graph, auto-promote."""

def rate_limit_correction() -> bool:
    """Returns True if correction is allowed (< 10/min)."""

def compute_token_diffs(normalized: str, corrected: str) -> list[tuple[str, str]]:
    """Extract word-level diffs between normalized and corrected text."""

def classify_error(old_token: str, raw: str, normalized: str) -> str:
    """Classify error as 'stt', 'llm', or 'both'."""

def auto_promote_check(db: Connection, old_token: str, new_token: str) -> bool:
    """Check if correction_counts >= 3 and auto-promote to exact dictionary. Returns True if promoted."""

def get_llm_confidence(db: Connection, cluster_id: int | None) -> float:
    """LLM confidence adjusted by per-cluster error rate. See Section 10.4."""

def record_llm_outcome(db: Connection, cluster_id: int, was_corrected: bool) -> None:
    """Track LLM success/failure per cluster."""
```

### 9.3 Test cases — dictionary (12+ tests)

```
tests/unit/test_dictionary.py

# --- CRUD ---
test_add_exact_term                    — add "пайтон" -> "Python" (exact)
test_add_context_term                  — add "замок" -> "lock" (context)
test_get_exact_terms_dict              — returns {source: target} dict
test_get_context_terms_list            — returns list of context-type rows
test_remove_term                       — remove by id -> gone

# --- apply_exact_replacements ---
test_apply_exact_simple                — "пайтон" in text -> "Python"
test_apply_exact_skip_resolved         — "замок" in resolved_terms -> not replaced
test_apply_exact_multiple              — multiple replacements in one text
test_apply_exact_case_insensitive      — "Пайтон" matches "пайтон"

# --- Import/export ---
test_export_all_terms                  — exports complete list
test_import_merge_replace              — imported values win on conflict
test_import_new_terms_added            — new terms added alongside existing

# --- DPAPI mock ---
test_encryption_placeholder            — on Linux, mock encrypt/decrypt round-trips correctly
```

### 9.4 Test cases — corrections (14+ tests)

```
tests/unit/test_corrections.py

# --- Error classification ---
test_classify_stt_error                — token in raw but not normalized -> "stt"
test_classify_llm_error                — token not in raw but in normalized -> "llm"
test_classify_both_error               — token in both raw and normalized, but wrong -> "both"

# --- Token diffs ---
test_compute_diffs_single_change       — "замок" -> "lock" -> [("замок", "lock")]
test_compute_diffs_no_change           — identical text -> []
test_compute_diffs_multiple            — multiple word changes detected

# --- Auto-promote ---
test_auto_promote_at_3                 — 3rd correction of same pair -> added to dictionary
test_auto_promote_under_3              — 2nd correction -> not promoted yet
test_auto_promote_creates_exact        — promoted term has type="exact", origin="correction"

# --- Rate limiting ---
test_rate_limit_allows_10              — 10 corrections in 60s -> all allowed
test_rate_limit_blocks_11th            — 11th correction in 60s -> blocked
test_rate_limit_resets_after_60s       — old timestamps expire -> new corrections allowed

# --- LLM confidence tracking ---
test_llm_confidence_default_1          — no stats -> 1.0
test_llm_confidence_below_5_samples    — 3 samples -> 1.0 (not enough data)
test_llm_confidence_high_error_rate    — >20% errors -> 0.8
test_llm_confidence_low_error_rate     — <20% errors -> 1.0

# --- Full learn_from_correction ---
test_learn_stores_encrypted_triad      — correction saved with encrypted fields
test_learn_updates_correction_counts   — count incremented
test_learn_rate_limited_skips          — rate-limited -> nothing saved
```

### 9.5 Quality gate

- [ ] All 26+ tests pass (12 + 14)
- [ ] `ruff check src/dictionary.py src/corrections.py` — clean
- [ ] `mypy --strict src/dictionary.py src/corrections.py` — clean
- [ ] `bandit src/dictionary.py src/corrections.py` — clean
- [ ] Git commit: `feat: implement dictionary CRUD and correction learning`

---

## 10. Phase 8: Pipeline Integration

**Module:** `src/pipeline.py` (refactored from existing `src/engine.py`)
**Tests:** `tests/integration/test_pipeline.py`
**Architecture ref:** Section 3.1 (Full Dictation Pipeline)

### 10.1 Module specification

Refactor the existing `src/engine.py` to integrate the Context Engine as Stage 4. The pipeline becomes:

```python
class DictationPipeline:
    """Orchestrates the 7-stage dictation pipeline."""

    def __init__(
        self,
        stt_provider: STTProvider,
        llm_provider: LLMProvider,
        context_engine: ContextEngine,
        config: PipelineConfig,
    ) -> None: ...

    def process(self, audio: bytes, app: str, window_title: str) -> PipelineResult:
        """Full 7-stage pipeline:
        1. Audio capture (already done — we receive audio bytes)
        2. STT
        3. Replacements (voice macros)
        4. Context Engine (resolve terms + build prompt)
        5. LLM normalization (with assembled prompt)
        6. Local post-processing (numbers + exact dictionary)
        7. Text injection + history + context update
        """
```

### 10.2 Test cases (10+ integration tests)

```
tests/integration/test_pipeline.py

# --- Full pipeline ---
test_full_pipeline_mock_stt_llm        — mock STT + LLM, verify all 7 stages execute
test_pipeline_context_reduces_prompt   — with seeded graph, prompt has fewer candidates
test_pipeline_history_saved            — after process(), history row exists in DB

# --- Feedback loop ---
test_correction_improves_resolution    — correct "замок" 3x -> auto-promoted -> next time resolved locally
test_feedback_updates_graph            — correction updates co-occurrence weights

# --- Cross-app scenario ---
test_cross_app_slack_vscode            — dictation in Slack (IT terms) -> switch to VS Code
                                         -> IT context carries over via thread

# --- Cold start ---
test_cold_start_empty_db               — fresh DB -> all goes through LLM -> text still produced
test_cold_start_50_dictations          — simulate 50 dictations -> verify graph grows

# --- Degraded modes ---
test_all_toggles_off_skip_llm          — all toggles OFF -> LLM not called, raw text returned
test_llm_all_fail_degraded             — mock all LLM providers failing -> raw text + local post-processing

# --- Demo test ---
test_zamok_it_vs_household             — "замок" resolves to "lock" in IT thread,
                                         "замок" resolves to "дверний замок" in household thread
                                         (the canonical demo from architecture spec)
```

### 10.3 Quality gate

- [ ] All 10+ integration tests pass
- [ ] All unit tests still pass (`make test`)
- [ ] `ruff check src/pipeline.py` — clean
- [ ] `mypy --strict src/pipeline.py` — clean (may need relaxation for existing engine.py)
- [ ] `bandit src/pipeline.py` — clean
- [ ] Git commit: `feat: integrate context engine into dictation pipeline`

---

## 11. Phase 9: Database Maintenance + Export/Import

**Module:** `src/context/db.py` (maintenance functions added)
**Tests:** `tests/integration/test_db_maintenance.py`, `tests/integration/test_export_import.py`
**Architecture ref:** Section 13 (Database Maintenance)

### 11.1 Maintenance functions (added to db.py)

```python
def daily_maintenance(db: Connection, config: MaintenanceConfig) -> MaintenanceReport:
    """Run at app startup, max once per 24h.
    1. Prune weak old co-occurrence edges
    2. History retention policy
    3. Remove old inactive threads
    4. Cap fingerprints at 10K
    5. Consolidate large cluster edges
    6. Backup via VACUUM INTO
    7. Cache warming"""

def warm_cache(db: Connection) -> None:
    """Pre-load hot data into SQLite page cache."""

def schedule_vacuum(db: Connection) -> bool:
    """VACUUM if not run in 7+ days. Returns True if VACUUM executed."""
```

### 11.2 Export/import functions (new module or added to db.py)

```python
def export_profile(
    db: Connection, output_path: str, user_password: str,
    encrypt_fn: Callable = dpapi_encrypt,
    decrypt_fn: Callable = dpapi_decrypt,
) -> None:
    """Export full profile: unencrypted tables as-is, DPAPI -> AES-256-GCM."""

def import_profile(
    db: Connection, input_path: str, user_password: str,
    encrypt_fn: Callable = dpapi_encrypt,
) -> ImportReport:
    """Import profile: AES -> DPAPI, merge strategies per table, FK remapping."""
```

### 11.3 Test cases — maintenance (8+ tests)

```
tests/integration/test_db_maintenance.py

# --- Pruning ---
test_prune_old_weak_cooccurrence       — weight=1, 100d old -> deleted
test_prune_keeps_strong_edges          — weight=5, 100d old -> kept
test_history_retention_deletes_old     — 400d old history -> deleted (365d default retention)
test_thread_cleanup_180_days           — inactive thread 200d old -> deleted
test_fingerprint_cap_10k              — 12K fingerprints -> oldest 2K deleted

# --- Backup ---
test_backup_creates_file               — VACUUM INTO creates .backup-YYYY-MM-DD file
test_backup_existing_file_replaced     — existing backup file removed before VACUUM INTO

# --- VACUUM ---
test_vacuum_in_idle                    — schedule_vacuum() runs VACUUM when overdue
```

### 11.4 Test cases — export/import (10+ tests)

```
tests/integration/test_export_import.py

# --- Export ---
test_export_creates_file               — export produces .apk-profile file
test_export_unencrypted_tables         — clusters, cooccurrence, threads copied as-is
test_export_encrypted_dpapi_to_aes     — history re-encrypted from DPAPI mock -> AES

# --- Import ---
test_import_aes_to_dpapi               — AES-encrypted history -> DPAPI mock on import
test_import_merge_cooccurrence_sum     — co-occurrence weights summed between DBs
test_import_merge_dictionary_replace   — imported dictionary values win on conflict
test_import_fk_remapping               — thread_id and fingerprint_id remapped to avoid collision

# --- Round-trip ---
test_export_import_round_trip          — export -> import on fresh DB -> all data present
test_round_trip_integrity              — data integrity maintained through re-encryption

# --- Validation ---
test_import_validates_scripts          — imported non-builtin scripts validated for injection
test_import_wrong_password_fails       — wrong password -> AES decryption fails gracefully
```

### 11.5 Quality gate

- [ ] All 18+ tests pass (8 + 10)
- [ ] All previous tests still pass (`make test`)
- [ ] `ruff check` — clean
- [ ] `mypy --strict src/context/db.py` — clean
- [ ] `bandit` — clean
- [ ] Git commit: `feat(context): implement database maintenance and profile export/import`

---

## 12. LLM Real Tests (manual, pre-release)

**Tests:** `tests/llm_real/`
**Marker:** `@pytest.mark.llm_real`
**When to run:** Manually before release, with `make test-llm`

### 12.1 Test structure

```
tests/llm_real/
    __init__.py
    conftest.py              # Real LLM provider fixture (reads API keys from env)
    test_normalization.py    # Real Groq API normalization
    test_script_validation.py # Real LLM script validation
    test_prompt_quality.py   # Verify prompt produces good results
```

### 12.2 Test cases (6+ tests)

```
tests/llm_real/test_normalization.py

@pytest.mark.llm_real
test_groq_normalizes_ukrainian         — real Groq call: "як справи з деплоєм" -> properly normalized
test_groq_respects_toggles             — punctuation=True -> output has punctuation

tests/llm_real/test_script_validation.py

@pytest.mark.llm_real
test_real_llm_rejects_injection        — real LLM: "ignore all previous..." -> safe=False
test_real_llm_accepts_safe_script      — real LLM: "Use title case for headers" -> safe=True

tests/llm_real/test_prompt_quality.py

@pytest.mark.llm_real
test_prompt_with_candidates_resolves   — LLM correctly picks "lock" meaning when IT context provided
test_token_consumption_under_budget    — verify total tokens < 300 for typical request
```

### 12.3 Pre-release checklist

- [ ] `GROQ_API_KEY` set in environment
- [ ] `make test-llm` — all 6+ tests pass
- [ ] Token consumption logged and within budget
- [ ] No unexpected API errors

---

## 13. Quality Gates Per Phase

After completing each phase (1-9), the implementor MUST run the following checks before committing:

### 13.1 Standard quality gate (every phase)

```bash
# 1. Lint
ruff check src/context/ tests/
ruff format --check src/context/ tests/

# 2. Type check
mypy --strict src/context/

# 3. Security scan
bandit -r src/context/ -ll

# 4. Run tests
pytest tests/ -m "not llm_real" --cov=src --cov-fail-under=80

# 5. Complexity check
radon cc src/context/ -a -nc

# Or all at once:
make check-all
```

### 13.2 Quality gate automation

The quality-gate plugin runs automatically after each implementation task:

```bash
python3 ~/.claude/plugins/quality-gate/tools/run_quality_gate.py
```

### 13.3 Per-phase commit pattern

```
Phase 0: feat: add test infrastructure and context engine schema
Phase 1: feat(context): implement keyword extraction with pymorphy3 lemmatization
Phase 2: feat(context): implement co-occurrence graph with temporal decay
Phase 3: feat(context): implement cluster detection and naming
Phase 4: feat(context): implement conversation thread management
Phase 5: feat(context): implement 4-level context engine with cascade resolution
Phase 6: feat(context): implement prompt builder and script validator
Phase 7: feat: implement dictionary CRUD and correction learning
Phase 8: feat: integrate context engine into dictation pipeline
Phase 9: feat(context): implement database maintenance and profile export/import
```

---

## 14. Success Criteria

| Criterion | Measurement | Threshold |
|-----------|-------------|-----------|
| All 9 phases complete | Phase checklist | 9/9 |
| Test coverage for `src/context/` | `pytest --cov=src/context` | >= 80% |
| Total test count | `pytest --collect-only \| tail -1` | >= 130 tests |
| Ruff violations | `ruff check src/context/ tests/` | 0 |
| Mypy errors | `mypy --strict src/context/` | 0 |
| Bandit findings | `bandit -r src/context/ -ll` | 0 |
| Complexity violations (CC>10) | `radon cc src/context/ -a -nc` | 0 |
| CI pipeline green | GitHub Actions | all jobs pass |
| LLM real tests pass | `make test-llm` (manual) | all pass |
| "замок" demo test | `test_zamok_it_vs_household` | passes |
| v5 existing tests unbroken | `pytest tests/` (full suite) | all pass |

---

## 15. Dependencies to Install

### 15.1 requirements-dev.txt (new file)

```
# Testing
pytest>=8.0
pytest-cov>=5.0

# Code quality
ruff>=0.9.0
mypy>=1.14
bandit>=1.8
radon>=6.0
vulture>=2.0

# Security
pip-audit>=2.0
detect-secrets>=1.5

# Git hooks
pre-commit>=4.0

# Context Engine runtime dependency
pymorphy3>=2.0
```

### 15.2 requirements.txt additions

Add to existing `requirements.txt`:

```
pymorphy3>=2.0
```

### 15.3 Installation command

```bash
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

---

## 16. File Tree (final state after all phases)

```
AI_Polyglot_Kit/
|-- .github/
|   `-- workflows/
|       `-- ci.yml                          # Phase 0 — GitHub Actions CI
|-- .pre-commit-config.yaml                 # Phase 0 — pre-commit hooks
|-- Makefile                                # Phase 0 — make targets
|-- pyproject.toml                          # Phase 0 — pytest/ruff/mypy/coverage config
|-- requirements.txt                        # existing + pymorphy3 added
|-- requirements-dev.txt                    # Phase 0 — dev dependencies
|
|-- src/
|   |-- __init__.py                         # existing
|   |-- __main__.py                         # existing
|   |-- engine.py                           # existing v5 (untouched until Phase 8)
|   |-- normalizer.py                       # existing v5
|   |-- pipeline.py                         # Phase 8 — refactored 7-stage pipeline
|   |-- dictionary.py                       # Phase 7 — dictionary CRUD, exact/context
|   |-- corrections.py                      # Phase 7 — correction triads, auto-promote
|   |-- ... (existing v5 modules)           #
|   |
|   `-- context/
|       |-- __init__.py                     # Phase 0 — package init
|       |-- db.py                           # Phase 0 + Phase 9 — connection manager, schema, maintenance
|       |-- keywords.py                     # Phase 1 — keyword extraction + lemmatization
|       |-- cooccurrence.py                 # Phase 2 — co-occurrence graph
|       |-- clusters.py                     # Phase 3 — cluster detection and naming
|       |-- threads.py                      # Phase 4 — conversation thread management
|       |-- engine.py                       # Phase 5 — 4-level context engine
|       |-- prompt_builder.py              # Phase 6 — LLM prompt assembly
|       `-- script_validator.py            # Phase 6 — script security validation
|
|-- tests/
|   |-- conftest.py                         # Phase 0 — root conftest with DB fixtures, LLM mock, Timer
|   |-- factories.py                        # Phase 0 — factory functions for all Context Engine entities
|   |
|   |-- unit/
|   |   |-- test_keywords.py               # Phase 1 — 15+ tests
|   |   |-- test_cooccurrence.py           # Phase 2 — 20+ tests
|   |   |-- test_clusters.py              # Phase 3 — 12+ tests
|   |   |-- test_threads.py               # Phase 4 — 18+ tests
|   |   |-- test_context_engine.py        # Phase 5 — 16+ tests
|   |   |-- test_prompt_builder.py        # Phase 6 — 12+ tests
|   |   |-- test_script_validator.py      # Phase 6 — 14+ tests
|   |   |-- test_dictionary.py            # Phase 7 — 12+ tests
|   |   `-- test_corrections.py           # Phase 7 — 14+ tests
|   |
|   |-- integration/
|   |   |-- test_pipeline.py              # Phase 8 — 10+ tests
|   |   |-- test_db_maintenance.py        # Phase 9 — 8+ tests
|   |   `-- test_export_import.py         # Phase 9 — 10+ tests
|   |
|   |-- llm_real/
|   |   |-- __init__.py                    # Phase 12
|   |   |-- conftest.py                    # Phase 12 — real LLM provider fixture
|   |   |-- test_normalization.py         # Phase 12 — real Groq API tests
|   |   |-- test_script_validation.py     # Phase 12 — real LLM script validation
|   |   `-- test_prompt_quality.py        # Phase 12 — prompt quality and token budget
|   |
|   `-- ui/                                # existing (empty or v5 UI tests)
|
`-- docs/
    `-- superpowers/
        `-- specs/
            |-- 2026-03-28-context-engine-architecture.md  # parent spec
            `-- 2026-03-28-implementation-pipeline.md       # this document
```

**Total new files:** 26
**Total new test files:** 14
**Estimated total test cases:** 130+

---

## Appendix A: Phase Dependency Graph

```
Phase 0 (Infrastructure)
    |
    v
Phase 1 (keywords.py)
    |
    v
Phase 2 (cooccurrence.py) ---+
    |                         |
    v                         |
Phase 3 (clusters.py) -------+
    |                         |
    v                         |
Phase 4 (threads.py) --------+
    |                         |
    v                         |
Phase 5 (engine.py) <--------+  (depends on all of 1-4)
    |
    +---> Phase 6 (prompt_builder + script_validator)
    |
    +---> Phase 7 (dictionary + corrections)
    |
    v
Phase 8 (pipeline integration) <--- Phase 6, Phase 7
    |
    v
Phase 9 (maintenance + export/import)
    |
    v
Phase 12 (LLM real tests — manual)
```

Phases 6 and 7 can run in **parallel** after Phase 5 completes.

---

## Appendix B: Estimated Implementation Time

| Phase | Estimated effort | Cumulative |
|-------|-----------------|------------|
| Phase 0: Infrastructure | 1-2 hours | 2h |
| Phase 1: keywords.py | 2-3 hours | 5h |
| Phase 2: cooccurrence.py | 3-4 hours | 9h |
| Phase 3: clusters.py | 2-3 hours | 12h |
| Phase 4: threads.py | 3-4 hours | 16h |
| Phase 5: engine.py | 3-4 hours | 20h |
| Phase 6: prompt + validator | 3-4 hours | 24h |
| Phase 7: dictionary + corrections | 3-4 hours | 28h |
| Phase 8: pipeline integration | 4-5 hours | 33h |
| Phase 9: maintenance + export | 3-4 hours | 37h |
| LLM real tests | 1-2 hours | 39h |
| **Total** | **~35-40 hours** | |

"""Remote log handler — sends logs to Axiom.co via HTTP API.

Non-blocking: buffers logs and sends in background thread.
Logs viewable at https://app.axiom.co and queryable via API.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import UTC, datetime

import httpx

AXIOM_URL = "https://api.axiom.co/v1/datasets/polyglot-logs/ingest"
AXIOM_TOKEN = "xaat-d3c48bcd-51ea-49db-b5e5-3a7d43c3634f"  # noqa: S105
FLUSH_INTERVAL = 5.0
MAX_BATCH = 50


class BetterStackHandler(logging.Handler):
    """Async logging handler that sends logs to Axiom."""

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=1000)
        self._thread = threading.Thread(target=self._flush_loop, name="AxiomLogs", daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "_time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "message": self.format(record),
                "level": record.levelname.lower(),
                "logger": record.name,
                "thread": record.threadName or "",
            }
            self._queue.put_nowait(entry)
        except queue.Full:
            pass

    def _flush_loop(self) -> None:
        while True:
            time.sleep(FLUSH_INTERVAL)
            self._flush()

    def _flush(self) -> None:
        batch: list[dict[str, str]] = []
        while len(batch) < MAX_BATCH:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not batch:
            return

        import contextlib  # noqa: PLC0415

        with contextlib.suppress(Exception):
            httpx.post(
                AXIOM_URL,
                json=batch,
                headers={
                    "Authorization": f"Bearer {AXIOM_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

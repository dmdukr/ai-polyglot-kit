"""Better Stack (Logtail) remote log handler.

Sends log records to Better Stack via HTTP API.
Non-blocking: buffers logs and sends in background thread.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import UTC, datetime

import httpx

BETTERSTACK_URL = "https://s2332954.eu-fsn-3.betterstackdata.com"
BETTERSTACK_TOKEN = "pVohkPBuQnnQmRtYBdm2fdtt"  # noqa: S105
FLUSH_INTERVAL = 5.0  # seconds
MAX_BATCH = 50


class BetterStackHandler(logging.Handler):
    """Async logging handler that sends logs to Better Stack."""

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=1000)
        self._thread = threading.Thread(target=self._flush_loop, name="BetterStack", daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "dt": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "message": self.format(record),
                "level": record.levelname.lower(),
                "logger": record.name,
                "thread": record.threadName or "",
            }
            self._queue.put_nowait(entry)
        except queue.Full:
            pass  # drop if buffer full

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
                BETTERSTACK_URL,
                json=batch,
                headers={
                    "Authorization": f"Bearer {BETTERSTACK_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

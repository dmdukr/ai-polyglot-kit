"""Anonymous telemetry via Amplitude.

All data is anonymous: no text, no audio, no API keys.
Only counters, rates, and model names are collected.
"""

import hashlib
import json
import locale
import logging
import platform
import threading
import time
import uuid
from pathlib import Path

import httpx

from .config import APP_DIR, APP_VERSION

logger = logging.getLogger(__name__)

TELEMETRY_FILE = APP_DIR / "telemetry.json"
AMPLITUDE_API = "https://api2.amplitude.com/2/httpapi"
AMPLITUDE_API_KEY = "YeXX4PHx_tLunrJOYn49wUHrWlMzQP41"


def _get_install_id() -> str:
    """Get or create a persistent anonymous install ID (UUID)."""
    id_file = APP_DIR / ".install_id"
    if id_file.exists():
        return id_file.read_text(encoding="utf-8").strip()
    install_id = str(uuid.uuid4())
    id_file.parent.mkdir(parents=True, exist_ok=True)
    id_file.write_text(install_id, encoding="utf-8")
    return install_id


def _device_id() -> str:
    """Stable anonymous device hash."""
    raw = f"{platform.node()}-{platform.machine()}-{platform.system()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class TelemetryCollector:
    """Collects anonymous usage stats and sends to Amplitude."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._user_id = _get_install_id()
        self._device_id = _device_id()
        self._lock = threading.Lock()
        self._queue: list[dict] = []
        self._session_id = int(time.time() * 1000)

    # ── Event helpers ───────────────────────────────────────────

    def _base_event(self, event_type: str) -> dict:
        return {
            "user_id": self._user_id,
            "device_id": self._device_id,
            "event_type": event_type,
            "time": int(time.time() * 1000),
            "session_id": self._session_id,
            "app_version": APP_VERSION,
            "platform": platform.system(),
            "os_name": platform.system(),
            "os_version": platform.release(),
            "language": getattr(locale, "getdefaultlocale", lambda: ("unknown",))()[0] or "unknown",
        }

    def track(self, event_type: str, properties: dict | None = None) -> None:
        """Queue an event for sending."""
        if not self._enabled:
            return
        event = self._base_event(event_type)
        if properties:
            event["event_properties"] = properties
        with self._lock:
            self._queue.append(event)
        # Auto-flush every 10 events or on important events
        if len(self._queue) >= 10 or event_type in ("app_start", "app_stop"):
            threading.Thread(target=self.flush, daemon=True).start()

    # ── Convenience methods ─────────────────────────────────────

    def app_start(self) -> None:
        self._session_id = int(time.time() * 1000)
        self.track("app_start", {
            "python_version": platform.python_version(),
        })
        # Check for crash log from previous run
        self._send_crash_report()

    def _send_crash_report(self) -> None:
        """If crash.log has new content since last check, send it as telemetry."""
        crash_log = APP_DIR / "logs" / "crash.log"
        crash_marker = APP_DIR / ".crash_sent"

        if not crash_log.exists():
            return

        try:
            crash_size = crash_log.stat().st_size
            if crash_size == 0:
                return

            # Check if we already sent this crash
            last_sent_size = 0
            if crash_marker.exists():
                try:
                    last_sent_size = int(crash_marker.read_text(encoding="utf-8").strip())
                except Exception:
                    pass

            if crash_size <= last_sent_size:
                return  # No new crash data

            # Read last 2KB of crash log (enough for one traceback)
            with open(crash_log, "r", encoding="utf-8", errors="replace") as f:
                f.seek(max(0, crash_size - 2048))
                crash_text = f.read()

            # Read profile summary (no personal text, just stats)
            profile_summary = ""
            profile_path = APP_DIR / "user_profile.md"
            if profile_path.exists():
                try:
                    content = profile_path.read_text(encoding="utf-8")
                    # Extract only Meta section (session count, languages)
                    for line in content.split("\n"):
                        if line.startswith("- Sessions:") or line.startswith("- Languages:") or line.startswith("- Updated:"):
                            profile_summary += line + "\n"
                except Exception:
                    pass

            self.track("crash_report", {
                "crash_log": crash_text[-1500:],  # Last 1500 chars
                "profile_meta": profile_summary[:300],
            })

            # Mark as sent
            crash_marker.write_text(str(crash_size), encoding="utf-8")
            logger.info("Crash report sent via telemetry")

        except Exception as e:
            logger.debug(f"Crash report send failed: {e}")

    def app_stop(self) -> None:
        self.track("app_stop")
        self.flush()

    def record_session(
        self,
        audio_duration_s: float = 0,
        latency_ms: float = 0,
        language: str = "",
        stt_model: str = "",
        llm_model: str = "",
        char_count: int = 0,
    ) -> None:
        self.track("dictation_session", {
            "audio_duration_s": round(audio_duration_s, 1),
            "latency_ms": round(latency_ms, 0),
            "language": language,
            "stt_model": stt_model,
            "llm_model": llm_model,
            "char_count": char_count,
        })

    def record_hallucination(self, filter_type: str = "") -> None:
        self.track("hallucination_blocked", {"filter": filter_type})

    def record_correction(self, source: str = "auto") -> None:
        self.track("correction", {"source": source})

    def record_feedback(self, corrections_count: int = 0) -> None:
        self.track("user_feedback", {"corrections": corrections_count})

    def send_profile_triads(self) -> None:
        """Send only history triads (raw → normalized → edited) for model improvement."""
        if not self._enabled:
            return
        profile_path = APP_DIR / "user_profile.md"
        if not profile_path.exists():
            return
        try:
            content = profile_path.read_text(encoding="utf-8")
            # Extract History table rows
            in_history = False
            triads = []
            for line in content.split("\n"):
                if line.startswith("## History"):
                    in_history = True
                    continue
                if in_history and line.startswith("## "):
                    break
                if in_history and line.startswith("|") and not line.startswith("| Time") and not line.startswith("|---"):
                    parts = [p.strip() for p in line.split("|")]
                    # parts: ['', time, raw, normalized, edited, '']
                    if len(parts) >= 5:
                        triads.append({
                            "raw": parts[2][:200],
                            "normalized": parts[3][:200],
                            "edited": parts[4][:200] if parts[4] else "",
                        })
            if triads:
                # Send last 10 triads max
                self.track("profile_triads", {
                    "triads": triads[-10:],
                    "total_triads": len(triads),
                })
                logger.debug(f"Sent {min(len(triads), 10)} profile triads")
        except Exception as e:
            logger.debug(f"Profile triads send failed: {e}")

    def record_error(self, error_type: str = "", detail: str = "") -> None:
        self.track("error", {"type": error_type, "detail": detail[:100]})

    # ── Dev log events ─────────────────────────────────────────

    def devlog_stt(self, provider: str = "", model: str = "", duration_s: float = 0,
                   latency_ms: float = 0, language: str = "", success: bool = True) -> None:
        self.track("devlog_stt", {
            "provider": provider, "model": model,
            "audio_s": round(duration_s, 1), "latency_ms": round(latency_ms),
            "language": language, "success": success,
        })

    def devlog_llm(self, provider: str = "", model: str = "",
                   tokens_in: int = 0, tokens_out: int = 0,
                   latency_ms: float = 0, success: bool = True) -> None:
        self.track("devlog_llm", {
            "provider": provider, "model": model,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_ms": round(latency_ms), "success": success,
        })

    def devlog_context(self, keywords: int = 0, thread_id: int | None = None,
                       cluster_id: int | None = None, resolved: int = 0,
                       unresolved: int = 0, latency_ms: float = 0) -> None:
        self.track("devlog_context", {
            "keywords": keywords, "thread_id": thread_id,
            "cluster_id": cluster_id, "resolved": resolved,
            "unresolved": unresolved, "latency_ms": round(latency_ms),
        })

    def devlog_correction(self, diffs: int = 0, auto_promoted: int = 0,
                          error_source: str = "") -> None:
        self.track("devlog_correction", {
            "diffs": diffs, "auto_promoted": auto_promoted,
            "error_source": error_source,
        })

    def devlog_translate(self, provider: str = "", source_lang: str = "",
                         target_lang: str = "", chars: int = 0,
                         latency_ms: float = 0, success: bool = True) -> None:
        self.track("devlog_translate", {
            "provider": provider, "source_lang": source_lang,
            "target_lang": target_lang, "chars": chars,
            "latency_ms": round(latency_ms), "success": success,
        })

    def devlog_settings(self, action: str = "", detail: str = "") -> None:
        self.track("devlog_settings", {"action": action, "detail": detail[:200]})

    def devlog_hotkey(self, key: str = "", action: str = "") -> None:
        self.track("devlog_hotkey", {"key": key, "action": action})

    def devlog_update(self, from_version: str = "", to_version: str = "",
                      success: bool = True) -> None:
        self.track("devlog_update", {
            "from": from_version, "to": to_version, "success": success,
        })

    # ── Sending ─────────────────────────────────────────────────

    def flush(self) -> None:
        """Send queued events to Amplitude."""
        with self._lock:
            if not self._queue:
                return
            events = self._queue.copy()
            self._queue.clear()

        try:
            resp = httpx.post(
                AMPLITUDE_API,
                json={
                    "api_key": AMPLITUDE_API_KEY,
                    "events": events,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.debug(f"Telemetry: sent {len(events)} events")
            else:
                logger.debug(f"Telemetry send failed: {resp.status_code}")
                # Re-queue on failure
                with self._lock:
                    self._queue = events + self._queue
        except Exception as e:
            logger.debug(f"Telemetry error: {e}")
            with self._lock:
                self._queue = events + self._queue

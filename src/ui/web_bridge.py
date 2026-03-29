"""Python API bridge exposed to JavaScript via ``window.pywebview.api``.

Every public method on :class:`WebBridge` is callable from the front-end
SPA.  Methods return plain dicts / lists that pywebview serialises to JSON
automatically.  All methods are wrapped in try/except so that a failure in
one call never crashes the whole bridge.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.audio_capture import AudioCapture
    from src.config import AppConfig

logger = logging.getLogger(__name__)


def _safe(method: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that wraps a bridge method in try/except.

    On error the method returns ``{"success": False, "error": "<message>"}``
    instead of propagating the exception to the JS caller.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            logger.exception("WebBridge.%s failed", method.__name__)
            return {"success": False, "error": str(exc)}

    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    return wrapper


# ---------------------------------------------------------------------------
# Lazy DB helper
# ---------------------------------------------------------------------------


def _get_db() -> Any:
    """Return a thread-local SQLite connection from the context engine.

    Returns ``None`` when the DB has not been configured yet (the context
    engine is optional and may not be initialised during early startup).
    """
    try:
        from src.context.db import get_connection  # noqa: PLC0415

        return get_connection()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# WebBridge
# ---------------------------------------------------------------------------


class WebBridge:
    """Python <-> JS API surface for the settings SPA.

    Parameters
    ----------
    config:
        Live :class:`AppConfig` instance (mutated in-place on save).
    audio_capture:
        Optional :class:`AudioCapture` for mic enumeration / testing.
    on_save:
        Optional callback ``(restart: bool) -> None`` invoked after save.
    """

    def __init__(
        self,
        config: AppConfig,
        audio_capture: object | None = None,
        on_save: object | None = None,
    ) -> None:
        self._config = config
        self._audio: AudioCapture | None = audio_capture  # type: ignore[assignment]
        self._on_save: Callable[..., Any] | None = on_save  # type: ignore[assignment]
        self._window: Any | None = None

    def set_window(self, window: Any) -> None:
        """Store a reference to the pywebview Window (set by the launcher)."""
        self._window = window

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @_safe
    def get_config(self) -> dict[str, Any]:
        """Return the full configuration as a plain dict for the JS forms."""
        data = asdict(self._config)
        # Include autostart state (Windows registry)
        data["autostart"] = self._get_autostart()
        # Include theme preference (stored separately)
        data["theme"] = self._load_theme()
        return data

    @_safe
    def save_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Persist configuration from JS form data.

        Applies the incoming dict onto the live :class:`AppConfig`, writes
        the YAML and ``.env`` files, and invokes the ``on_save`` callback.

        Returns ``{"success": True}`` on success.
        """
        self._apply_config(data)
        self._write_config()
        self._write_env()
        self._save_theme(data.get("theme", "auto"))

        # Autostart
        autostart = data.get("autostart")
        if autostart is not None:
            self._set_autostart(bool(autostart))

        if self._on_save is not None:
            self._on_save(restart=True)

        return {"success": True}

    @_safe
    def get_version(self) -> dict[str, str]:
        """Return application name and version."""
        from src.config import APP_NAME, APP_VERSION  # noqa: PLC0415

        return {"version": APP_VERSION, "app_name": APP_NAME}

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    @_safe
    def get_audio_devices(self) -> list[dict[str, Any]]:
        """Enumerate input audio devices.

        Returns a list of ``{"index": int, "name": str, "is_current": bool}``.
        """
        if self._audio is None:
            return []

        devices = self._audio.list_devices()
        current_idx = self._config.audio.mic_device_index
        return [
            {
                "index": d.index,
                "name": d.name,
                "is_current": d.index == current_idx,
            }
            for d in devices
        ]

    @_safe
    def test_audio(self, device_index: int) -> dict[str, Any]:
        """Run a quick audio level test on the given device.

        Returns ``{"success": True, "rms_db": float}`` or an error dict.
        """
        if self._audio is None:
            return {"success": False, "error": "AudioCapture not available"}

        import math  # noqa: PLC0415
        import struct  # noqa: PLC0415

        try:
            import pyaudio  # noqa: PLC0415
        except ImportError:
            return {"success": False, "error": "PyAudio not installed"}

        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=4096,
            )
            frames = stream.read(4096, exception_on_overflow=False)
            stream.stop_stream()
            stream.close()
        finally:
            pa.terminate()

        n_samples = len(frames) // 2
        if n_samples == 0:
            return {"success": False, "error": "No audio data"}

        samples = struct.unpack(f"<{n_samples}h", frames)
        rms = math.sqrt(sum(s * s for s in samples) / n_samples)
        rms_db = 20 * math.log10(max(rms, 1e-10))

        return {"success": True, "rms_db": round(rms_db, 1)}

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    @_safe
    def detect_provider(self, api_key: str) -> dict[str, Any] | None:
        """Detect provider from an API key prefix.

        Returns ``{"name", "base_url", "supports_stt", "supports_llm"}``
        or ``None`` if the prefix is unknown.
        """
        from src.providers import detect_provider as _detect  # noqa: PLC0415

        info = _detect(api_key)
        if info is None:
            return None
        return {
            "name": info.name,
            "base_url": info.base_url,
            "supports_stt": info.supports_stt,
            "supports_llm": info.supports_llm,
        }

    @_safe
    def fetch_models(self, api_key: str, base_url: str) -> list[str]:
        """Fetch available model IDs from a provider's ``/models`` endpoint."""
        from src.providers import fetch_models as _fetch  # noqa: PLC0415

        return _fetch(base_url, api_key)

    # ------------------------------------------------------------------
    # Dictionary
    # ------------------------------------------------------------------

    @_safe
    def get_dictionary(self) -> list[dict[str, Any]]:
        """Return all dictionary terms."""
        db = _get_db()
        if db is None:
            return []

        rows = db.execute(
            "SELECT id, source_text, target_text, term_type, origin, hit_count FROM dictionary ORDER BY id"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "source": r["source_text"],
                "target": r["target_text"],
                "type": r["term_type"],
                "origin": r["origin"],
                "hits": r["hit_count"],
            }
            for r in rows
        ]

    @_safe
    def add_dictionary_term(self, source: str, target: str, term_type: str = "exact") -> dict[str, Any]:
        """Add a dictionary term.  Returns ``{"success": True, "id": int}``."""
        db = _get_db()
        if db is None:
            return {"success": False, "error": "Database not configured"}

        from src.context.dictionary import add_term  # noqa: PLC0415

        term_id = add_term(db, source, target, term_type=term_type, origin="manual")
        return {"success": True, "id": term_id}

    @_safe
    def remove_dictionary_term(self, term_id: int) -> dict[str, Any]:
        """Remove a dictionary term by ID."""
        db = _get_db()
        if db is None:
            return {"success": False, "error": "Database not configured"}

        from src.context.dictionary import remove_term  # noqa: PLC0415

        remove_term(db, term_id)
        return {"success": True}

    @_safe
    def import_dictionary(self, data: str) -> dict[str, Any]:
        """Import dictionary terms from a JSON string.

        Returns ``{"success": True, "count": int}``.
        """
        db = _get_db()
        if db is None:
            return {"success": False, "error": "Database not configured"}

        from src.context.dictionary import import_terms  # noqa: PLC0415

        terms = json.loads(data)
        count = import_terms(db, terms)
        return {"success": True, "count": count}

    @_safe
    def export_dictionary(self) -> str:
        """Export all dictionary terms as a JSON string."""
        db = _get_db()
        if db is None:
            return "[]"

        from src.context.dictionary import export_terms  # noqa: PLC0415

        terms = export_terms(db)
        return json.dumps(terms, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Replacements
    # ------------------------------------------------------------------

    @_safe
    def get_replacements(self) -> list[dict[str, Any]]:
        """Return all replacement rules from the DB."""
        db = _get_db()
        if db is None:
            return []

        rows = db.execute(
            "SELECT id, trigger_text, replacement_text, match_mode, is_sensitive, hit_count "
            "FROM replacements ORDER BY id"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "trigger": r["trigger_text"],
                "replacement": r["replacement_text"],
                "match_mode": r["match_mode"],
                "is_sensitive": bool(r["is_sensitive"]),
                "hits": r["hit_count"],
            }
            for r in rows
        ]

    @_safe
    def add_replacement(
        self,
        trigger: str,
        replacement: str,
        match_mode: str = "fuzzy",
        is_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Add a replacement rule.  Returns ``{"success": True, "id": int}``."""
        db = _get_db()
        if db is None:
            return {"success": False, "error": "Database not configured"}

        cursor = db.execute(
            "INSERT INTO replacements (trigger_text, replacement_text, match_mode, is_sensitive) VALUES (?, ?, ?, ?)",
            [trigger, replacement, match_mode, int(is_sensitive)],
        )
        db.commit()
        return {"success": True, "id": cursor.lastrowid}

    @_safe
    def remove_replacement(self, replacement_id: int) -> dict[str, Any]:
        """Remove a replacement rule by ID."""
        db = _get_db()
        if db is None:
            return {"success": False, "error": "Database not configured"}

        db.execute("DELETE FROM replacements WHERE id = ?", [replacement_id])
        db.commit()
        return {"success": True}

    # ------------------------------------------------------------------
    # Scripts / Per-App rules
    # ------------------------------------------------------------------

    @_safe
    def get_scripts(self) -> list[dict[str, Any]]:
        """Return all formatting scripts."""
        db = _get_db()
        if db is None:
            return []

        rows = db.execute("SELECT id, name, body, is_builtin FROM scripts ORDER BY id").fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "body": r["body"],
                "is_builtin": bool(r["is_builtin"]),
            }
            for r in rows
        ]

    @_safe
    def save_script(self, name: str, body: str) -> dict[str, Any]:
        """Validate and save a formatting script.

        Uses the deterministic check from
        :mod:`src.context.script_validator`.  Returns
        ``{"success": True, "id": int}`` or an error with violations.
        """
        from src.context.script_validator import deterministic_check  # noqa: PLC0415

        violations = deterministic_check(body)
        if violations:
            return {"success": False, "error": "Validation failed", "violations": violations}

        db = _get_db()
        if db is None:
            return {"success": False, "error": "Database not configured"}

        cursor = db.execute(
            "INSERT INTO scripts (name, body) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET body = excluded.body",
            [name, body],
        )
        db.commit()
        return {"success": True, "id": cursor.lastrowid}

    @_safe
    def get_app_rules(self) -> list[dict[str, Any]]:
        """Return all application -> script mapping rules."""
        db = _get_db()
        if db is None:
            return []

        rows = db.execute(
            "SELECT ar.id, ar.app_name, ar.script_id, s.name AS script_name "
            "FROM app_rules ar LEFT JOIN scripts s ON ar.script_id = s.id "
            "ORDER BY ar.id"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "app_name": r["app_name"],
                "script_id": r["script_id"],
                "script_name": r["script_name"],
            }
            for r in rows
        ]

    @_safe
    def save_app_rule(self, app_name: str, script_id: int) -> dict[str, Any]:
        """Save (upsert) an application rule."""
        db = _get_db()
        if db is None:
            return {"success": False, "error": "Database not configured"}

        cursor = db.execute(
            "INSERT INTO app_rules (app_name, script_id) VALUES (?, ?) "
            "ON CONFLICT(app_name) DO UPDATE SET script_id = excluded.script_id",
            [app_name, script_id],
        )
        db.commit()
        return {"success": True, "id": cursor.lastrowid}

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    @_safe
    def get_history(
        self,
        limit: int = 50,
        offset: int = 0,
        app_filter: str = "",
        time_filter: str = "all",
    ) -> dict[str, Any]:
        """Fetch history entries with pagination and optional filters.

        Returns ``{"items": [...], "total": int}``.
        """
        db = _get_db()
        if db is None:
            return {"items": [], "total": 0}

        where_clauses: list[str] = []
        params: list[Any] = []

        if app_filter:
            where_clauses.append("app = ?")
            params.append(app_filter)

        if time_filter == "today":
            where_clauses.append("date(timestamp) = date('now')")
        elif time_filter == "week":
            where_clauses.append("timestamp >= datetime('now', '-7 days')")
        elif time_filter == "month":
            where_clauses.append("timestamp >= datetime('now', '-30 days')")

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        total_row = db.execute(
            f"SELECT COUNT(*) AS cnt FROM history{where_sql}",  # noqa: S608
            params,
        ).fetchone()
        total: int = total_row["cnt"] if total_row else 0

        rows = db.execute(
            f"SELECT id, timestamp, app, window_title, language, duration_s, "  # noqa: S608
            f"word_count, stt_provider, llm_provider, was_corrected "
            f"FROM history{where_sql} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        items = [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "app": r["app"],
                "window_title": r["window_title"],
                "language": r["language"],
                "duration_s": r["duration_s"],
                "word_count": r["word_count"],
                "stt_provider": r["stt_provider"],
                "llm_provider": r["llm_provider"],
                "was_corrected": bool(r["was_corrected"]),
            }
            for r in rows
        ]

        return {"items": items, "total": total}

    @_safe
    def delete_history(self, ids: list[int]) -> dict[str, Any]:
        """Delete history entries by ID list."""
        db = _get_db()
        if db is None:
            return {"success": False, "error": "Database not configured"}

        if not ids:
            return {"success": True}

        placeholders = ",".join("?" for _ in ids)
        db.execute(f"DELETE FROM history WHERE id IN ({placeholders})", ids)  # noqa: S608
        db.commit()
        return {"success": True}

    # ------------------------------------------------------------------
    # Browser extensions
    # ------------------------------------------------------------------

    @_safe
    def find_browsers(self) -> list[dict[str, Any]]:
        """Detect installed Chromium-based browsers."""
        from src.browser_installer import find_browsers as _find  # noqa: PLC0415
        from src.browser_installer import is_extension_installed  # noqa: PLC0415

        browsers = _find()
        return [
            {
                "name": b.name,
                "exe_path": str(b.exe_path) if b.exe_path else None,
                "extensions_url": b.extensions_url,
                "installed": is_extension_installed(b),
            }
            for b in browsers
        ]

    @_safe
    def install_extension(self, browser_name: str) -> dict[str, Any]:
        """Return extension installation info for a browser.

        The actual installation is manual (user must load unpacked in the
        browser).  This method opens the browser and returns the extension
        directory path.
        """
        from src.browser_installer import find_browsers as _find  # noqa: PLC0415

        browsers = _find()
        target = next((b for b in browsers if b.name == browser_name), None)
        if target is None:
            return {"success": False, "error": f"Browser '{browser_name}' not found"}

        # Open the browser if possible
        if target.exe_path:
            try:
                subprocess.Popen([str(target.exe_path)])  # noqa: S603
            except Exception as exc:
                logger.warning("Failed to open %s: %s", browser_name, exc)

        ext_dir = Path(__file__).parent.parent.parent / "extension"
        return {
            "success": True,
            "extensions_url": target.extensions_url,
            "extension_path": str(ext_dir),
        }

    # ------------------------------------------------------------------
    # I18N
    # ------------------------------------------------------------------

    @_safe
    def get_translations(self) -> dict[str, str]:
        """Return all translation strings for the current UI language."""
        from src.i18n import _STRINGS, get_language  # noqa: PLC0415

        lang = get_language()
        result: dict[str, str] = {}
        for key, translations in _STRINGS.items():
            result[key] = translations.get(lang) or translations.get("en") or key
        return result

    @_safe
    def set_language(self, lang: str) -> dict[str, Any]:
        """Change the UI language and return the new translation set."""
        from src.i18n import set_language as _set_lang  # noqa: PLC0415

        _set_lang(lang)
        return {"success": True, "translations": self.get_translations()}

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @_safe
    def get_stats(self) -> dict[str, Any]:
        """Gather usage statistics from the history table."""
        db = _get_db()
        if db is None:
            return {
                "total_dictations": 0,
                "total_duration_s": 0,
                "total_words": 0,
                "corrections": 0,
                "top_apps": [],
            }

        row = db.execute(
            "SELECT COUNT(*) AS cnt, "
            "COALESCE(SUM(duration_s), 0) AS dur, "
            "COALESCE(SUM(word_count), 0) AS words, "
            "COALESCE(SUM(was_corrected), 0) AS corr "
            "FROM history"
        ).fetchone()

        top_apps_rows = db.execute(
            "SELECT app, COUNT(*) AS cnt FROM history GROUP BY app ORDER BY cnt DESC LIMIT 5"
        ).fetchall()

        return {
            "total_dictations": row["cnt"] if row else 0,
            "total_duration_s": round(row["dur"], 1) if row else 0,
            "total_words": row["words"] if row else 0,
            "corrections": row["corr"] if row else 0,
            "top_apps": [{"app": r["app"], "count": r["cnt"]} for r in top_apps_rows],
        }

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    @_safe
    def check_update(self) -> dict[str, Any]:
        """Check GitHub for a newer release.

        Returns ``{"available": True, "version": str, "url": str}``
        or ``{"available": False}``.
        """
        from src.updater import Updater  # noqa: PLC0415

        updater = Updater()
        result = updater.check_now()
        if result:
            return {
                "available": True,
                "version": result.get("version", ""),
                "url": result.get("url", ""),
            }
        return {"available": False}

    @_safe
    def open_logs_folder(self) -> None:
        """Open the logs folder in the system file manager."""
        from src.config import APP_DIR  # noqa: PLC0415

        logs_dir = APP_DIR / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(logs_dir))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(logs_dir)])  # noqa: S603, S607

    @_safe
    def open_url(self, url: str) -> None:
        """Open a URL in the default web browser."""
        webbrowser.open(url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_config(self, data: dict[str, Any]) -> None:
        """Map incoming JS form dict onto the live :class:`AppConfig`."""
        self._apply_providers(data)
        self._apply_audio(data)
        self._apply_dictation(data)
        self._apply_ui(data)

    def _apply_providers(self, data: dict[str, Any]) -> None:
        """Apply provider slot and STT language settings."""
        from src.providers import detect_provider as _detect  # noqa: PLC0415
        from src.providers import get_provider_base_url  # noqa: PLC0415

        cfg = self._config

        def _read_slots(raw_slots: list[dict[str, Any]]) -> list[dict[str, str]]:
            result: list[dict[str, str]] = []
            for slot in raw_slots:
                key = str(slot.get("api_key", "")).strip()
                provider = str(slot.get("provider", "")).strip()
                model = str(slot.get("model", "")).strip()
                base_url = ""
                if key:
                    info = _detect(key)
                    if info:
                        base_url = info.base_url
                    elif provider:
                        base_url = get_provider_base_url(provider)
                result.append({"api_key": key, "provider": provider, "base_url": base_url, "model": model})
            return result

        providers = data.get("providers", {})
        if isinstance(providers, dict):
            if "stt" in providers:
                cfg.providers.stt = _read_slots(providers["stt"])
            if "llm" in providers:
                cfg.providers.llm = _read_slots(providers["llm"])
            if "translation" in providers:
                cfg.providers.translation = _read_slots(providers["translation"])

        # Backward compat: copy first STT key to groq config
        if cfg.providers.stt and cfg.providers.stt[0].get("api_key"):
            cfg.groq.api_key = cfg.providers.stt[0]["api_key"]
            cfg.groq.stt_model = cfg.providers.stt[0].get("model", "whisper-large-v3-turbo")
        if cfg.providers.llm and cfg.providers.llm[0].get("api_key"):
            cfg.groq.llm_model = cfg.providers.llm[0].get("model", "llama-3.3-70b-versatile")

        # STT language
        stt_language = data.get("groq", {}).get("stt_language")
        if stt_language is not None:
            cfg.groq.stt_language = stt_language if stt_language else None

    def _apply_audio(self, data: dict[str, Any]) -> None:
        """Apply audio settings from incoming data."""
        cfg = self._config
        audio = data.get("audio", {})
        if not isinstance(audio, dict):
            return
        if "mic_device_index" in audio:
            val = audio["mic_device_index"]
            cfg.audio.mic_device_index = int(val) if val is not None else None
        if "vad_aggressiveness" in audio:
            cfg.audio.vad_aggressiveness = int(audio["vad_aggressiveness"])
        if "silence_threshold_ms" in audio:
            cfg.audio.silence_threshold_ms = int(audio["silence_threshold_ms"])
        if "gain" in audio:
            cfg.audio.gain = float(audio["gain"])

    def _apply_dictation(self, data: dict[str, Any]) -> None:
        """Apply hotkey, normalization, and text injection settings."""
        cfg = self._config
        if "hotkey" in data:
            cfg.hotkey = str(data["hotkey"]).strip()
            cfg.ptt_key = cfg.hotkey
        if "hotkey_mode" in data:
            cfg.hotkey_mode = str(data["hotkey_mode"])

        norm = data.get("normalization", {})
        if isinstance(norm, dict) and "enabled" in norm:
            cfg.normalization.enabled = bool(norm["enabled"])

        text_inj = data.get("text_injection", {})
        if isinstance(text_inj, dict) and "method" in text_inj:
            cfg.text_injection.method = str(text_inj["method"])

    def _apply_ui(self, data: dict[str, Any]) -> None:
        """Apply UI, telemetry, and interface settings."""
        cfg = self._config
        ui = data.get("ui", {})
        if isinstance(ui, dict):
            if "sound_on_start" in ui:
                cfg.ui.sound_on_start = bool(ui["sound_on_start"])
            if "sound_on_stop" in ui:
                cfg.ui.sound_on_stop = bool(ui["sound_on_stop"])
            if "show_notifications" in ui:
                cfg.ui.show_notifications = bool(ui["show_notifications"])
            if "language" in ui:
                cfg.ui.language = str(ui["language"])

        telemetry = data.get("telemetry", {})
        if isinstance(telemetry, dict) and "enabled" in telemetry:
            cfg.telemetry.enabled = bool(telemetry["enabled"])

    def _write_config(self) -> None:
        """Write current config to ``config.yaml`` in APPDATA."""
        from src.config import APP_DIR  # noqa: PLC0415

        APP_DIR.mkdir(parents=True, exist_ok=True)
        save_path = APP_DIR / "config.yaml"
        try:
            data = self._config.to_dict()
            with save_path.open("w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            logger.info("Config saved to %s", save_path)
        except Exception:
            logger.exception("Failed to save config")

    def _write_env(self) -> None:
        """Write the primary API key to ``.env`` in APPDATA."""
        from src.config import APP_DIR  # noqa: PLC0415

        APP_DIR.mkdir(parents=True, exist_ok=True)
        env_path = APP_DIR / ".env"
        try:
            with env_path.open("w", encoding="utf-8") as f:
                f.write(f"GROQ_API_KEY={self._config.groq.api_key}\n")
            logger.info("API key saved to %s", env_path)
        except Exception:
            logger.exception("Failed to save .env")

    @staticmethod
    def _load_theme() -> str:
        """Load theme preference from ``translate_settings.json``."""
        from src.utils import load_translate_settings  # noqa: PLC0415

        return load_translate_settings().get("theme", "auto")

    @staticmethod
    def _save_theme(theme: str) -> None:
        """Persist theme preference into ``translate_settings.json``."""
        from src.utils import save_translate_settings  # noqa: PLC0415

        save_translate_settings({"theme": theme})

    @staticmethod
    def _get_autostart() -> bool:
        """Check if the app is registered for Windows startup."""
        if sys.platform != "win32":
            return False
        try:
            import winreg  # noqa: PLC0415

            from src.config import APP_NAME  # noqa: PLC0415

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except Exception:
            return False

    @staticmethod
    def _set_autostart(enabled: bool) -> None:
        """Add or remove the app from Windows startup."""
        if sys.platform != "win32":
            return
        try:
            import winreg  # noqa: PLC0415

            from src.config import APP_NAME  # noqa: PLC0415

            reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_key, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    exe_path = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m src.main'
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
                    logger.info("Autostart enabled")
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                        logger.info("Autostart disabled")
                    except FileNotFoundError:
                        pass
        except Exception:
            logger.exception("Failed to set autostart")


# Alias used by settings_window.py
SettingsBridge = WebBridge

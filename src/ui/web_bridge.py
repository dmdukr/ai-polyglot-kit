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

    PyWebView sometimes passes extra positional args to bridge methods.
    We try the call as-is first, then retry with only self on TypeError.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except TypeError:
            # PyWebView may pass extra args — retry with just self
            if args:
                try:
                    return method(args[0])
                except Exception as exc:
                    logger.exception("WebBridge.%s failed", method.__name__)
                    return {"success": False, "error": str(exc)}
            raise
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
        logger.debug("bridge.set_window(%s)", type(window).__name__)
        self._window = window

    # ------------------------------------------------------------------
    # Window management (frameless titlebar buttons)
    # ------------------------------------------------------------------

    def window_minimize(self) -> None:
        """Minimize the settings window."""
        logger.debug("bridge.window_minimize()")
        if self._window:
            self._window.minimize()

    def window_maximize(self) -> None:
        """Toggle maximize/restore the settings window."""
        logger.debug("bridge.window_maximize()")
        if self._window:
            self._window.toggle_fullscreen()

    def window_close(self) -> None:
        """Close the settings window."""
        logger.debug("bridge.window_close()")
        if self._window:
            self._window.destroy()

    def window_set_theme(self, theme: str) -> None:
        """Repaint native Windows title bar for dark/light theme."""
        logger.debug("bridge.window_set_theme(%s)", theme)
        if not self._window or sys.platform != "win32":
            return
        try:
            from src.ui.settings_window import set_titlebar_theme  # noqa: PLC0415

            set_titlebar_theme(self._window, theme)
        except Exception:
            logger.debug("Could not set titlebar theme", exc_info=True)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @_safe
    def get_config(self) -> dict[str, Any]:
        """Return config as UI payload."""
        from src.ui.settings_contract import config_to_ui  # noqa: PLC0415

        logger.debug("bridge.get_config()")
        data = config_to_ui(self._config)
        data["theme"] = self._load_theme()
        logger.debug("bridge.get_config → %d keys", len(data))
        return data

    @_safe
    def save_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply UI payload back to config and persist."""
        from src.ui.settings_contract import ui_to_config  # noqa: PLC0415

        logger.debug("bridge.save_config(%d keys)", len(data))
        theme = data.pop("theme", None)
        if theme:
            self._save_theme(theme)

        ui_to_config(data, self._config)
        self._write_config()
        self._write_env()

        if self._on_save is not None:
            self._on_save(restart=True)
        logger.debug("bridge.save_config → success")
        return {"success": True}

    @_safe
    def get_version(self) -> dict[str, Any]:
        """Return application name, version, and update availability."""
        from src.config import APP_NAME, APP_VERSION  # noqa: PLC0415

        logger.debug("bridge.get_version()")
        result: dict[str, Any] = {"version": APP_VERSION, "app_name": APP_NAME}
        try:
            from src.updater import Updater  # noqa: PLC0415
            update = Updater().check_now()
            if update:
                result["update_available"] = True
                result["latest"] = update.get("version", "")
        except Exception:
            logger.debug("bridge.get_version — update check failed", exc_info=True)
        logger.debug("bridge.get_version → %s", result)
        return result

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    @_safe
    def get_audio_devices(self) -> list[dict[str, Any]]:
        """Enumerate input audio devices.

        Returns a list of ``{"index": int, "name": str, "is_current": bool}``.
        """
        logger.debug("bridge.get_audio_devices()")
        if self._audio is None:
            logger.debug("bridge.get_audio_devices → [] (no audio capture)")
            return []

        devices = self._audio.list_devices()
        current_idx = self._config.audio.mic_device_index
        result = [
            {
                "index": d.index,
                "name": d.name,
                "is_current": d.index == current_idx,
            }
            for d in devices
        ]
        logger.debug("bridge.get_audio_devices → %d devices", len(result))
        return result

    @_safe
    def test_audio(self, device_index: int) -> dict[str, Any]:
        """Run a quick audio level test on the given device.

        Returns ``{"success": True, "rms_db": float}`` or an error dict.
        """
        logger.debug("bridge.test_audio(device_index=%s)", device_index)
        if self._audio is None:
            logger.debug("bridge.test_audio → error (no AudioCapture)")
            return {"success": False, "error": "AudioCapture not available"}

        import math  # noqa: PLC0415
        import struct  # noqa: PLC0415

        try:
            import pyaudio  # noqa: PLC0415
        except ImportError:
            logger.debug("bridge.test_audio → error (PyAudio not installed)")
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
            logger.debug("bridge.test_audio → error (no audio data)")
            return {"success": False, "error": "No audio data"}

        samples = struct.unpack(f"<{n_samples}h", frames)
        rms = math.sqrt(sum(s * s for s in samples) / n_samples)
        rms_db = 20 * math.log10(max(rms, 1e-10))

        logger.debug("bridge.test_audio → rms_db=%.1f", rms_db)
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
        masked_key = api_key[:4] + "***" if len(api_key) > 4 else "****"  # noqa: PLR2004
        logger.debug("bridge.detect_provider(api_key=%s)", masked_key)
        from src.providers import detect_provider as _detect  # noqa: PLC0415

        info = _detect(api_key)
        if info is None:
            logger.debug("bridge.detect_provider → None (unknown prefix)")
            return None
        logger.debug("bridge.detect_provider → provider=%s", info.name)
        return {
            "name": info.name,
            "base_url": info.base_url,
            "supports_stt": info.supports_stt,
            "supports_llm": info.supports_llm,
        }

    @_safe
    def fetch_models(self, api_key: str, base_url: str) -> list[str]:
        """Fetch available model IDs from a provider's ``/models`` endpoint."""
        masked_key = api_key[:4] + "***" if len(api_key) > 4 else "****"  # noqa: PLR2004
        logger.debug("bridge.fetch_models(api_key=%s, base_url=%s)", masked_key, base_url)
        from src.providers import fetch_models as _fetch  # noqa: PLC0415

        result = _fetch(base_url, api_key)
        logger.debug("bridge.fetch_models → %d models", len(result))
        return result

    # ------------------------------------------------------------------
    # Dictionary
    # ------------------------------------------------------------------

    @_safe
    def get_dictionary(self) -> list[dict[str, Any]]:
        """Return all dictionary terms."""
        logger.debug("bridge.get_dictionary()")
        db = _get_db()
        if db is None:
            logger.debug("bridge.get_dictionary → [] (no db)")
            return []

        rows = db.execute(
            "SELECT id, source_text, target_text, term_type, origin, hit_count FROM dictionary ORDER BY id"
        ).fetchall()
        result = [
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
        logger.debug("bridge.get_dictionary → %d terms", len(result))
        return result

    @_safe
    def add_dictionary_term(self, source: str, target: str, term_type: str = "exact") -> dict[str, Any]:
        """Add a dictionary term.  Returns ``{"success": True, "id": int}``."""
        logger.debug("bridge.add_dictionary_term(source=%r, target=%r, type=%s)", source, target, term_type)
        db = _get_db()
        if db is None:
            logger.debug("bridge.add_dictionary_term → error (no db)")
            return {"success": False, "error": "Database not configured"}

        from src.context.dictionary import add_term  # noqa: PLC0415

        term_id = add_term(db, source, target, term_type=term_type, origin="manual")
        logger.debug("bridge.add_dictionary_term → id=%s", term_id)
        return {"success": True, "id": term_id}

    @_safe
    def remove_dictionary_term(self, term_id: int) -> dict[str, Any]:
        """Remove a dictionary term by ID."""
        logger.debug("bridge.remove_dictionary_term(term_id=%s)", term_id)
        db = _get_db()
        if db is None:
            logger.debug("bridge.remove_dictionary_term → error (no db)")
            return {"success": False, "error": "Database not configured"}

        from src.context.dictionary import remove_term  # noqa: PLC0415

        remove_term(db, term_id)
        logger.debug("bridge.remove_dictionary_term → success")
        return {"success": True}

    @_safe
    def import_dictionary(self, data: str) -> dict[str, Any]:
        """Import dictionary terms from a JSON string.

        Returns ``{"success": True, "count": int}``.
        """
        logger.debug("bridge.import_dictionary(data_len=%d)", len(data))
        db = _get_db()
        if db is None:
            logger.debug("bridge.import_dictionary → error (no db)")
            return {"success": False, "error": "Database not configured"}

        from src.context.dictionary import import_terms  # noqa: PLC0415

        terms = json.loads(data)
        count = import_terms(db, terms)
        logger.debug("bridge.import_dictionary → imported %d terms", count)
        return {"success": True, "count": count}

    @_safe
    def export_dictionary(self) -> str:
        """Export all dictionary terms as a JSON string."""
        logger.debug("bridge.export_dictionary()")
        db = _get_db()
        if db is None:
            logger.debug("bridge.export_dictionary → empty (no db)")
            return "[]"

        from src.context.dictionary import export_terms  # noqa: PLC0415

        terms = export_terms(db)
        result = json.dumps(terms, ensure_ascii=False, indent=2)
        logger.debug("bridge.export_dictionary → %d terms, %d chars", len(terms), len(result))
        return result

    # ------------------------------------------------------------------
    # Replacements
    # ------------------------------------------------------------------

    @_safe
    def get_replacements(self) -> list[dict[str, Any]]:
        """Return all replacement rules from the DB."""
        logger.debug("bridge.get_replacements()")
        db = _get_db()
        if db is None:
            logger.debug("bridge.get_replacements → [] (no db)")
            return []

        rows = db.execute(
            "SELECT id, trigger_text, replacement_text, match_mode, is_sensitive, hit_count "
            "FROM replacements ORDER BY id"
        ).fetchall()
        result = [
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
        logger.debug("bridge.get_replacements → %d rules", len(result))
        return result

    @_safe
    def add_replacement(
        self,
        trigger: str,
        replacement: str,
        match_mode: str = "fuzzy",
        is_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Add a replacement rule.  Returns ``{"success": True, "id": int}``."""
        logger.debug(
            "bridge.add_replacement(trigger=%r, replacement=%r, match_mode=%s, is_sensitive=%s)",
            trigger,
            replacement,
            match_mode,
            is_sensitive,
        )
        db = _get_db()
        if db is None:
            logger.debug("bridge.add_replacement → error (no db)")
            return {"success": False, "error": "Database not configured"}

        cursor = db.execute(
            "INSERT INTO replacements (trigger_text, replacement_text, match_mode, is_sensitive) VALUES (?, ?, ?, ?)",
            [trigger, replacement, match_mode, int(is_sensitive)],
        )
        db.commit()
        logger.debug("bridge.add_replacement → id=%s", cursor.lastrowid)
        return {"success": True, "id": cursor.lastrowid}

    @_safe
    def remove_replacement(self, replacement_id: int) -> dict[str, Any]:
        """Remove a replacement rule by ID."""
        logger.debug("bridge.remove_replacement(replacement_id=%s)", replacement_id)
        db = _get_db()
        if db is None:
            logger.debug("bridge.remove_replacement → error (no db)")
            return {"success": False, "error": "Database not configured"}

        db.execute("DELETE FROM replacements WHERE id = ?", [replacement_id])
        db.commit()
        logger.debug("bridge.remove_replacement → success")
        return {"success": True}

    # ------------------------------------------------------------------
    # Scripts / Per-App rules
    # ------------------------------------------------------------------

    @_safe
    def get_scripts(self) -> list[dict[str, Any]]:
        """Return all formatting scripts."""
        logger.debug("bridge.get_scripts()")
        db = _get_db()
        if db is None:
            logger.debug("bridge.get_scripts → [] (no db)")
            return []

        rows = db.execute("SELECT id, name, body, is_builtin FROM scripts ORDER BY id").fetchall()
        result = [
            {
                "id": r["id"],
                "name": r["name"],
                "body": r["body"],
                "is_builtin": bool(r["is_builtin"]),
            }
            for r in rows
        ]
        logger.debug("bridge.get_scripts → %d scripts", len(result))
        return result

    @_safe
    def save_script(self, name: str, body: str) -> dict[str, Any]:
        """Validate and save a formatting script.

        Uses the deterministic check from
        :mod:`src.context.script_validator`.  Returns
        ``{"success": True, "id": int}`` or an error with violations.
        """
        logger.debug("bridge.save_script(name=%r, body_len=%d)", name, len(body))
        from src.context.script_validator import deterministic_check  # noqa: PLC0415

        violations = deterministic_check(body)
        if violations:
            logger.debug("bridge.save_script → validation failed (%d violations)", len(violations))
            return {"success": False, "error": "Validation failed", "violations": violations}

        db = _get_db()
        if db is None:
            logger.debug("bridge.save_script → error (no db)")
            return {"success": False, "error": "Database not configured"}

        cursor = db.execute(
            "INSERT INTO scripts (name, body) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET body = excluded.body",
            [name, body],
        )
        db.commit()
        logger.debug("bridge.save_script → id=%s", cursor.lastrowid)
        return {"success": True, "id": cursor.lastrowid}

    @_safe
    def get_app_rules(self) -> list[dict[str, Any]]:
        """Return all application -> script mapping rules."""
        logger.debug("bridge.get_app_rules()")
        db = _get_db()
        if db is None:
            logger.debug("bridge.get_app_rules → [] (no db)")
            return []

        rows = db.execute(
            "SELECT ar.id, ar.app_name, ar.script_id, s.name AS script_name "
            "FROM app_rules ar LEFT JOIN scripts s ON ar.script_id = s.id "
            "ORDER BY ar.id"
        ).fetchall()
        result = [
            {
                "id": r["id"],
                "app_name": r["app_name"],
                "script_id": r["script_id"],
                "script_name": r["script_name"],
            }
            for r in rows
        ]
        logger.debug("bridge.get_app_rules → %d rules", len(result))
        return result

    @_safe
    def save_app_rule(self, app_name: str, script_id: int) -> dict[str, Any]:
        """Save (upsert) an application rule."""
        logger.debug("bridge.save_app_rule(app_name=%r, script_id=%s)", app_name, script_id)
        db = _get_db()
        if db is None:
            logger.debug("bridge.save_app_rule → error (no db)")
            return {"success": False, "error": "Database not configured"}

        cursor = db.execute(
            "INSERT INTO app_rules (app_name, script_id) VALUES (?, ?) "
            "ON CONFLICT(app_name) DO UPDATE SET script_id = excluded.script_id",
            [app_name, script_id],
        )
        db.commit()
        logger.debug("bridge.save_app_rule → id=%s", cursor.lastrowid)
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
        logger.debug(
            "bridge.get_history(limit=%s, offset=%s, app_filter=%r, time_filter=%s)",
            limit,
            offset,
            app_filter,
            time_filter,
        )
        db = _get_db()
        if db is None:
            logger.debug("bridge.get_history → empty (no db)")
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

        logger.debug("bridge.get_history → %d items, total=%d", len(items), total)
        return {"items": items, "total": total}

    @_safe
    def delete_history(self, ids: list[int]) -> dict[str, Any]:
        """Delete history entries by ID list."""
        logger.debug("bridge.delete_history(ids=%s)", ids)
        db = _get_db()
        if db is None:
            logger.debug("bridge.delete_history → error (no db)")
            return {"success": False, "error": "Database not configured"}

        if not ids:
            logger.debug("bridge.delete_history → success (empty list)")
            return {"success": True}

        placeholders = ",".join("?" for _ in ids)
        db.execute(f"DELETE FROM history WHERE id IN ({placeholders})", ids)  # noqa: S608
        db.commit()
        logger.debug("bridge.delete_history → deleted %d entries", len(ids))
        return {"success": True}

    # ------------------------------------------------------------------
    # Browser extensions
    # ------------------------------------------------------------------

    @_safe
    def find_browsers(self) -> list[dict[str, Any]]:
        """Detect installed Chromium-based browsers."""
        logger.debug("bridge.find_browsers()")
        from src.browser_installer import find_browsers as _find  # noqa: PLC0415
        from src.browser_installer import is_extension_installed  # noqa: PLC0415

        browsers = _find()
        result = [
            {
                "name": b.name,
                "exe_path": str(b.exe_path) if b.exe_path else None,
                "extensions_url": b.extensions_url,
                "installed": is_extension_installed(b),
            }
            for b in browsers
        ]
        logger.debug("bridge.find_browsers → %d browsers", len(result))
        return result

    @_safe
    def install_extension(self, browser_name: str) -> dict[str, Any]:
        """Return extension installation info for a browser.

        The actual installation is manual (user must load unpacked in the
        browser).  This method opens the browser and returns the extension
        directory path.
        """
        logger.debug("bridge.install_extension(browser_name=%r)", browser_name)
        from src.browser_installer import find_browsers as _find  # noqa: PLC0415

        browsers = _find()
        target = next((b for b in browsers if b.name == browser_name), None)
        if target is None:
            logger.debug("bridge.install_extension → error (browser not found)")
            return {"success": False, "error": f"Browser '{browser_name}' not found"}

        # Open the browser if possible
        if target.exe_path:
            try:
                subprocess.Popen([str(target.exe_path)])  # noqa: S603
            except Exception as exc:
                logger.warning("Failed to open %s: %s", browser_name, exc)

        ext_dir = Path(__file__).parent.parent.parent / "extension"
        logger.debug("bridge.install_extension → success, ext_dir=%s", ext_dir)
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
        logger.debug("bridge.get_translations()")
        from src.i18n import _STRINGS, get_language  # noqa: PLC0415

        lang = get_language()
        result: dict[str, str] = {}
        for key, translations in _STRINGS.items():
            result[key] = translations.get(lang) or translations.get("en") or key
        logger.debug("bridge.get_translations → lang=%s, %d strings", lang, len(result))
        return result

    @_safe
    def set_language(self, lang: str) -> dict[str, Any]:
        """Change the UI language, refresh tray menu, return translations."""
        logger.debug("bridge.set_language(%s)", lang)
        from src.i18n import set_language as _set_lang  # noqa: PLC0415

        _set_lang(lang)

        # Update config
        self._config.ui.language = lang

        # Rebuild tray menu with new language
        _refresh_tray_menu()

        logger.debug("bridge.set_language → success, lang=%s", lang)
        return {"success": True, "translations": self.get_translations()}

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @_safe
    def get_stats(self) -> dict[str, Any]:
        """Gather usage statistics from the history table."""
        logger.debug("bridge.get_stats()")
        db = _get_db()
        if db is None:
            logger.debug("bridge.get_stats → empty (no db)")
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

        result = {
            "total_dictations": row["cnt"] if row else 0,
            "total_duration_s": round(row["dur"], 1) if row else 0,
            "total_words": row["words"] if row else 0,
            "corrections": row["corr"] if row else 0,
            "top_apps": [{"app": r["app"], "count": r["cnt"]} for r in top_apps_rows],
        }
        logger.debug(
            "bridge.get_stats → dictations=%s, words=%s, top_apps=%d",
            result["total_dictations"],
            result["total_words"],
            len(result["top_apps"]),
        )
        return result

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    @_safe
    def check_update(self) -> dict[str, Any]:
        """Check GitHub for a newer release.

        Returns ``{"available": True, "version": str, "url": str}``
        or ``{"available": False}``.
        """
        logger.debug("bridge.check_update()")
        from src.updater import Updater  # noqa: PLC0415

        updater = Updater()
        result = updater.check_now()
        if result:
            logger.debug("bridge.check_update → available, version=%s", result.get("version", ""))
            return {
                "available": True,
                "version": result.get("version", ""),
                "url": result.get("url", ""),
            }
        logger.debug("bridge.check_update → no update available")
        return {"available": False}

    @_safe
    def open_logs_folder(self) -> None:
        """Open the logs folder in the system file manager."""
        logger.debug("bridge.open_logs_folder()")
        from src.config import APP_DIR  # noqa: PLC0415

        logs_dir = APP_DIR / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(logs_dir))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(logs_dir)])  # noqa: S603, S607
        logger.debug("bridge.open_logs_folder → opened %s", logs_dir)

    @_safe
    def open_url(self, url: str) -> None:
        """Open a URL in the default web browser."""
        logger.debug("bridge.open_url(%s)", url)
        webbrowser.open(url)
        logger.debug("bridge.open_url → opened")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_config(self) -> None:
        """Write current config to ``config.yaml`` in APPDATA."""
        logger.debug("bridge._write_config()")
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
            logger.debug("bridge._write_config → saved to %s", save_path)
        except Exception:
            logger.exception("Failed to save config")

    def _write_env(self) -> None:
        """Write the primary API key to ``.env`` in APPDATA."""
        logger.debug("bridge._write_env()")
        from src.config import APP_DIR  # noqa: PLC0415

        APP_DIR.mkdir(parents=True, exist_ok=True)
        env_path = APP_DIR / ".env"
        try:
            with env_path.open("w", encoding="utf-8") as f:
                f.write(f"GROQ_API_KEY={self._config.groq.api_key}\n")
            logger.debug("bridge._write_env → saved to %s", env_path)
        except Exception:
            logger.exception("Failed to save .env")

    @staticmethod
    def _load_theme() -> str:
        """Load theme preference from ``translate_settings.json``."""
        logger.debug("bridge._load_theme()")
        from src.utils import load_translate_settings  # noqa: PLC0415

        theme = load_translate_settings().get("theme", "dark")
        logger.debug("bridge._load_theme → %s", theme)
        return theme

    @staticmethod
    def _save_theme(theme: str) -> None:
        """Persist theme preference into ``translate_settings.json``."""
        logger.debug("bridge._save_theme(%s)", theme)
        from src.utils import save_translate_settings  # noqa: PLC0415

        save_translate_settings({"theme": theme})
        logger.debug("bridge._save_theme → saved")


def _refresh_tray_menu() -> None:
    """Rebuild tray menu after language change. Best-effort."""
    import contextlib  # noqa: PLC0415

    with contextlib.suppress(Exception):
        import gc  # noqa: PLC0415

        from src.tray_app import TrayApp  # noqa: PLC0415

        for obj in gc.get_referrers(TrayApp):
            if isinstance(obj, TrayApp) and obj._icon:  # noqa: SLF001
                obj._icon.menu = obj._create_menu()  # noqa: SLF001
                with contextlib.suppress(Exception):
                    obj._icon.update_menu()  # noqa: SLF001
                break


# Alias used by settings_window.py
SettingsBridge = WebBridge

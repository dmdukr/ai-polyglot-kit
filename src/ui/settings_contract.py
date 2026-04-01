"""Settings contract: the single adapter between AppConfig and the Settings SPA.

All config <-> UI mapping lives here.  The rest of the codebase should never
need to know how the SPA dict differs from the Python dataclass layout.

Public API
----------
config_to_ui(config)   — AppConfig  -> dict for JavaScript
ui_to_config(data, config) — SPA dict -> mutates AppConfig in place
"""

from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


def config_to_ui(config: AppConfig) -> dict[str, Any]:
    """Convert an AppConfig to a plain dict for the Settings SPA.

    Adds convenience shortcuts that the SPA expects at the top level:
    - ``language`` — mirrors ``config.ui.language``
    - ``autostart`` — Windows-only startup registration status
    """
    data: dict[str, Any] = asdict(config)
    data["language"] = data["ui"]["language"]
    data["autostart"] = _get_autostart()
    return data


def ui_to_config(data: dict[str, Any], config: AppConfig) -> None:
    """Apply a (possibly partial) SPA dict onto a live AppConfig.

    Handles:
    1. ``language`` shortcut  -> ``ui.language``
    2. ``autostart`` flag     -> Windows registry (no-op on Linux)
    3. Everything else        -> ``config._apply_dict()``
    4. Backward-compat sync   -> ``providers.stt[0].api_key`` -> ``groq.api_key``
    """
    # Work on a shallow copy so we can pop transient keys without mutating caller's dict
    data = dict(data)

    # 1. Language shortcut -> ui.language
    if "language" in data:
        ui_section = data.get("ui")
        if not isinstance(ui_section, dict):
            ui_section = {}
            data["ui"] = ui_section
        ui_section["language"] = data.pop("language")

    # 2. Autostart
    if "autostart" in data:
        _set_autostart(bool(data.pop("autostart")))

    # 3. Apply remaining fields to AppConfig
    config._apply_dict(data)  # noqa: SLF001

    # 4. Backward-compat: sync stt[0].api_key -> groq.api_key
    _sync_stt_key_to_groq(config)


# ---------------------------------------------------------------------------
# Autostart helpers (Windows-only)
# ---------------------------------------------------------------------------


def _get_autostart() -> bool:
    """Check if the app is registered for Windows startup.

    Returns False on non-Windows platforms.
    """
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


def _set_autostart(enabled: bool) -> None:
    """Add or remove the app from Windows startup.

    No-op on non-Windows platforms.
    """
    if sys.platform != "win32":
        return
    try:
        import winreg  # noqa: PLC0415

        from src.config import APP_NAME  # noqa: PLC0415

        reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            reg_key,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sync_stt_key_to_groq(config: AppConfig) -> None:
    """Copy providers.stt[0].api_key -> groq.api_key for backward compat.

    Only overwrites if the STT slot actually contains a non-empty key.
    """
    try:
        stt_slots = config.providers.stt
        if not stt_slots:
            return
        first_key = stt_slots[0].get("api_key", "") if isinstance(stt_slots[0], dict) else ""
        if first_key:
            config.groq.api_key = first_key
    except (IndexError, AttributeError, TypeError):
        pass

"""Prepare bootstrap payload for Settings UI.

Single place responsible for:
- Building the bootstrap JSON (config + translations + lang + theme)
- Injecting it into HTML string (release mode)
Dev mode does not use bootstrap - JS falls back to bridge.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger(__name__)


def build_payload(config: AppConfig) -> dict[str, Any]:
    """Build the bootstrap payload dict for first paint."""
    from src.ui.settings_contract import config_to_ui  # noqa: PLC0415

    lang = config.ui.language if hasattr(config, "ui") else "uk"
    return {
        "lang": lang,
        "theme": _load_theme(),
        "config": config_to_ui(config),
        "translations": _load_translations(),
    }


def prepare_html(config: AppConfig, html: str) -> str:
    """Inject bootstrap payload into HTML string (release mode only)."""
    payload = build_payload(config)
    script = f"<script>var _BOOTSTRAP={json.dumps(payload,ensure_ascii=False)};</script>"
    return html.replace("</head>", f"{script}\n</head>")


def _load_translations() -> dict[str, dict[str, str]]:
    i18n_path = Path(__file__).parent / "web" / "i18n.json"
    if i18n_path.exists():
        return json.loads(i18n_path.read_text(encoding="utf-8"))
    logger.warning("i18n.json not found at %s", i18n_path)
    return {}


def _load_theme() -> str:
    try:
        from src.utils import load_translate_settings  # noqa: PLC0415
        return load_translate_settings().get("theme", "dark")
    except Exception:
        return "dark"

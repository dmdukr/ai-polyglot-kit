"""PyWebView-based settings window launcher.

Opens the settings SPA (src/ui/web/) inside a native WebView2 window.
Falls back gracefully if pywebview is not installed.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.audio_capture import AudioCapture
    from src.config import AppConfig

logger = logging.getLogger(__name__)


def show_settings(
    config: AppConfig,
    audio_capture: AudioCapture,
    on_save: Callable[..., None],
) -> None:
    """Open the PyWebView settings window.

    Args:
        config: The application config to display/edit.
        audio_capture: AudioCapture instance for mic device listing.
        on_save: Callback invoked after user saves settings.

    Raises:
        ImportError: If pywebview is not installed.
    """
    import webview  # noqa: PLC0415  # lazy — may not be installed

    from .web_bridge import SettingsBridge  # noqa: PLC0415

    logger.info("Opening PyWebView settings window")

    bridge = SettingsBridge(config, audio_capture, on_save)

    web_dir = Path(__file__).parent / "web"
    window = webview.create_window(
        "AI Polyglot Kit \u2014 Settings",
        url=str(web_dir / "index.html"),
        js_api=bridge,
        width=820,
        height=640,
        resizable=True,
        min_size=(640, 480),
    )
    bridge.set_window(window)

    # Non-blocking: run in a separate thread so tray stays responsive
    def _run() -> None:
        try:
            webview.start(debug=False)
        except Exception:
            logger.exception("PyWebView settings window error")

    threading.Thread(target=_run, name="SettingsWebView", daemon=True).start()

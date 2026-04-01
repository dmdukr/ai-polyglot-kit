"""Settings window launcher using PyWebView.

Architecture: main thread is kept free for PyWebView windows.
Tray app signals this module when Settings should open.
The main thread event loop in main.py picks up the signal.
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.audio_capture import AudioCapture
    from src.config import AppConfig

logger = logging.getLogger(__name__)

# Signal queue: main thread waits on this for "open settings" commands
_settings_queue: queue.Queue[tuple[AppConfig, AudioCapture | None, Callable[..., None] | None] | None] = queue.Queue()
_window_open = threading.Event()


def show_settings(
    config: AppConfig,
    audio_capture: AudioCapture | None = None,
    on_save: Callable[..., None] | None = None,
) -> None:
    """Request the main thread to open Settings window.

    Called from tray menu callback (runs in pystray thread).
    Puts config on the queue; main thread picks it up.
    """
    if _window_open.is_set():
        logger.info("Settings window already open")
        return

    logger.info("Requesting Settings window open")
    _settings_queue.put((config, audio_capture, on_save))


def run_settings_loop() -> None:
    """Main-thread event loop that opens PyWebView windows on demand.

    Called from main.py after tray.run() starts in a thread.
    Blocks the main thread, waiting for settings open requests.
    """
    while True:
        request = _settings_queue.get()  # blocks until signal
        if request is None:
            break  # shutdown signal

        config, audio_capture, on_save = request

        _window_open.set()
        try:
            _open_webview_window(config, audio_capture, on_save)
        except Exception:
            logger.exception("Settings window error")
        finally:
            _window_open.clear()


def shutdown_settings_loop() -> None:
    """Signal the main-thread loop to exit."""
    _settings_queue.put(None)


def _open_webview_window(
    config: AppConfig,
    audio_capture: AudioCapture | None = None,
    on_save: Callable[..., None] | None = None,
) -> None:
    """Create and show a PyWebView window. Runs on main thread."""
    import sys  # noqa: PLC0415

    import webview  # noqa: PLC0415

    from src.ui.web_bridge import WebBridge  # noqa: PLC0415

    bridge = WebBridge(config, audio_capture, on_save)
    web_dir = _find_web_dir()
    if web_dir is None:
        logger.error("Cannot find web UI directory")
        return

    if not getattr(sys, "frozen", False):
        # Dev mode: load from file, JS uses bridge for config
        url = (web_dir / "index.html").as_uri()
        window = webview.create_window(
            "AI Polyglot Kit \u2014 Settings",
            url=url, js_api=bridge,
            width=900, height=640, resizable=True,
            min_size=(700, 500), background_color="#1e1e2e",
        )
    else:
        # Release mode: load bundled HTML with bootstrap payload
        from src.ui.settings_bootstrap import prepare_html  # noqa: PLC0415
        bundled = web_dir / "_bundled.html"
        if bundled.exists():
            html = bundled.read_text(encoding="utf-8")
        else:
            html = (web_dir / "index.html").read_text(encoding="utf-8")
        html = prepare_html(config, html)
        window = webview.create_window(
            "AI Polyglot Kit \u2014 Settings",
            html=html, js_api=bridge,
            width=900, height=640, resizable=True,
            min_size=(700, 500), background_color="#1e1e2e",
        )

    bridge.set_window(window)
    logger.info("PyWebView Settings window created")
    webview.start(debug=not getattr(sys, "frozen", False))
    logger.info("PyWebView Settings window closed")


def _find_web_dir() -> Path | None:
    """Find the web UI directory."""
    import sys  # noqa: PLC0415

    candidates = [
        Path(__file__).parent / "web",
        Path(getattr(sys, "_MEIPASS", "")) / "src" / "ui" / "web",
    ]
    for c in candidates:
        if c.is_dir() and (c / "index.html").exists():
            return c
    return None

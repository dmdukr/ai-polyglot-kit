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
    import webview  # noqa: PLC0415

    from src.config import APP_DIR  # noqa: PLC0415
    from src.ui.web_bridge import SettingsBridge  # noqa: PLC0415

    bridge = SettingsBridge(config, audio_capture, on_save)

    web_dir = _find_web_dir()
    if web_dir is None:
        logger.error("Cannot find web UI directory")
        return

    logger.info("web_dir=%s, files=%s", web_dir, list(web_dir.glob("*"))[:10])

    # Load HTML and apply translations server-side (no JS race conditions)
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    lang = config.ui.language if hasattr(config, "ui") and hasattr(config.ui, "language") else "uk"
    # Also check what's actually in config.yaml on disk
    import yaml as _yaml  # noqa: PLC0415

    _cfg_path = APP_DIR / "config.yaml"
    _disk_lang = "?"
    if _cfg_path.exists():
        try:
            with _cfg_path.open(encoding="utf-8") as _f:
                _disk = _yaml.safe_load(_f) or {}
            _disk_lang = _disk.get("ui", {}).get("language", "NOT SET")
        except Exception:
            _disk_lang = "READ ERROR"
    else:
        _disk_lang = "NO FILE"
    logger.info("i18n: lang=%s, disk_lang=%s, config_path=%s", lang, _disk_lang, _cfg_path)
    html_path = web_dir / "index.html"
    html_content = html_path.read_text(encoding="utf-8")
    logger.info("i18n: HTML loaded, %d bytes", len(html_content))

    # Apply translations directly in HTML if not English
    if lang != "en":
        translations: dict[str, str] = {}

        # 1) Try standalone i18n.json
        i18n_path = web_dir / "i18n.json"
        if i18n_path.exists():
            all_i18n = json.loads(i18n_path.read_text(encoding="utf-8"))
            translations = all_i18n.get(lang, {})
            logger.info("i18n: loaded %d keys from i18n.json", len(translations))

        # 2) Try extracting from inline JS in HTML (greedy match between = and ;)
        if not translations:
            m = re.search(r"var _EMBEDDED_I18N\s*=\s*(\{.+\});\s*$", html_content, re.MULTILINE)
            if m:
                try:
                    all_i18n = json.loads(m.group(1))
                    translations = all_i18n.get(lang, {})
                    logger.info("i18n: extracted %d keys from inline JS", len(translations))
                except json.JSONDecodeError:
                    logger.warning("i18n: failed to parse inline _EMBEDDED_I18N")

        if not translations:
            logger.warning("i18n: no translations found for lang=%s", lang)

        if translations:
            # Replace text content of data-i18n elements
            def _replace_i18n(match: re.Match[str]) -> str:
                key = match.group(1)
                after_tag = match.group(2)
                old_text = match.group(3)
                translated = translations.get(key, old_text)
                return f'data-i18n="{key}"{after_tag}{translated}<'

            html_content = re.sub(
                r'data-i18n="([^"]+)"([^>]*)>([^<]*)<',
                _replace_i18n,
                html_content,
            )
            logger.info("Applied %d translations to HTML (%s)", len(translations), lang)

    html_content = html_content.replace(
        '<html lang="en" data-theme="dark">',
        f'<html lang="{lang}" data-theme="dark" data-initial-lang="{lang}">',
    )

    # Set correct language in dropdown (remove any existing 'selected', add to correct option)
    html_content = html_content.replace(
        f'<option value="{lang}">',
        f'<option value="{lang}" selected>',
    )

    window = webview.create_window(
        "AI Polyglot Kit \u2014 Settings",
        html=html_content,
        js_api=bridge,
        width=900,
        height=640,
        resizable=True,
        min_size=(700, 500),
        background_color="#1e1e2e",
        on_top=True,
    )
    bridge.set_window(window)

    # Clear WebView2 cache to ensure fresh JS/CSS/HTML
    def _clear_cache() -> None:
        import contextlib  # noqa: PLC0415

        with contextlib.suppress(Exception):
            window.evaluate_js("caches && caches.keys().then(k => k.forEach(n => caches.delete(n)))")

    logger.info("PyWebView Settings window created")

    def _on_shown() -> None:
        """Paint native title bar after window is shown."""
        try:
            set_titlebar_theme(window, "dark")
        except Exception:
            logger.debug("Could not set titlebar theme", exc_info=True)

    window.events.shown += _on_shown
    webview.start(debug=False)
    logger.info("PyWebView Settings window closed")


def set_titlebar_theme(window: object, theme: str = "dark") -> None:
    """Paint native Windows title bar using DWM API. Supports 'dark' and 'light'."""
    import contextlib  # noqa: PLC0415
    import ctypes  # noqa: PLC0415
    import ctypes.wintypes  # noqa: PLC0415

    hwnd = None
    with contextlib.suppress(Exception):
        hwnd = window.gui.BrowserView.Handle.ToInt32()  # type: ignore[union-attr]
    if not hwnd:
        with contextlib.suppress(Exception):
            hwnd = ctypes.windll.user32.FindWindowW(None, "AI Polyglot Kit \u2014 Settings")
    if not hwnd:
        return

    is_dark = theme == "dark"

    # Dark mode attribute (attr 20)
    value = ctypes.c_int(1 if is_dark else 0)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))

    # Caption color (attr 35, Win11 22H2+): dark #1e1e2e / light #f0ece4 in BGR
    caption_bgr = ctypes.c_int(0x002E1E1E if is_dark else 0x00E4ECF0)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption_bgr), ctypes.sizeof(caption_bgr))

    # Text color (attr 36, Win11 22H2+): dark #e0e0e8 / light #2c2520 in BGR
    text_bgr = ctypes.c_int(0x00E8E0E0 if is_dark else 0x0020252C)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_bgr), ctypes.sizeof(text_bgr))


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

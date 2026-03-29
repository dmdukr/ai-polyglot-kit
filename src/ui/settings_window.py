"""Settings window launcher.

Strategy:
1. If running from source (not frozen) and pywebview available:
   launch _settings_main.py as subprocess with system Python
2. If frozen (PyInstaller) or pywebview unavailable:
   serve web UI on localhost and open in default browser
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.audio_capture import AudioCapture
    from src.config import AppConfig

logger = logging.getLogger(__name__)

_settings_proc: subprocess.Popen[bytes] | None = None
_http_server: HTTPServer | None = None
_HTTP_PORT = 19379


def show_settings(
    config: AppConfig,  # noqa: ARG001
    audio_capture: AudioCapture | None = None,  # noqa: ARG001
    on_save: Callable[..., None] | None = None,  # noqa: ARG001
) -> None:
    """Open the Settings UI."""
    # Try PyWebView subprocess first (only works from source with python.exe)
    if not getattr(sys, "frozen", False):
        try:
            _show_pywebview()
        except Exception:
            logger.info("PyWebView launch failed, falling back to browser")
        else:
            return

    # Fallback: serve via HTTP + open browser
    _show_in_browser()


def _show_pywebview() -> None:
    """Launch _settings_main.py as subprocess (works from source only)."""
    global _settings_proc  # noqa: PLW0603

    if _settings_proc is not None and _settings_proc.poll() is None:
        logger.info("Settings window already open")
        return

    config_path = str(Path("config.yaml").resolve())
    launcher = str(Path(__file__).parent / "_settings_main.py")

    _settings_proc = subprocess.Popen(  # noqa: S603
        [sys.executable, launcher, config_path],
        cwd=str(Path(__file__).parent.parent.parent),
    )
    logger.info("Settings PyWebView launched (PID %s)", _settings_proc.pid)


def _show_in_browser() -> None:
    """Serve web UI on localhost and open in default browser."""
    global _http_server  # noqa: PLW0603

    web_dir = _find_web_dir()
    if web_dir is None:
        logger.error("Cannot find web UI directory")
        return

    # Start HTTP server if not running
    if _http_server is None:
        handler = _make_handler(web_dir)
        try:
            _http_server = HTTPServer(("127.0.0.1", _HTTP_PORT), handler)
        except OSError:
            logger.info("HTTP server already running on port %d", _HTTP_PORT)
            webbrowser.open(f"http://127.0.0.1:{_HTTP_PORT}/index.html")
            return

        t = threading.Thread(target=_http_server.serve_forever, name="SettingsHTTP", daemon=True)
        t.start()
        logger.info("Settings HTTP server started on port %d", _HTTP_PORT)

    webbrowser.open(f"http://127.0.0.1:{_HTTP_PORT}/index.html")


def _find_web_dir() -> Path | None:
    """Find the web UI directory in various locations."""
    candidates = [
        Path(__file__).parent / "web",
        Path(getattr(sys, "_MEIPASS", "")) / "src" / "ui" / "web" if getattr(sys, "frozen", False) else None,
    ]
    for c in candidates:
        if c is not None and c.is_dir() and (c / "index.html").exists():
            return c
    return None


def _make_handler(web_dir: Path) -> type[SimpleHTTPRequestHandler]:
    """Create a handler class that serves from web_dir."""
    directory = str(web_dir)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=directory, **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # Suppress HTTP logs

    return Handler

"""PyWebView-based settings window launcher.

Opens the settings SPA (src/ui/web/) inside a native WebView2 window.
Runs as a separate Python process since pywebview requires the main thread.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.audio_capture import AudioCapture
    from src.config import AppConfig

logger = logging.getLogger(__name__)

_settings_proc: subprocess.Popen[bytes] | None = None


def show_settings(
    config: AppConfig,
    audio_capture: AudioCapture | None = None,
    on_save: Callable[..., None] | None = None,
) -> None:
    """Open the PyWebView settings window in a subprocess."""
    global _settings_proc  # noqa: PLW0603

    if _settings_proc is not None and _settings_proc.poll() is None:
        logger.info("Settings window already open")
        return

    config_path = str(Path("config.yaml").resolve())
    launcher = str(Path(__file__).parent / "_settings_main.py")

    _settings_proc = subprocess.Popen(
        [sys.executable, launcher, config_path],
        cwd=str(Path(__file__).parent.parent.parent),
    )
    logger.info("Settings window process started (PID %s)", _settings_proc.pid)

"""Standalone entry point for the PyWebView Settings window.

Launched as a subprocess — pywebview requires the main thread.
Usage: python _settings_main.py [config_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path
_root = str(Path(__file__).parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)


def main() -> None:
    """Create and run the PyWebView settings window."""
    import webview

    from src.config import AppConfig
    from src.ui.web_bridge import SettingsBridge

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = AppConfig.load(Path(config_path))

    bridge = SettingsBridge(config, None, None)

    web_dir = Path(__file__).parent / "web"
    window = webview.create_window(
        "AI Polyglot Kit \u2014 Settings",
        url=str(web_dir / "index.html"),
        js_api=bridge,
        width=900,
        height=640,
        resizable=True,
        min_size=(700, 500),
        background_color="#1e1e2e",
    )
    bridge.set_window(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()

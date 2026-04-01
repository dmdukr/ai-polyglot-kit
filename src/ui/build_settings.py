"""Bundle Settings UI for release + generate i18n-data.js.

Outputs (both gitignored):
  1. js/i18n-data.js — generated from i18n.json
  2. _bundled.html   — everything inlined for PyInstaller

Usage: python -m src.ui.build_settings
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"


def generate_i18n_data_js() -> None:
    """Generate js/i18n-data.js from i18n.json."""
    i18n = (WEB_DIR / "i18n.json").read_text(encoding="utf-8")
    out = WEB_DIR / "js" / "i18n-data.js"
    out.write_text(f"var _EMBEDDED_I18N = {i18n.strip()};\n", encoding="utf-8")
    logger.info("Generated: %s", out)


def build_bundle() -> None:
    """Bundle index.html with all external assets inlined."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # Inline CSS
    css_path = WEB_DIR / "css" / "styles.css"
    if css_path.exists():
        css = css_path.read_text(encoding="utf-8")
        html = re.sub(
            r'<link\s+rel="stylesheet"\s+href="css/styles\.css"\s*/?>',
            f"<style>\n{css}\n</style>",
            html,
        )

    # Inline all JS
    def inline_js(match: re.Match[str]) -> str:
        src = match.group(1)
        js_path = WEB_DIR / src
        if js_path.exists():
            return f"<script>\n{js_path.read_text(encoding='utf-8')}\n</script>"
        return match.group(0)

    html = re.sub(r'<script src="(js/[^"]+)"></script>', inline_js, html)

    out = WEB_DIR / "_bundled.html"
    out.write_text(html, encoding="utf-8")
    logger.info("Bundled: %s (%d bytes)", out, len(html))


def build() -> None:
    generate_i18n_data_js()
    build_bundle()


if __name__ == "__main__":
    build()

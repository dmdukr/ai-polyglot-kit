# AI Polyglot Kit — Project Rules

## Project Overview
Windows desktop app (PyInstaller) for voice dictation with AI-powered STT, LLM normalization, browser translation extension. Python backend + Chrome Extension (MV3) frontend.

## Architecture
- **Backend:** Python 3.12+, PyAudio, WebRTC VAD, HTTP server, tkinter UI
- **Extension:** Chrome MV3 (content.js, background.js, popup.js)
- **Build:** PyInstaller (onedir) → Inno Setup installer
- **Target:** Windows 10/11, Chromium browsers

## Code Quality Standards

### Python (src/)
- **Linter/Formatter:** `ruff check` + `ruff format` (all rules enabled)
- **Type checker:** `mypy --strict` — all new code must be fully typed
- **Security:** `bandit -r src/` — no high/medium findings allowed
- **Complexity:** `radon cc src/ -a -nc` — no function above CC=10
- **Dead code:** `vulture src/` — no unused exports
- **Tests:** `pytest tests/ --cov=src --cov-fail-under=80`
- **Secrets:** `detect-secrets scan` — no secrets in committed code
- **Dependencies:** `pip-audit` — no known CVEs

### JavaScript (extension/)
- **Linter:** `eslint extension/` with recommended config
- **No external dependencies** — vanilla JS only

### Commit Rules
- All analysis pipelines MUST pass before commit
- English commit messages, conventional commits format
- Code comments and documentation in English
- UI strings via i18n module (uk/en)

## Agent Rules

### Backend Agent (Python)
- Follow existing patterns in src/ (dataclass configs, logger per module, threading with locks)
- All new modules: type hints, docstrings, `from __future__ import annotations`
- Audio pipeline: 16kHz mono 16-bit PCM, 30ms frames, thread-safe queues
- Config changes: add to dataclass in config.py + YAML loader + settings UI
- No global state — pass dependencies via constructor injection
- Error handling: log + propagate, never silently swallow exceptions
- Windows-specific code: guard with platform checks, use ctypes for Win32 API

### Frontend Agent (Chrome Extension)
- MV3 only — no deprecated APIs
- All messages via chrome.runtime.sendMessage / chrome.tabs.sendMessage
- Content script: minimal DOM manipulation, data-apk-* attributes for state
- Background: service worker, no persistent state (use chrome.storage)
- Popup: vanilla JS, no frameworks, progressive enhancement

### UI Agent (PyWebView Settings + tkinter Overlay)
- **Settings UI:** PyWebView (Edge WebView2) rendering HTML/CSS/JS SPA
  - Source: `src/ui/web/` (HTML/CSS/JS), `src/ui/web_bridge.py` (Python API)
  - Design language: Aqua Voice style (dark theme, gold shimmer accents, rounded corners)
  - Python↔JS communication via `window.pywebview.api` bridge
  - All UI text via i18n — never hardcoded strings
- **Recording overlay:** tkinter (always-on-top transparent pill, no web effects)
  - Source: `src/ui/overlay.py`
- DPI-aware: use relative sizing, test at 100%/125%/150%
- Keyboard navigation: all controls reachable via Tab, actions via Enter/Escape
- Accessibility: ARIA attributes in HTML, proper tab order

## Analysis Pipeline Skills
Subagents MUST run the appropriate analysis skill after completing work:
- After Python code: `/analyze-backend`
- After Extension code: `/analyze-frontend`
- After UI changes: `/analyze-ui`
- After security-sensitive changes: `/analyze-security`
- Before any commit: `/pre-commit-check`

## Windows VM Testing
- VM: 192.168.12.6, user: test_claude, RDP port 3389
- Build: scp to VM → PyInstaller → Inno Setup → /VERYSILENT install
- Test: launch from Start menu (not SSH), check tray icon in RDP session

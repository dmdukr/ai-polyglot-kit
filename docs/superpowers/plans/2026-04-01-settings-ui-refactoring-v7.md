# Settings UI Refactoring v7 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Settings UI from 11400 to ~4640 lines by eliminating duplication and simplifying architecture — zero visual or functional regressions.

**Architecture:** Bootstrap payload (Python injects one JSON for first paint) + declarative form binding (`data-cfg` attributes) + config contract module (`settings_contract.py`). Dev mode uses `url=` with bridge fallback; release mode uses `html=` with inlined assets.

**Tech Stack:** Python 3.12, PyWebView, vanilla JS, PyYAML, pytest

**Spec:** `docs/superpowers/specs/2026-03-31-settings-ui-refactoring-final.md`

---

## File Map

### New files
| File | Responsibility | Lines |
|---|---|---|
| `src/ui/settings_contract.py` | AppConfig ↔ UI payload mapping | ~100 |
| `src/ui/settings_bootstrap.py` | Prepare bootstrap payload + HTML injection | ~70 |
| `src/ui/build_settings.py` | Bundle assets for release | ~60 |
| `src/ui/web/js/i18n.js` | Translation application | ~80 |
| `src/ui/web/js/form-bind.js` | Declarative form ↔ config binding | ~90 |
| `src/ui/web/js/ui-core.js` | Theme, navigation, modals, toasts | ~150 |
| `tests/ui/test_settings_contract.py` | Contract round-trip tests | ~120 |
| `tests/ui/__init__.py` | Package marker | 0 |

### Modified files
| File | Change |
|---|---|
| `src/ui/web/index.html` | Strip inline CSS/JS/i18n, add `<link>`/`<script src>`, add `data-cfg` attrs |
| `src/ui/web/js/app.js` | Sync inline diffs, remove populateForm/collectFormData/helpers, delegate to modules |
| `src/ui/web_bridge.py` | Simplify get_config/save_config, delete _config_to_web/_normalize/_apply_* |
| `src/ui/settings_window.py` | Use bootstrap module, dev/release split, remove regex i18n |
| `groq_dictation.spec` | Remove _settings_main, add new modules |
| `.gitignore` | Add `_bundled.html`, `i18n-data.js` |

### Deleted files
| File | Reason |
|---|---|
| `src/ui/_settings_main.py` | Single entry point via settings_window.py |
| `src/ui/web/js/pages/` | Empty directory |

---

## Task 1: Test infrastructure + contract tests

**Files:**
- Create: `tests/ui/__init__.py`
- Create: `tests/ui/test_settings_contract.py`
- Create: `src/ui/settings_contract.py`

- [ ] **Step 1: Create test package**

```python
# tests/ui/__init__.py
# (empty)
```

- [ ] **Step 2: Write failing tests for config_to_ui**

```python
# tests/ui/test_settings_contract.py
"""Tests for Settings UI config contract."""
from __future__ import annotations

import pytest
from dataclasses import asdict
from src.config import AppConfig


class TestConfigToUi:
    """config_to_ui must return a dict the SPA can consume."""

    def test_returns_dict_with_all_appconfig_keys(self) -> None:
        from src.ui.settings_contract import config_to_ui
        config = AppConfig()
        result = config_to_ui(config)
        base = asdict(config)
        for key in base:
            assert key in result, f"Missing key: {key}"

    def test_top_level_language_shortcut(self) -> None:
        from src.ui.settings_contract import config_to_ui
        config = AppConfig()
        config.ui.language = "en"
        result = config_to_ui(config)
        assert result["language"] == "en"

    def test_top_level_language_default_uk(self) -> None:
        from src.ui.settings_contract import config_to_ui
        config = AppConfig()
        result = config_to_ui(config)
        assert result["language"] == "uk"

    def test_nested_audio_preserved(self) -> None:
        from src.ui.settings_contract import config_to_ui
        config = AppConfig()
        config.audio.vad_aggressiveness = 3
        config.audio.gain = 2.5
        result = config_to_ui(config)
        assert result["audio"]["vad_aggressiveness"] == 3
        assert result["audio"]["gain"] == 2.5

    def test_nested_providers_preserved(self) -> None:
        from src.ui.settings_contract import config_to_ui
        config = AppConfig()
        config.providers.stt[0] = {
            "api_key": "gsk_test", "provider": "Groq",
            "base_url": "https://api.groq.com/openai/v1", "model": "whisper-large-v3-turbo",
        }
        result = config_to_ui(config)
        assert result["providers"]["stt"][0]["api_key"] == "gsk_test"

    def test_nested_ui_preserved(self) -> None:
        from src.ui.settings_contract import config_to_ui
        config = AppConfig()
        config.ui.sound_on_start = False
        result = config_to_ui(config)
        assert result["ui"]["sound_on_start"] is False

    def test_telemetry_nested(self) -> None:
        from src.ui.settings_contract import config_to_ui
        config = AppConfig()
        config.telemetry.enabled = False
        result = config_to_ui(config)
        assert result["telemetry"]["enabled"] is False

    def test_text_injection_nested(self) -> None:
        from src.ui.settings_contract import config_to_ui
        config = AppConfig()
        config.text_injection.method = "clipboard"
        result = config_to_ui(config)
        assert result["text_injection"]["method"] == "clipboard"


class TestUiToConfig:
    """ui_to_config must apply SPA payload back onto AppConfig."""

    def test_language_shortcut_applied(self) -> None:
        from src.ui.settings_contract import ui_to_config
        config = AppConfig()
        ui_to_config({"language": "en"}, config)
        assert config.ui.language == "en"

    def test_nested_audio_applied(self) -> None:
        from src.ui.settings_contract import ui_to_config
        config = AppConfig()
        ui_to_config({"audio": {"vad_aggressiveness": 3, "gain": 1.5}}, config)
        assert config.audio.vad_aggressiveness == 3
        assert config.audio.gain == 1.5

    def test_nested_ui_applied(self) -> None:
        from src.ui.settings_contract import ui_to_config
        config = AppConfig()
        ui_to_config({"ui": {"sound_on_start": False, "show_notifications": False}}, config)
        assert config.ui.sound_on_start is False
        assert config.ui.show_notifications is False

    def test_hotkey_applied(self) -> None:
        from src.ui.settings_contract import ui_to_config
        config = AppConfig()
        ui_to_config({"hotkey": "ctrl+shift+r", "hotkey_mode": "toggle"}, config)
        assert config.hotkey == "ctrl+shift+r"
        assert config.hotkey_mode == "toggle"

    def test_text_injection_applied(self) -> None:
        from src.ui.settings_contract import ui_to_config
        config = AppConfig()
        ui_to_config({"text_injection": {"method": "clipboard"}}, config)
        assert config.text_injection.method == "clipboard"

    def test_telemetry_applied(self) -> None:
        from src.ui.settings_contract import ui_to_config
        config = AppConfig()
        ui_to_config({"telemetry": {"enabled": False}}, config)
        assert config.telemetry.enabled is False

    def test_provider_stt_key_migrated_to_groq(self) -> None:
        from src.ui.settings_contract import ui_to_config
        config = AppConfig()
        ui_to_config({
            "providers": {
                "stt": [{"api_key": "gsk_abc", "provider": "Groq", "base_url": "", "model": ""}],
            }
        }, config)
        assert config.groq.api_key == "gsk_abc"

    def test_partial_update_preserves_untouched(self) -> None:
        from src.ui.settings_contract import ui_to_config
        config = AppConfig()
        config.ui.sound_on_start = True
        config.ui.language = "uk"
        ui_to_config({"language": "en"}, config)
        assert config.ui.language == "en"
        assert config.ui.sound_on_start is True  # untouched


class TestRoundTrip:
    """config_to_ui → ui_to_config must preserve all values."""

    def test_full_round_trip(self) -> None:
        from src.ui.settings_contract import config_to_ui, ui_to_config
        original = AppConfig()
        original.ui.language = "en"
        original.hotkey = "ctrl+alt+d"
        original.audio.vad_aggressiveness = 2
        original.audio.gain = 1.5
        original.telemetry.enabled = False
        original.text_injection.method = "clipboard"
        original.normalization.enabled = False

        # Round-trip
        ui_data = config_to_ui(original)
        restored = AppConfig()
        ui_to_config(ui_data, restored)

        assert restored.ui.language == "en"
        assert restored.hotkey == "ctrl+alt+d"
        assert restored.audio.vad_aggressiveness == 2
        assert restored.audio.gain == 1.5
        assert restored.telemetry.enabled is False
        assert restored.text_injection.method == "clipboard"
        assert restored.normalization.enabled is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/ui/test_settings_contract.py -v --no-header 2>&1 | tail -5`
Expected: `ModuleNotFoundError: No module named 'src.ui.settings_contract'`

- [ ] **Step 4: Write settings_contract.py**

```python
# src/ui/settings_contract.py
"""AppConfig <-> Settings UI payload contract.

Single place where config shape is adapted for the Settings SPA.
All other modules pass through - no hidden reshaping.
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.config import AppConfig


def config_to_ui(config: AppConfig) -> dict[str, Any]:
    """Convert AppConfig to the dict the Settings SPA expects."""
    data = asdict(config)
    data["language"] = data.get("ui", {}).get("language", "uk")
    data["autostart"] = _get_autostart()
    return data


def ui_to_config(data: dict[str, Any], config: AppConfig) -> None:
    """Apply Settings SPA payload back onto a live AppConfig."""
    # Resolve top-level shortcuts
    if "language" in data:
        data.setdefault("ui", {})["language"] = data.pop("language")

    if "autostart" in data:
        _set_autostart(bool(data.pop("autostart")))

    # Apply nested data
    config._apply_dict(data)

    # Provider backward-compat: copy first STT key to groq.api_key
    providers = data.get("providers", {})
    if isinstance(providers, dict):
        stt_slots = providers.get("stt", [])
        if stt_slots and isinstance(stt_slots, list) and stt_slots[0].get("api_key"):
            config.groq.api_key = stt_slots[0]["api_key"]


def _get_autostart() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg  # noqa: PLC0415
        from src.config import APP_NAME  # noqa: PLC0415
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except Exception:
        return False


def _set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg  # noqa: PLC0415
        from src.config import APP_NAME  # noqa: PLC0415
        reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, reg_key, 0, winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m src.main'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/ui/test_settings_contract.py -v --no-header 2>&1 | tail -25`
Expected: all 18 tests PASS

- [ ] **Step 6: Commit**

```bash
git add tests/ui/__init__.py tests/ui/test_settings_contract.py src/ui/settings_contract.py
git commit -m "feat(v7): add settings_contract.py with full round-trip tests"
```

---

## Task 2: Bootstrap module

**Files:**
- Create: `src/ui/settings_bootstrap.py`

- [ ] **Step 1: Write settings_bootstrap.py**

```python
# src/ui/settings_bootstrap.py
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
```

- [ ] **Step 2: Verify import works**

Run: `python3 -c "import sys; sys.path.insert(0,'.'); from src.ui.settings_bootstrap import build_payload; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ui/settings_bootstrap.py
git commit -m "feat(v7): add settings_bootstrap.py"
```

---

## Task 3: Deduplicate index.html

This is the biggest single change. Strip inline CSS (~2800 lines), inline JS (~3300 lines), and inline i18n (~75KB) from `index.html`. Replace with external references.

**Files:**
- Modify: `src/ui/web/index.html`
- Modify: `src/ui/web/js/app.js` (sync 3 diverged diffs from inline copy)

- [ ] **Step 1: Sync inline JS diffs into standalone app.js**

The inline copy has 3 changes not in standalone app.js:

1. `earlyLang()` reads `data-initial-lang` first (inline is newer)
2. Error toast replaced with `console.warn` on config load failure
3. `getHotkeyValue` / `bindIfExists` missing from inline — present in standalone (keep them)

Apply diff 1 (earlyLang) into `src/ui/web/js/app.js` lines 14-20:

Replace:
```javascript
    var lang = null;
    try {
      var match = window.location.href.match(/[?&]lang=([a-z]{2})/);
      lang = match ? match[1] : null;
    } catch(e) {}
```
With:
```javascript
    var lang = null;
    try {
      lang = document.documentElement.getAttribute('data-initial-lang');
      if (!lang) {
        var match = window.location.href.match(/[?&]lang=([a-z]{2})/);
        lang = match ? match[1] : null;
      }
      if (!lang) {
        lang = document.documentElement.lang;
      }
    } catch(e) {}
```

Apply diff 2: In `loadConfig()` (~line 460), replace:
```javascript
      showToast('Failed to load settings', 'error');
```
With:
```javascript
      console.warn('[config] Settings load error (non-critical):', e.message);
```

- [ ] **Step 2: Strip index.html to markup-only**

Remove from `index.html`:
1. Lines 7-2800: entire `<style>...</style>` block + `</head><body>` preamble → replace with `<link>` + proper `</head><body>`
2. Line ~2801: `<script>var _EMBEDDED_I18N = {...};</script>` → delete
3. Lines ~2805-6120: `<script>` inline copy of app.js → replace with `<script src>` references

The resulting `</head>` section becomes:
```html
<link rel="stylesheet" href="css/styles.css">
</head>
<body>
```

The resulting end of `</body>` becomes:
```html
  <script src="js/i18n-data.js"></script>
  <script src="js/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Verify file sizes**

Run: `wc -l src/ui/web/index.html src/ui/web/js/app.js`
Expected: index.html ~2150 lines, app.js ~3315 lines (slightly larger with synced diffs)

- [ ] **Step 4: Commit**

```bash
git add src/ui/web/index.html src/ui/web/js/app.js
git commit -m "refactor(v7): deduplicate index.html — strip inline CSS/JS/i18n"
```

---

## Task 4: Create i18n.js module

**Files:**
- Create: `src/ui/web/js/i18n.js`
- Modify: `src/ui/web/js/app.js` — remove i18n functions, delegate to I18n

- [ ] **Step 1: Write i18n.js**

```javascript
// i18n.js — single i18n module for Settings SPA
var I18n = {
  lang: 'uk',
  data: {},

  /**
   * Initialize i18n from bootstrap payload or embedded data.
   * @param {Object|null} bootstrap - Bootstrap payload from Python
   */
  init: function(bootstrap) {
    this.lang = (bootstrap && bootstrap.lang) || 'uk';

    if (bootstrap && bootstrap.translations) {
      this.data = bootstrap.translations;
    } else if (typeof _EMBEDDED_I18N !== 'undefined') {
      this.data = _EMBEDDED_I18N;
    }

    this.apply(this.lang);
  },

  /**
   * Apply translations for the given language.
   * @param {string} lang - 'en' or 'uk'
   */
  apply: function(lang) {
    this.lang = lang;
    var tr = this.data[lang] || {};

    document.querySelectorAll('[data-i18n]').forEach(function(el) {
      var key = el.getAttribute('data-i18n');
      if (tr[key]) el.textContent = tr[key];
    });

    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
      var key = el.getAttribute('data-i18n-placeholder');
      if (tr[key]) el.placeholder = tr[key];
    });

    document.documentElement.lang = lang;
  },

  /**
   * Switch language and notify backend.
   * @param {string} lang
   */
  setLang: function(lang) {
    this.apply(lang);
    if (window.pywebview && window.pywebview.api && window.pywebview.api.set_language) {
      window.pywebview.api.set_language(lang);
    }
  },

  /**
   * Get translated text by key.
   * @param {string} key
   * @returns {string}
   */
  t: function(key) {
    var tr = this.data[this.lang] || {};
    return tr[key] || key;
  }
};
```

- [ ] **Step 2: Update index.html script order**

Ensure `<script src>` order is:
```html
  <script src="js/i18n-data.js"></script>
  <script src="js/i18n.js"></script>
  <script src="js/app.js"></script>
```

- [ ] **Step 3: Remove i18n functions from app.js**

Delete from app.js:
- `earlyLang()` IIFE (lines ~14-34)
- `var translations = {};` (line ~283)
- `function setupI18n()` — replace body with:
  ```javascript
  function setupI18n() {
    var langSelect = document.getElementById('lang-select');
    if (langSelect) {
      langSelect.addEventListener('change', function() {
        I18n.setLang(this.value);
        refreshSliderLabels();
      });
    }
  }
  ```
- `var i18nData = null;` + `function _loadEmbeddedI18n()` + `async function loadTranslations(lang)` — delete
- `function walkAndTranslate(lang)` — delete
- `async function setLang(lang)` — replace with:
  ```javascript
  async function setLang(lang) {
    I18n.setLang(lang);
    refreshSliderLabels();
  }
  ```
- `var origTexts = new Map();` — delete

Keep: `SLIDER_UK` map, `sliderLabel()`, `refreshSliderLabels()` — these are controller logic.

- [ ] **Step 4: Update init() to use I18n**

In `init()`, replace `setupI18n()` call order:
```javascript
  async function init(bootstrap) {
    if (window.pywebview && window.pywebview.api) {
      bridgeReady = true;
      api = window.pywebview.api;
    }

    I18n.init(bootstrap);
    // ... rest of setup calls ...
```

- [ ] **Step 5: Commit**

```bash
git add src/ui/web/js/i18n.js src/ui/web/js/app.js src/ui/web/index.html
git commit -m "refactor(v7): extract i18n.js module, remove inline i18n from app.js"
```

---

## Task 5: Create form-bind.js + add data-cfg attributes

**Files:**
- Create: `src/ui/web/js/form-bind.js`
- Modify: `src/ui/web/index.html` — add `data-cfg` attributes
- Modify: `src/ui/web/js/app.js` — replace populateForm/collectFormData/helpers

- [ ] **Step 1: Write form-bind.js**

```javascript
// form-bind.js — Declarative form <-> config binding
// Elements with [data-cfg] are automatically bound to config paths.
var FormBind = {
  /**
   * Populate all [data-cfg] elements from a config object.
   * @param {Object} config - nested config from backend
   */
  populate: function(config) {
    document.querySelectorAll('[data-cfg]').forEach(function(el) {
      var path = el.getAttribute('data-cfg');
      var value = FormBind._resolve(config, path);
      if (value === undefined) return;
      FormBind._setValue(el, value);
    });
  },

  /**
   * Collect all [data-cfg] elements into a nested config object.
   * @returns {Object}
   */
  collect: function() {
    var config = {};
    document.querySelectorAll('[data-cfg]').forEach(function(el) {
      var path = el.getAttribute('data-cfg');
      var value = FormBind._getValue(el);
      FormBind._assign(config, path, value);
    });
    return config;
  },

  _resolve: function(obj, path) {
    return path.split('.').reduce(function(cur, key) {
      return (cur == null) ? undefined : cur[key];
    }, obj);
  },

  _assign: function(obj, path, value) {
    var parts = path.split('.');
    var target = parts.slice(0, -1).reduce(function(cur, key) {
      if (!cur[key]) cur[key] = {};
      return cur[key];
    }, obj);
    target[parts[parts.length - 1]] = value;
  },

  _getValue: function(el) {
    if (el.type === 'checkbox') return el.checked;
    if (el.type === 'range') {
      var divisor = parseFloat(el.getAttribute('data-divisor')) || 1;
      return parseFloat(el.value) / divisor;
    }
    if (el.type === 'number') return parseInt(el.value, 10) || 0;
    return el.value;
  },

  _setValue: function(el, value) {
    if (value === undefined || value === null) return;
    if (el.type === 'checkbox') {
      el.checked = !!value;
    } else if (el.type === 'range') {
      var divisor = parseFloat(el.getAttribute('data-divisor')) || 1;
      el.value = value * divisor;
      el.dispatchEvent(new Event('input'));
    } else {
      el.value = value;
    }
  }
};
```

- [ ] **Step 2: Add data-cfg attributes to HTML elements**

Map of HTML element IDs to `data-cfg` paths (only for fields that exist in AppConfig):

```
General page:
  #lang-select               → data-cfg="language"
  #toggle-telemetry input    → data-cfg="telemetry.enabled"
  #toggle-sound-feedback     → data-cfg="ui.sound_on_start"
  #toggle-show-overlay       → data-cfg="ui.show_notifications"

Audio page:
  #mic-select                → data-cfg="audio.mic_device_index"
  #rms-slider                → data-cfg="audio.gain"
  #vad-select                → data-cfg="audio.vad_aggressiveness"

Dictation page:
  #injection-method-select   → data-cfg="text_injection.method"
  #toggle-rnnoise            → (aspirational — no data-cfg)
  #toggle-agc                → (aspirational — no data-cfg)

LLM/Normalization page:
  #toggle-llm-enable         → data-cfg="normalization.enabled"
  #temp-slider               → data-cfg="normalization.temperature" data-divisor="100"
```

For each element, add `data-cfg="path"` attribute. Example transformations:

```html
<!-- Before -->
<select id="lang-select">
<!-- After -->
<select id="lang-select" data-cfg="language">

<!-- Before -->
<label class="toggle"><input type="checkbox" id="toggle-telemetry">
<!-- After -->
<label class="toggle"><input type="checkbox" id="toggle-telemetry" data-cfg="telemetry.enabled">

<!-- Before -->
<input type="range" min="0" max="100" value="30" id="temp-slider">
<!-- After -->
<input type="range" min="0" max="100" value="30" id="temp-slider" data-cfg="normalization.temperature" data-divisor="100">
```

Elements with NO matching AppConfig field (aspirational) get class `disabled-field` added to their parent `.card-row` and NO `data-cfg` attribute.

- [ ] **Step 3: Update index.html script order**

```html
  <script src="js/i18n-data.js"></script>
  <script src="js/i18n.js"></script>
  <script src="js/form-bind.js"></script>
  <script src="js/app.js"></script>
```

- [ ] **Step 4: Replace populateForm in app.js**

Replace the entire `populateForm()` function with:
```javascript
  async function populateForm(config) {
    // Declarative binding handles all data-cfg elements
    FormBind.populate(config);

    // Theme (external, not in AppConfig)
    var theme = config.theme || 'dark';
    setTheme(theme);

    // Language (triggers i18n)
    if (config.language) {
      I18n.setLang(config.language);
      var langSelect = document.getElementById('lang-select');
      if (langSelect) langSelect.value = config.language;
    }

    // Hotkeys (custom capture UI)
    if (config.hotkeys) {
      setHotkeyDisplay('hotkey-record', config.hotkeys.record);
      setHotkeyDisplay('hotkey-feedback', config.hotkeys.feedback);
      setHotkeyDisplay('hotkey-cancel', config.hotkeys.cancel);
      setHotkeyDisplay('hotkey-paste-last', config.hotkeys.paste_last);
      setHotkeyDisplay('hotkey-translate', config.hotkeys.translate);
    } else if (config.hotkey) {
      setHotkeyDisplay('hotkey-record', config.hotkey);
    }

    // Provider cards (dynamic structure)
    populateProviderCards(config);

    refreshSliderLabels();
  }
```

- [ ] **Step 5: Replace collectFormData in app.js**

Replace the entire `collectFormData()` function with:
```javascript
  function collectFormData() {
    // Declarative binding collects all data-cfg elements
    var config = FormBind.collect();

    // Theme (external)
    config.theme = currentTheme;

    // Language
    config.language = I18n.lang;

    // Hotkeys (custom capture UI)
    config.hotkeys = {
      record: getHotkeyValue('hotkey-record'),
      feedback: getHotkeyValue('hotkey-feedback'),
      cancel: getHotkeyValue('hotkey-cancel'),
      paste_last: getHotkeyValue('hotkey-paste-last'),
      translate: getHotkeyValue('hotkey-translate')
    };
    config.hotkey = config.hotkeys.record;

    // Provider cards (dynamic structure)
    if (!config.providers) config.providers = {};
    config.providers.stt = collectProviderCards('stt-provider');
    config.providers.llm = collectProviderCards('llm-provider');
    config.providers.translation = collectProviderCards('translate-provider');

    return config;
  }
```

- [ ] **Step 6: Delete unused helper functions from app.js**

Delete these functions (no longer called):
- `setSelectValue`, `setSelectByText`, `getSelectValue`
- `setInputValue`, `getInputValue`, `getInputInt`
- `setBoolToggle`, `getBoolToggle`
- `setSliderValue`, `getSliderInt`, `getSliderFloat`
- `setTextContent`

Keep: `setHotkeyDisplay`, `getHotkeyValue`, `bindIfExists`, `showToast`

- [ ] **Step 7: Commit**

```bash
git add src/ui/web/js/form-bind.js src/ui/web/index.html src/ui/web/js/app.js
git commit -m "refactor(v7): declarative form binding with data-cfg attributes"
```

---

## Task 6: Extract ui-core.js

**Files:**
- Create: `src/ui/web/js/ui-core.js`
- Modify: `src/ui/web/js/app.js` — remove theme/nav/modal/toast functions

- [ ] **Step 1: Write ui-core.js**

Extract from app.js: `setupTheme`, `setTheme`, `setupNavigation`, `setupModals`, `showToast`, `refreshSliderLabels`, `SLIDER_UK`, `sliderLabel`, and the `dynamicStyle` variable.

```javascript
// ui-core.js — Theme, navigation, modals, toasts, slider labels
var UiCore = {
  theme: 'dark',
  dynamicStyle: null,

  init: function(bootstrap) {
    this.dynamicStyle = document.createElement('style');
    document.head.appendChild(this.dynamicStyle);
    var theme = (bootstrap && bootstrap.theme) || 'dark';
    this.setTheme(theme);
    this._setupNavigation();
    this._setupModals();
  },

  setTheme: function(theme) {
    if (theme !== 'dark' && theme !== 'light') theme = 'dark';
    this.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    document.body.style.background = theme === 'light' ? '#ddd8ce' : '#16161e';
    var track = theme === 'light' ? '#d4cec4' : '#333348';
    var thumb = theme === 'light' ? '#a07010' : '#c49520';
    if (this.dynamicStyle) {
      this.dynamicStyle.textContent =
        'input[type="range"]::-webkit-slider-runnable-track{background:' + track + '!important}' +
        'input[type="range"]::-webkit-slider-thumb{background:' + thumb + '!important}';
    }
    if (window.pywebview && window.pywebview.api && window.pywebview.api.window_set_theme) {
      window.pywebview.api.window_set_theme(theme);
    }
    try { localStorage.setItem('apk_theme', theme); } catch(e) {}
  },

  toast: function(message, type) {
    // Reuse existing showToast logic
    var container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.style.cssText = 'position:fixed;top:16px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:8px;';
      document.body.appendChild(container);
    }
    var toast = document.createElement('div');
    toast.className = 'toast toast-' + (type || 'info');
    toast.textContent = message;
    toast.style.cssText = 'padding:10px 20px;border-radius:6px;color:#fff;font-size:13px;opacity:0;transition:opacity 0.3s;cursor:pointer;' +
      (type === 'error' ? 'background:#d47878;' : type === 'success' ? 'background:#7ec89b;color:#1e1e2e;' : 'background:#333348;');
    container.appendChild(toast);
    requestAnimationFrame(function() { toast.style.opacity = '1'; });
    toast.addEventListener('click', function() { toast.remove(); });
    setTimeout(function() {
      toast.style.opacity = '0';
      setTimeout(function() { toast.remove(); }, 300);
    }, 3000);
  },

  _setupNavigation: function() {
    var sidebarItems = document.querySelectorAll('.sidebar-item');
    var contentPages = document.querySelectorAll('.content');
    sidebarItems.forEach(function(item) {
      item.addEventListener('click', function() {
        var targetPage = item.dataset.page;
        if (!targetPage) return;
        sidebarItems.forEach(function(i) { i.classList.remove('active'); });
        item.classList.add('active');
        contentPages.forEach(function(c) { c.classList.remove('active'); });
        var page = document.getElementById('page-' + targetPage);
        if (page) page.classList.add('active');
        try { localStorage.setItem('apk_last_page', targetPage); } catch(e) {}
      });
    });
    try {
      var lastPage = localStorage.getItem('apk_last_page');
      if (lastPage) {
        var target = document.querySelector('.sidebar-item[data-page="' + lastPage + '"]');
        if (target) target.click();
      }
    } catch(e) {}
  },

  _setupModals: function() {
    document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
      overlay.addEventListener('click', function(e) {
        if (e.target === overlay) overlay.classList.remove('active');
      });
    });
    document.querySelectorAll('[data-modal-close]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var modal = btn.closest('.modal-overlay');
        if (modal) modal.classList.remove('active');
      });
    });
  }
};

// Slider label translations (kept with UI core)
var SLIDER_UK = {
  'Whisper':'\u0428\u0435\u043f\u0456\u0442','Soft':'\u0422\u0438\u0445\u0438\u0439',
  'Quiet':'\u0422\u0438\u0445\u043e','Clear voice':'\u0427\u0456\u0442\u043a\u0438\u0439 \u0433\u043e\u043b\u043e\u0441',
  'Loud':'\u0413\u0443\u0447\u043d\u0438\u0439','Maximum':'\u041c\u0430\u043a\u0441\u0438\u043c\u0443\u043c',
  'Fastest':'\u041d\u0430\u0439\u0448\u0432\u0438\u0434\u0448\u0435','Fast':'\u0428\u0432\u0438\u0434\u043a\u043e',
  'Good':'\u0414\u043e\u0431\u0440\u0435','High':'\u0412\u0438\u0441\u043e\u043a\u0435',
  'Best':'\u041d\u0430\u0439\u043a\u0440\u0430\u0449\u0435','Minimal':'\u041c\u0456\u043d\u0456\u043c\u0430\u043b\u044c\u043d\u0430',
  'Low':'\u041d\u0438\u0437\u044c\u043a\u0430','Medium':'\u0421\u0435\u0440\u0435\u0434\u043d\u044f',
  'Balanced':'\u0417\u0431\u0430\u043b\u0430\u043d\u0441\u043e\u0432\u0430\u043d\u0435',
  'Very high':'\u0414\u0443\u0436\u0435 \u0432\u0438\u0441\u043e\u043a\u0435',
  'Stable':'\u0421\u0442\u0430\u0431\u0456\u043b\u044c\u043d\u043e',
  'Creative':'\u041a\u0440\u0435\u0430\u0442\u0438\u0432\u043d\u043e'
};

function sliderLabel(key) {
  if (I18n.lang === 'uk' && SLIDER_UK[key]) return SLIDER_UK[key];
  return key;
}

function refreshSliderLabels() {
  var configs = [
    {s:'cpu-slider',v:'cpu-value',l:['Low','Balanced','High','Very high','Maximum']},
    {s:'beam-slider',v:'beam-value',l:['Fastest','Fast','Good','High','Best']},
    {s:'whisper-temp-slider',v:'whisper-temp-value',l:['Minimal','Low','Medium','High','Maximum']},
    {s:'rms-slider',v:'rms-value',l:['Whisper','Soft','Clear voice','Loud','Maximum']}
  ];
  configs.forEach(function(cfg) {
    var slider = document.getElementById(cfg.s);
    var display = document.getElementById(cfg.v);
    if (slider && display) display.textContent = sliderLabel(cfg.l[slider.value]);
  });
}
```

- [ ] **Step 2: Remove extracted functions from app.js**

Delete from app.js: `setupTheme`, `setTheme`, `setupNavigation`, `setupModals`, `showToast`, `var dynamicStyle`, `SLIDER_UK`, `sliderLabel`, `refreshSliderLabels`.

Replace calls:
- `showToast(...)` → `UiCore.toast(...)`
- `setTheme(theme)` → `UiCore.setTheme(theme)`
- `currentTheme` → `UiCore.theme`

Update `init()`:
```javascript
  async function init(bootstrap) {
    if (window.pywebview && window.pywebview.api) {
      bridgeReady = true;
      api = window.pywebview.api;
    }
    I18n.init(bootstrap);
    UiCore.init(bootstrap);
    setupTitlebar();
    setupI18n();
    setupHotkeyCapture();
    setupSliders();
    setupToggles();
    // ... rest of setup calls ...
```

- [ ] **Step 3: Update index.html script order**

```html
  <script src="js/i18n-data.js"></script>
  <script src="js/i18n.js"></script>
  <script src="js/form-bind.js"></script>
  <script src="js/ui-core.js"></script>
  <script src="js/app.js"></script>
```

- [ ] **Step 4: Commit**

```bash
git add src/ui/web/js/ui-core.js src/ui/web/js/app.js src/ui/web/index.html
git commit -m "refactor(v7): extract ui-core.js — theme, nav, modals, toasts"
```

---

## Task 7: Simplify web_bridge.py

**Files:**
- Modify: `src/ui/web_bridge.py`

- [ ] **Step 1: Replace get_config with contract call**

```python
@_safe
def get_config(self) -> dict[str, Any]:
    """Return config as UI payload."""
    from src.ui.settings_contract import config_to_ui  # noqa: PLC0415
    data = config_to_ui(self._config)
    data["theme"] = self._load_theme()
    return data
```

- [ ] **Step 2: Replace save_config with contract call**

```python
@_safe
def save_config(self, data: dict[str, Any]) -> dict[str, Any]:
    """Apply UI payload back to config and persist."""
    from src.ui.settings_contract import ui_to_config  # noqa: PLC0415

    theme = data.pop("theme", None)
    if theme:
        self._save_theme(theme)

    ui_to_config(data, self._config)
    self._write_config()
    self._write_env()

    if self._on_save is not None:
        self._on_save(restart=True)
    return {"success": True}
```

- [ ] **Step 3: Delete unused methods**

Delete: `_config_to_web`, `_normalize_web_config`, `_apply_config`, `_apply_providers`, `_apply_audio`, `_apply_dictation`, `_apply_ui`, `_get_autostart`, `_set_autostart`.

Keep `_load_theme`, `_save_theme` (still used here). Keep `_write_config`, `_write_env`.

- [ ] **Step 4: Run contract tests to verify round-trip still works**

Run: `pytest tests/ui/test_settings_contract.py -v --no-header 2>&1 | tail -5`
Expected: all 18 PASS

- [ ] **Step 5: Commit**

```bash
git add src/ui/web_bridge.py
git commit -m "refactor(v7): simplify web_bridge.py — delegate to settings_contract"
```

---

## Task 8: Refactor settings_window.py

**Files:**
- Modify: `src/ui/settings_window.py`

- [ ] **Step 1: Rewrite _open_webview_window**

Replace the entire `_open_webview_window` function with dev/release split:

```python
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
```

- [ ] **Step 2: Remove dead code**

Delete from settings_window.py:
- All `import json`, `import re`, `import yaml`, `import os` that were only used for regex i18n
- The regex translation block (`if lang != "en": ...`)
- The `html_content.replace('<html lang=...')` block
- The `_clear_cache` function
- The `_on_shown` callback and `set_titlebar_theme` function (move to bridge if needed later)
- The disk-language debug logging

- [ ] **Step 3: Commit**

```bash
git add src/ui/settings_window.py
git commit -m "refactor(v7): simplify settings_window.py — dev/release split, no regex i18n"
```

---

## Task 9: Delete _settings_main.py + build bundler + cleanup

**Files:**
- Delete: `src/ui/_settings_main.py`
- Create: `src/ui/build_settings.py`
- Modify: `groq_dictation.spec`
- Modify: `.gitignore`

- [ ] **Step 1: Delete _settings_main.py**

```bash
git rm src/ui/_settings_main.py
```

- [ ] **Step 2: Write build_settings.py**

```python
# src/ui/build_settings.py
"""Bundle Settings UI for release + generate i18n-data.js.

Outputs (both gitignored):
  1. js/i18n-data.js — generated from i18n.json
  2. _bundled.html   — everything inlined for PyInstaller

Usage: python -m src.ui.build_settings
"""
from __future__ import annotations

import re
from pathlib import Path

WEB_DIR = Path(__file__).parent / "web"


def generate_i18n_data_js() -> None:
    """Generate js/i18n-data.js from i18n.json."""
    i18n = (WEB_DIR / "i18n.json").read_text(encoding="utf-8")
    out = WEB_DIR / "js" / "i18n-data.js"
    out.write_text(f"var _EMBEDDED_I18N = {i18n.strip()};\n", encoding="utf-8")
    print(f"Generated: {out}")


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
    print(f"Bundled: {out} ({len(html):,} bytes)")


def build() -> None:
    generate_i18n_data_js()
    build_bundle()


if __name__ == "__main__":
    build()
```

- [ ] **Step 3: Update .gitignore**

Add:
```
src/ui/web/_bundled.html
src/ui/web/js/i18n-data.js
```

- [ ] **Step 4: Update groq_dictation.spec**

Remove `_settings_main.py` from datas and hiddenimports. Add new modules to hiddenimports:

```python
# Remove from datas:
#   ('src/ui/_settings_main.py', 'src/ui'),

# Remove from hiddenimports:
#   'src.ui._settings_main',

# Add to hiddenimports:
    'src.ui.settings_bootstrap',
    'src.ui.settings_contract',
```

- [ ] **Step 5: Remove empty js/pages/ directory**

```bash
rmdir src/ui/web/js/pages 2>/dev/null || true
```

- [ ] **Step 6: Run build_settings.py to verify it works**

Run: `python3 -m src.ui.build_settings`
Expected: prints "Generated: ..." and "Bundled: ..."

- [ ] **Step 7: Run all tests**

Run: `pytest tests/ -x -q --tb=short 2>&1 | tail -10`
Expected: 220+ tests pass (202 existing + 18 new contract tests)

- [ ] **Step 8: Final line count audit**

Run: `wc -l src/ui/web/index.html src/ui/web/js/app.js src/ui/web/js/i18n.js src/ui/web/js/form-bind.js src/ui/web/js/ui-core.js src/ui/web/css/styles.css src/ui/web_bridge.py src/ui/settings_window.py src/ui/settings_bootstrap.py src/ui/settings_contract.py src/ui/build_settings.py`
Expected: total under 5000 lines

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(v7): build bundler, delete _settings_main.py, cleanup"
```

---

## Task 10: Version bump + final commit

**Files:**
- Modify: `src/config.py` line 14

- [ ] **Step 1: Bump version**

Change `APP_VERSION = "6.1.40"` to `APP_VERSION = "7.0.0"` in `src/config.py:14`.

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: all tests pass

- [ ] **Step 3: Run ruff + mypy on changed Python files**

Run: `ruff check src/ui/settings_contract.py src/ui/settings_bootstrap.py src/ui/build_settings.py src/ui/web_bridge.py src/ui/settings_window.py`
Run: `ruff format --check src/ui/settings_contract.py src/ui/settings_bootstrap.py src/ui/build_settings.py`

- [ ] **Step 4: Commit**

```bash
git add src/config.py
git commit -m "release: v7.0.0 — Settings UI refactoring complete"
```

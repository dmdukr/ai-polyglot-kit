# Browser Page Translation Extension — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full-page inline translation to Chromium browsers via a browser extension communicating with AI Polyglot Kit desktop app through a local REST API.

**Architecture:** New HTTP server in desktop app (`127.0.0.1:19378`) serves translation API + extension files. Browser extension (Manifest V3) translates visible page blocks via viewport-based batching. Extension auto-installed via HKCU registry policy.

**Tech Stack:** Python stdlib `http.server` (server), plain JS (extension), `secrets` (auth), `winreg` (browser install)

**Spec:** `docs/superpowers/specs/2026-03-23-browser-extension-design.md`

---

## File Map

### New Files (Python)

| File | Responsibility |
|------|---------------|
| `src/translate_engine.py` | Shared translation logic: DeepL → LLM fallback (extracted from translate_overlay.py) |
| `src/translate_server.py` | HTTP server on 127.0.0.1:19378 — /health, /translate, /token, /extension/* |
| `src/browser_installer.py` | Browser detection, CRX packing, HKCU registry install/uninstall |

### New Files (Extension)

| File | Responsibility |
|------|---------------|
| `extension/manifest.json` | Manifest V3 config |
| `extension/background.js` | Service worker: token management, batching, API calls |
| `extension/content.js` | DOM walker, viewport observer, inline replacement, hover tooltip |
| `extension/popup.html` | Popup markup |
| `extension/popup.js` | Popup logic: language selector, translate button, status |
| `extension/popup.css` | Popup styles |

### Modified Files

| File | Change |
|------|--------|
| `src/translate_overlay.py` | Replace internal translation methods with calls to `translate_engine.py` |
| `src/tray_app.py` | Start translate server in `_setup()` |
| `src/settings_ui.py` | Add browser extensions section to Interface tab |
| `src/config.py` | Version 5.0.0, add `server_port` field |
| `installer.iss` | Version bump, include `extension/` directory |

---

## Task 1: Extract TranslateEngine

Extract translation logic from `translate_overlay.py` into a standalone module that both the overlay and HTTP server can use.

**Files:**
- Create: `src/translate_engine.py`
- Modify: `src/translate_overlay.py`

- [ ] **Step 1: Create `src/translate_engine.py`**

```python
"""Shared translation engine — DeepL with key rotation → LLM fallback.

Used by both TranslateOverlay (desktop) and TranslateServer (browser extension).
"""

import logging

import httpx

from .provider_manager import ProviderManager
from .utils import load_deepl_keys

logger = logging.getLogger(__name__)

TRANSLATE_PROMPT = (
    "You are a professional translator. Translate the following text to {language}. "
    "Return ONLY the translated text, no explanations, no notes. "
    "Preserve formatting, line breaks, and punctuation style."
)

LANGUAGES = [
    ("English", "en"), ("Українська", "uk"), ("Русский", "ru"),
    ("Deutsch", "de"), ("Français", "fr"), ("Español", "es"),
    ("Polski", "pl"), ("Italiano", "it"), ("Português", "pt"),
    ("日本語", "ja"), ("中文", "zh"), ("한국어", "ko"),
    ("Türkçe", "tr"), ("العربية", "ar"),
]

DEEPL_LANG_MAP = {"EN": "EN-US", "PT": "PT-BR", "ZH": "ZH-HANS"}


class TranslateEngine:
    """Stateless translation engine with DeepL → LLM fallback."""

    def __init__(self, provider_manager: ProviderManager | None = None,
                 groq_config=None):
        self._pm = provider_manager
        self._groq = groq_config
        self._deepl_rotation_idx = 0

    def translate(self, text: str, target_lang: str,
                  source_lang: str = "auto") -> tuple[str, str]:
        """Translate a single text. Returns (translated, engine_name)."""
        lang_code = target_lang
        # If target_lang is a language name, resolve to code
        for name, code in LANGUAGES:
            if name == target_lang:
                lang_code = code
                break

        # 1. Try DeepL with key rotation
        keys = load_deepl_keys()
        if keys:
            for _ in range(len(keys)):
                key = self._next_deepl_key(keys)
                try:
                    result = self._deepl(text, lang_code, key)
                    key_num = (self._deepl_rotation_idx - 1) % len(keys) + 1
                    logger.info("DeepL OK (key #%d)", key_num)
                    return result, f"DeepL #{key_num}"
                except ValueError as e:
                    if "quota exceeded" in str(e).lower():
                        logger.warning("DeepL key quota exceeded, trying next")
                        continue
                    raise
                except Exception as e:
                    logger.warning("DeepL failed: %s", e)
                    continue
            logger.warning("All DeepL keys exhausted, falling back to LLM")

        # 2. LLM via ProviderManager
        if self._pm:
            llm = self._pm.get_translation_llm()
            if llm:
                try:
                    lang_name = self._code_to_name(lang_code)
                    result = llm.chat([
                        {"role": "system", "content": TRANSLATE_PROMPT.format(language=lang_name)},
                        {"role": "user", "content": text},
                    ], temperature=0.3)
                    return result, "LLM"
                except Exception as e:
                    logger.warning("Translation LLM failed: %s", e)

        # 3. Legacy groq fallback
        if self._groq and self._groq.api_key:
            result = self._groq_llm(text, lang_code)
            return result, "Groq LLM"

        raise ValueError("No translation providers configured")

    def translate_batch(self, texts: list[str], target_lang: str,
                        source_lang: str = "auto") -> tuple[list[str], str]:
        """Translate a batch of texts. Returns (translations[], engine_name).

        DeepL supports batch natively. LLM falls back to one-by-one.
        """
        if not texts:
            return [], ""

        lang_code = target_lang
        for name, code in LANGUAGES:
            if name == target_lang:
                lang_code = code
                break

        # Try DeepL batch
        keys = load_deepl_keys()
        if keys:
            for _ in range(len(keys)):
                key = self._next_deepl_key(keys)
                try:
                    results = self._deepl_batch(texts, lang_code, key)
                    key_num = (self._deepl_rotation_idx - 1) % len(keys) + 1
                    logger.info("DeepL batch OK (key #%d, %d texts)", key_num, len(texts))
                    return results, f"DeepL #{key_num}"
                except ValueError as e:
                    if "quota exceeded" in str(e).lower():
                        continue
                    raise
                except Exception as e:
                    logger.warning("DeepL batch failed: %s", e)
                    continue

        # LLM: translate one by one
        results = []
        engine = "LLM"
        for text in texts:
            try:
                translated, engine = self.translate(text, lang_code, source_lang)
                results.append(translated)
            except Exception:
                results.append(text)  # keep original on failure
        return results, engine

    def _next_deepl_key(self, keys: list[str]) -> str:
        idx = self._deepl_rotation_idx % len(keys)
        self._deepl_rotation_idx += 1
        return keys[idx]

    def _deepl(self, text: str, target_lang: str, api_key: str) -> str:
        base_url = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
        deepl_lang = DEEPL_LANG_MAP.get(target_lang.upper(), target_lang.upper())
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{base_url}/v2/translate",
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                data={"text": text, "target_lang": deepl_lang},
            )
            if resp.status_code == 456:
                raise ValueError("DeepL quota exceeded for this key")
            resp.raise_for_status()
            translations = resp.json().get("translations", [])
            if translations:
                return translations[0].get("text", "")
            raise ValueError("No translations in DeepL response")

    def _deepl_batch(self, texts: list[str], target_lang: str, api_key: str) -> list[str]:
        base_url = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
        deepl_lang = DEEPL_LANG_MAP.get(target_lang.upper(), target_lang.upper())
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{base_url}/v2/translate",
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                data=[("text", t) for t in texts] + [("target_lang", deepl_lang)],
            )
            if resp.status_code == 456:
                raise ValueError("DeepL quota exceeded for this key")
            resp.raise_for_status()
            translations = resp.json().get("translations", [])
            return [t.get("text", "") for t in translations]

    def _groq_llm(self, text: str, lang_code: str) -> str:
        lang_name = self._code_to_name(lang_code)
        with httpx.Client(
            base_url="https://api.groq.com/openai/v1",
            headers={"Authorization": f"Bearer {self._groq.api_key}"},
            timeout=30.0,
        ) as client:
            resp = client.post(
                "/chat/completions",
                json={
                    "model": self._groq.llm_model,
                    "messages": [
                        {"role": "system", "content": TRANSLATE_PROMPT.format(language=lang_name)},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4000,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _code_to_name(code: str) -> str:
        for name, c in LANGUAGES:
            if c == code:
                return name
        return code
```

- [ ] **Step 2: Refactor `translate_overlay.py` to use `TranslateEngine`**

Replace `_translate`, `_translate_deepl`, `_translate_groq`, `_next_deepl_key` methods with a single `TranslateEngine` instance. In `__init__`, create `self._engine = TranslateEngine(provider_manager, groq_config)`. In `_translate`, call `self._engine.translate(text, target_language)`.

- [ ] **Step 3: Verify overlay still works**

Run the app locally: `C:/tmp/dist/AIPolyglotKit/AIPolyglotKit.exe`. Test 2×Ctrl+C translate — should work as before.

- [ ] **Step 4: Commit**

```bash
git add src/translate_engine.py src/translate_overlay.py
git commit -m "refactor: extract TranslateEngine from translate_overlay"
```

---

## Task 2: HTTP Translation Server

**Files:**
- Create: `src/translate_server.py`
- Modify: `src/tray_app.py`
- Modify: `src/config.py`

- [ ] **Step 1: Create `src/translate_server.py`**

```python
"""Local HTTP server for browser extension translation API.

Binds to 127.0.0.1:19378. Endpoints:
  GET  /health              — status check (no auth)
  GET  /token               — one-time auth token (no auth)
  POST /translate            — batch translate (auth required)
  GET  /extension/update.xml — Chrome update manifest (no auth)
  GET  /extension/apk.crx   — signed extension package (no auth)
"""

import json
import logging
import secrets
import threading
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from .config import APP_VERSION, APP_DIR

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 50


class TranslateServer:
    """Manages the HTTP server lifecycle."""

    def __init__(self, translate_engine, port: int = 19378):
        self._engine = translate_engine
        self._port = port
        self._token: str = secrets.token_hex(32)
        self._token_issued: bool = False
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        handler = partial(_Handler, self)
        self._server = HTTPServer(("127.0.0.1", self._port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="TranslateServer",
            daemon=True,
        )
        self._thread.start()
        logger.info("Translate server started on 127.0.0.1:%d", self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            logger.info("Translate server stopped")


class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler."""

    def __init__(self, server_ctx: TranslateServer, *args, **kwargs):
        self._ctx = server_ctx
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        logger.debug("HTTP %s", format % args)

    # ── CORS ──

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    # ── Helpers ──

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {self._ctx._token}":
            self._json_response(401, {"error": "unauthorized"})
            return False
        return True

    # ── Routes ──

    def do_GET(self):
        if self.path == "/health":
            self._json_response(200, {"status": "ok", "version": APP_VERSION})

        elif self.path == "/token":
            if self._ctx._token_issued:
                self._json_response(403, {"error": "token_already_issued"})
            else:
                self._ctx._token_issued = True
                self._json_response(200, {"token": self._ctx._token})

        elif self.path == "/extension/update.xml":
            self._serve_update_xml()

        elif self.path == "/extension/apk.crx":
            self._serve_crx()

        else:
            self._json_response(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/translate":
            if not self._check_auth():
                return
            self._handle_translate()
        else:
            self._json_response(404, {"error": "not_found"})

    def _handle_translate(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            self._json_response(400, {"error": "invalid_json"})
            return

        texts = body.get("texts", [])
        target_lang = body.get("target_lang", "en")
        source_lang = body.get("source_lang", "auto")

        if not texts:
            self._json_response(400, {"error": "empty_texts"})
            return
        if len(texts) > MAX_BATCH_SIZE:
            self._json_response(400, {"error": f"max_batch_size={MAX_BATCH_SIZE}"})
            return

        try:
            translations, engine = self._ctx._engine.translate_batch(
                texts, target_lang, source_lang
            )
            self._json_response(200, {
                "translations": translations,
                "engine": engine,
            })
        except ValueError as e:
            self._json_response(503, {"error": "no_providers", "detail": str(e)})
        except Exception as e:
            logger.error("Translate error: %s", e, exc_info=True)
            self._json_response(500, {"error": str(e)})

    def _serve_update_xml(self):
        # Will be implemented in Task 5 (browser_installer)
        self._json_response(501, {"error": "not_implemented"})

    def _serve_crx(self):
        crx_path = APP_DIR / "extension" / "apk.crx"
        if not crx_path.exists():
            self._json_response(404, {"error": "crx_not_found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-chrome-extension")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(crx_path.read_bytes())
```

- [ ] **Step 2: Add `server_port` to config**

In `src/config.py`, add `server_port: int = 19378` to the main config dataclass. Bump `APP_VERSION = "5.0.0"`.

- [ ] **Step 3: Wire server into tray_app.py**

In `src/tray_app.py` `_setup()` method, after engine creation:

```python
from .translate_engine import TranslateEngine
from .translate_server import TranslateServer

engine_te = TranslateEngine(
    provider_manager=self._engine._providers,
    groq_config=self._config.groq,
)
self._translate_server = TranslateServer(engine_te, self._config.server_port)
self._translate_server.start()
```

- [ ] **Step 4: Test server manually**

Build and run the app. Test with curl:
```bash
curl http://127.0.0.1:19378/health
# → {"status": "ok", "version": "5.0.0"}

TOKEN=$(curl -s http://127.0.0.1:19378/token | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -X POST http://127.0.0.1:19378/translate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"texts":["Hello world","Good morning"],"target_lang":"uk"}'
# → {"translations": ["Привіт світ", "Доброго ранку"], "engine": "DeepL #1"}
```

- [ ] **Step 5: Commit**

```bash
git add src/translate_server.py src/config.py src/tray_app.py
git commit -m "feat: add translation HTTP server on localhost:19378"
```

---

## Task 3: Browser Extension — Core Files

**Files:**
- Create: `extension/manifest.json`
- Create: `extension/background.js`
- Create: `extension/content.js`
- Create: `extension/popup.html`
- Create: `extension/popup.js`
- Create: `extension/popup.css`

- [ ] **Step 1: Create `extension/manifest.json`**

```json
{
  "manifest_version": 3,
  "name": "AI Polyglot Kit — Page Translator",
  "version": "5.0.0",
  "description": "Translate web pages using AI Polyglot Kit desktop app",
  "permissions": ["storage", "activeTab"],
  "host_permissions": ["http://127.0.0.1:19378/*"],
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "content_scripts": [{
    "matches": ["<all_urls>"],
    "js": ["content.js"],
    "run_at": "document_idle"
  }],
  "background": {
    "service_worker": "background.js"
  },
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  }
}
```

- [ ] **Step 2: Create `extension/background.js`**

Service worker: token management, batching, API communication.

```javascript
const API_BASE = "http://127.0.0.1:19378";
const BATCH_SIZE = 50;

// ── Token Management ──

async function getToken() {
  const stored = await chrome.storage.local.get("apk_token");
  if (stored.apk_token) return stored.apk_token;
  return await fetchNewToken();
}

async function fetchNewToken() {
  const resp = await fetch(`${API_BASE}/token`);
  if (!resp.ok) throw new Error("Token unavailable");
  const data = await resp.json();
  await chrome.storage.local.set({ apk_token: data.token });
  return data.token;
}

async function clearToken() {
  await chrome.storage.local.remove("apk_token");
}

// ── Health Check ──

async function checkHealth() {
  try {
    const resp = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    if (!resp.ok) return { connected: false };
    const data = await resp.json();
    return { connected: true, version: data.version };
  } catch {
    return { connected: false };
  }
}

// ── Translation ──

async function translateBatch(texts, targetLang) {
  let token = await getToken();

  const resp = await fetch(`${API_BASE}/translate`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ texts, target_lang: targetLang, source_lang: "auto" }),
  });

  if (resp.status === 401) {
    // Token expired, get new one
    await clearToken();
    token = await fetchNewToken();
    const retry = await fetch(`${API_BASE}/translate`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ texts, target_lang: targetLang, source_lang: "auto" }),
    });
    if (!retry.ok) throw new Error(`Translate failed: ${retry.status}`);
    return await retry.json();
  }

  if (!resp.ok) throw new Error(`Translate failed: ${resp.status}`);
  return await resp.json();
}

async function translateAll(texts, targetLang, sendProgress) {
  const batches = [];
  for (let i = 0; i < texts.length; i += BATCH_SIZE) {
    batches.push(texts.slice(i, i + BATCH_SIZE));
  }

  const results = new Array(texts.length);
  let completed = 0;
  let engine = "";

  // Send batches in parallel (max 3 concurrent)
  const concurrency = 3;
  const queue = batches.map((batch, idx) => ({ batch, idx }));
  const workers = [];

  for (let w = 0; w < Math.min(concurrency, queue.length); w++) {
    workers.push((async () => {
      while (queue.length > 0) {
        const { batch, idx } = queue.shift();
        try {
          const data = await translateBatch(batch, targetLang);
          const offset = idx * BATCH_SIZE;
          data.translations.forEach((t, i) => { results[offset + i] = t; });
          engine = data.engine || engine;
        } catch (e) {
          const offset = idx * BATCH_SIZE;
          batch.forEach((t, i) => { results[offset + i] = t; }); // keep original
        }
        completed++;
        sendProgress(completed, batches.length);
      }
    })());
  }

  await Promise.all(workers);
  return { translations: results, engine };
}

// ── Message Handler ──

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "health") {
    checkHealth().then(sendResponse);
    return true;
  }

  if (msg.action === "translate") {
    translateAll(msg.texts, msg.lang, (done, total) => {
      chrome.runtime.sendMessage({ action: "progress", done, total });
    }).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }

  if (msg.action === "clearToken") {
    clearToken().then(() => sendResponse({ ok: true }));
    return true;
  }
});
```

- [ ] **Step 3: Create `extension/content.js`**

DOM walker, viewport observer, inline replacement.

```javascript
// ── State ──

let isTranslated = false;
let observer = null;
let currentLang = "";

const SKIP_TAGS = new Set([
  "SCRIPT", "STYLE", "CODE", "PRE", "NOSCRIPT", "SVG", "CANVAS",
  "TEXTAREA", "INPUT", "SELECT", "IFRAME",
]);

// ── DOM Walker ──

function getVisibleTextNodes() {
  const nodes = [];
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        if (!node.textContent.trim()) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        if (SKIP_TAGS.has(parent.tagName)) return NodeFilter.FILTER_REJECT;
        if (parent.closest("[data-apk-translated]")) return NodeFilter.FILTER_REJECT;
        if (!isInViewport(parent)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );
  while (walker.nextNode()) nodes.push(walker.currentNode);
  return nodes;
}

function isInViewport(el) {
  const rect = el.getBoundingClientRect();
  return (
    rect.bottom >= 0 &&
    rect.top <= window.innerHeight &&
    rect.right >= 0 &&
    rect.left <= window.innerWidth
  );
}

// ── Translation ──

async function translateVisibleNodes(lang) {
  const textNodes = getVisibleTextNodes();
  if (textNodes.length === 0) return;

  const texts = textNodes.map(n => n.textContent.trim());

  const response = await chrome.runtime.sendMessage({
    action: "translate",
    texts,
    lang,
  });

  if (response.error) {
    console.error("APK translate error:", response.error);
    return;
  }

  const { translations } = response;
  textNodes.forEach((node, i) => {
    if (!translations[i] || translations[i] === texts[i]) return;
    const parent = node.parentElement;
    if (!parent || parent.hasAttribute("data-apk-translated")) return;
    parent.setAttribute("data-apk-original", node.textContent);
    parent.setAttribute("data-apk-translated", "true");
    node.textContent = translations[i];
  });
}

// ── Viewport Observer ──

function startScrollObserver(lang) {
  if (observer) observer.disconnect();

  let debounceTimer;
  const onScroll = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => translateVisibleNodes(lang), 300);
  };
  window.addEventListener("scroll", onScroll, { passive: true });

  // Store cleanup
  observer = { disconnect: () => window.removeEventListener("scroll", onScroll) };
}

// ── Revert ──

function revertTranslation() {
  document.querySelectorAll("[data-apk-translated]").forEach(el => {
    const original = el.getAttribute("data-apk-original");
    if (original) {
      // Find the text node and restore
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const textNode = walker.nextNode();
      if (textNode) textNode.textContent = original;
    }
    el.removeAttribute("data-apk-translated");
    el.removeAttribute("data-apk-original");
  });
  if (observer) {
    observer.disconnect();
    observer = null;
  }
  isTranslated = false;
}

// ── Tooltip CSS ──

function injectTooltipStyles() {
  if (document.getElementById("apk-tooltip-styles")) return;
  const style = document.createElement("style");
  style.id = "apk-tooltip-styles";
  style.textContent = `
    [data-apk-translated]:hover {
      outline: 1px dashed #0078d4;
      outline-offset: 2px;
      position: relative;
    }
    [data-apk-translated]:hover::after {
      content: attr(data-apk-original);
      position: absolute;
      bottom: 100%;
      left: 0;
      background: #1a1a2e;
      color: #fff;
      padding: 6px 10px;
      border-radius: 4px;
      font-size: 13px;
      white-space: pre-wrap;
      max-width: 400px;
      z-index: 999999;
      pointer-events: none;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
  `;
  document.head.appendChild(style);
}

// ── Message Listener ──

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "startTranslation") {
    isTranslated = true;
    currentLang = msg.lang;
    injectTooltipStyles();
    translateVisibleNodes(msg.lang).then(() => {
      startScrollObserver(msg.lang);
      sendResponse({ ok: true });
    });
    return true;
  }

  if (msg.action === "revert") {
    revertTranslation();
    sendResponse({ ok: true });
  }

  if (msg.action === "getState") {
    sendResponse({ isTranslated, lang: currentLang });
  }
});
```

- [ ] **Step 4: Create `extension/popup.html`**

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <div class="header">
    <img src="icons/icon48.png" alt="" class="logo">
    <span class="title">AI Polyglot Kit</span>
  </div>

  <div id="status" class="status"></div>

  <div id="controls" class="controls" style="display:none">
    <select id="lang">
      <option value="uk">Українська</option>
      <option value="ru">Русский</option>
      <option value="en">English</option>
      <option value="de">Deutsch</option>
      <option value="fr">Français</option>
      <option value="es">Español</option>
      <option value="pl">Polski</option>
      <option value="it">Italiano</option>
      <option value="pt">Português</option>
      <option value="ja">日本語</option>
      <option value="zh">中文</option>
      <option value="ko">한국어</option>
      <option value="tr">Türkçe</option>
      <option value="ar">العربية</option>
    </select>
    <button id="translateBtn" class="btn-primary">Translate page</button>
  </div>

  <div id="progress" class="progress" style="display:none"></div>

  <script src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 5: Create `extension/popup.js`**

```javascript
const langSelect = document.getElementById("lang");
const translateBtn = document.getElementById("translateBtn");
const statusEl = document.getElementById("status");
const controlsEl = document.getElementById("controls");
const progressEl = document.getElementById("progress");

let pageTranslated = false;

// ── Init ──

async function init() {
  // Restore last language
  const stored = await chrome.storage.local.get("apk_last_lang");
  if (stored.apk_last_lang) langSelect.value = stored.apk_last_lang;

  // Check health
  const health = await chrome.runtime.sendMessage({ action: "health" });
  if (health.connected) {
    statusEl.textContent = `Connected (v${health.version})`;
    statusEl.className = "status connected";
    controlsEl.style.display = "flex";
  } else {
    statusEl.textContent = "App not running — launch AI Polyglot Kit";
    statusEl.className = "status disconnected";
    return;
  }

  // Check page state
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    const state = await chrome.tabs.sendMessage(tab.id, { action: "getState" });
    if (state && state.isTranslated) {
      pageTranslated = true;
      translateBtn.textContent = "Show original";
      translateBtn.className = "btn-secondary";
    }
  } catch { /* content script not loaded */ }
}

// ── Translate / Revert ──

translateBtn.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const lang = langSelect.value;

  // Save language preference
  await chrome.storage.local.set({ apk_last_lang: lang });

  if (pageTranslated) {
    // Revert
    await chrome.tabs.sendMessage(tab.id, { action: "revert" });
    pageTranslated = false;
    translateBtn.textContent = "Translate page";
    translateBtn.className = "btn-primary";
    progressEl.style.display = "none";
    return;
  }

  // Translate
  translateBtn.disabled = true;
  translateBtn.textContent = "Translating...";
  progressEl.style.display = "block";

  await chrome.tabs.sendMessage(tab.id, { action: "startTranslation", lang });

  pageTranslated = true;
  translateBtn.disabled = false;
  translateBtn.textContent = "Show original";
  translateBtn.className = "btn-secondary";
  progressEl.style.display = "none";
});

// ── Progress ──

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === "progress") {
    progressEl.style.display = "block";
    progressEl.textContent = `Translating... ${msg.done}/${msg.total} batches`;
  }
});

init();
```

- [ ] **Step 6: Create `extension/popup.css`**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 300px; font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; padding: 16px; background: #fff; }
.header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.logo { width: 24px; height: 24px; }
.title { font-weight: 600; font-size: 15px; color: #1a1a1a; }
.status { padding: 8px; border-radius: 6px; font-size: 12px; margin-bottom: 12px; }
.status.connected { background: #e6f7e6; color: #107c10; }
.status.disconnected { background: #fde7e7; color: #d13438; }
.controls { display: flex; gap: 8px; align-items: center; }
select { flex: 1; padding: 8px; border: 1px solid #d0d0d0; border-radius: 4px; font-size: 13px; }
.btn-primary { padding: 8px 16px; background: #0078d4; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; white-space: nowrap; }
.btn-primary:hover { background: #106ebe; }
.btn-primary:disabled { background: #999; cursor: default; }
.btn-secondary { padding: 8px 16px; background: #e0e0e0; color: #1a1a1a; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; white-space: nowrap; }
.btn-secondary:hover { background: #d0d0d0; }
.progress { margin-top: 8px; font-size: 12px; color: #666; }
```

- [ ] **Step 7: Create placeholder icons**

Create `extension/icons/` directory. Generate simple 16/48/128px PNG icons (blue circle with "T" letter — can be refined later).

- [ ] **Step 8: Test extension manually**

Load unpacked from `extension/` in Chrome → `chrome://extensions` → Developer mode → Load unpacked. Click popup, verify health check, test translate on a page.

- [ ] **Step 9: Commit**

```bash
git add extension/
git commit -m "feat: browser extension — popup, content script, background worker"
```

---

## Task 4: Browser Installer

**Files:**
- Create: `src/browser_installer.py`
- Modify: `src/settings_ui.py`

- [ ] **Step 1: Create `src/browser_installer.py`**

```python
"""Browser detection and extension auto-install via HKCU registry policy.

Supports: Chrome, Edge, Vivaldi, Brave, Opera (all Chromium-based).
Install writes ExtensionInstallForcelist to HKCU (no UAC needed).
"""

import logging
import shutil
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path

from .config import APP_DIR

logger = logging.getLogger(__name__)

EXTENSION_DIR = Path(__file__).parent.parent / "extension"
CRX_DIR = APP_DIR / "extension"
PEM_PATH = APP_DIR / "extension.pem"

UPDATE_URL = "http://127.0.0.1:19378/extension/update.xml"


@dataclass
class BrowserInfo:
    name: str
    exe_path: Path | None
    policy_key: str  # HKCU registry path for ExtensionInstallForcelist


# Browser definitions
BROWSERS = [
    BrowserInfo("Google Chrome", None,
                r"SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist"),
    BrowserInfo("Microsoft Edge", None,
                r"SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist"),
    BrowserInfo("Vivaldi", None,
                r"SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist"),
    BrowserInfo("Brave", None,
                r"SOFTWARE\Policies\BraveSoftware\Brave\ExtensionInstallForcelist"),
    BrowserInfo("Opera", None,
                r"SOFTWARE\Policies\Opera Software\Opera Stable\ExtensionInstallForcelist"),
]

# Known exe locations (registry keys and paths)
_EXE_SEARCHES = {
    "Google Chrome": [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon", "version"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe", None),
    ],
    "Microsoft Edge": [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe", None),
    ],
    "Vivaldi": [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Vivaldi", "InstallLocation"),
    ],
    "Brave": [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BraveSoftware\Brave-Browser\Capabilities", "ApplicationName"),
    ],
    "Opera": [],
}

_EXE_PATHS = {
    "Google Chrome": [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ],
    "Microsoft Edge": [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ],
    "Vivaldi": [],  # dynamic from LOCALAPPDATA
    "Brave": [],
    "Opera": [],
}


def find_browsers() -> list[BrowserInfo]:
    """Find installed Chromium browsers."""
    found = []
    for browser in BROWSERS:
        exe = _find_browser_exe(browser.name)
        if exe:
            found.append(BrowserInfo(browser.name, exe, browser.policy_key))
    return found


def _find_browser_exe(name: str) -> Path | None:
    """Try registry then known paths."""
    # Registry
    for hive, key_path, value_name in _EXE_SEARCHES.get(name, []):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                val, _ = winreg.QueryValueEx(key, value_name or "")
                p = Path(val)
                if p.exists():
                    return p
        except (OSError, FileNotFoundError):
            pass

    # Known paths
    for p in _EXE_PATHS.get(name, []):
        if p.exists():
            return p

    # LOCALAPPDATA searches
    import os
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    searches = {
        "Vivaldi": local / "Vivaldi" / "Application" / "vivaldi.exe",
        "Brave": local / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        "Opera": local / "Programs" / "Opera" / "opera.exe",
    }
    p = searches.get(name)
    if p and p.exists():
        return p

    return None


def is_extension_installed(browser: BrowserInfo) -> bool:
    """Check if our extension is registered in browser's ExtensionInstallForcelist."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, browser.policy_key) as key:
            i = 0
            while True:
                try:
                    _, value, _ = winreg.EnumValue(key, i)
                    if UPDATE_URL in str(value):
                        return True
                    i += 1
                except OSError:
                    break
    except (OSError, FileNotFoundError):
        pass
    return False


def get_extension_id() -> str:
    """Get or compute the extension ID from the PEM key."""
    if not PEM_PATH.exists():
        _generate_pem()
    # Extension ID = first 32 chars of SHA256 of DER public key, mapped a-p
    from hashlib import sha256
    import base64
    pem_data = PEM_PATH.read_text()
    # Extract public key from PEM (simplified — works with openssl-generated keys)
    # For production, use cryptography library
    # Placeholder: deterministic ID from PEM hash
    h = sha256(pem_data.encode()).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in h)


def _generate_pem():
    """Generate a new PEM key for CRX signing."""
    CRX_DIR.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["openssl", "genrsa", "-out", str(PEM_PATH), "2048"],
            check=True, capture_output=True,
        )
        logger.info("Generated extension PEM key: %s", PEM_PATH)
    except FileNotFoundError:
        # openssl not available — generate with Python
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        PEM_PATH.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
        logger.info("Generated extension PEM key (Python): %s", PEM_PATH)


def install_extension(browser: BrowserInfo) -> None:
    """Install extension via HKCU registry policy."""
    ext_id = get_extension_id()
    value = f"{ext_id};{UPDATE_URL}"

    # Ensure CRX exists
    _pack_crx()

    # Write registry
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, browser.policy_key,
                                 0, winreg.KEY_SET_VALUE)
        # Find next available index
        idx = 1
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, browser.policy_key) as rk:
                while True:
                    try:
                        winreg.EnumValue(rk, idx - 1)
                        idx += 1
                    except OSError:
                        break
        except (OSError, FileNotFoundError):
            pass

        winreg.SetValueEx(key, str(idx), 0, winreg.REG_SZ, value)
        winreg.CloseKey(key)
        logger.info("Extension installed for %s (HKCU, idx=%d)", browser.name, idx)
    except Exception as e:
        logger.error("Failed to install extension for %s: %s", browser.name, e)
        raise


def uninstall_extension(browser: BrowserInfo) -> None:
    """Remove extension from HKCU registry policy."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, browser.policy_key,
                            0, winreg.KEY_ALL_ACCESS) as key:
            i = 0
            to_delete = []
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    if UPDATE_URL in str(value):
                        to_delete.append(name)
                    i += 1
                except OSError:
                    break
            for name in to_delete:
                winreg.DeleteValue(key, name)
        logger.info("Extension uninstalled for %s", browser.name)
    except (OSError, FileNotFoundError):
        pass


def _pack_crx():
    """Pack extension/ directory into a CRX file."""
    CRX_DIR.mkdir(parents=True, exist_ok=True)
    crx_path = CRX_DIR / "apk.crx"

    # Copy extension files
    ext_staging = CRX_DIR / "src"
    if ext_staging.exists():
        shutil.rmtree(ext_staging)
    shutil.copytree(EXTENSION_DIR, ext_staging)

    # For now, create a simple zip-based CRX
    # Full CRX3 signing will be implemented with cryptography library
    import zipfile
    zip_path = CRX_DIR / "apk.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in ext_staging.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(ext_staging))

    # Copy as .crx (simplified — real CRX3 needs proper header)
    shutil.copy2(zip_path, crx_path)
    zip_path.unlink()

    logger.info("Extension packed: %s", crx_path)
```

- [ ] **Step 2: Add browser section to Settings UI**

In `src/settings_ui.py`, in the Interface tab build method, after the telemetry section, add:

```python
# Browser extensions section
ttk.Separator(tab_iface, orient="horizontal").pack(fill="x", padx=0, pady=(12, 4))
ttk.Label(tab_iface, text=t("settings.browser_extensions"),
          font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 8))

from .browser_installer import find_browsers, is_extension_installed, install_extension, uninstall_extension

browsers = find_browsers()
if not browsers:
    ttk.Label(tab_iface, text=t("settings.no_browsers_found"),
              foreground=self._dark_fg2 or "#888888").pack(anchor="w")
else:
    for browser in browsers:
        row = ttk.Frame(tab_iface)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=browser.name).pack(side="left")
        installed = is_extension_installed(browser)
        if installed:
            btn = ttk.Button(row, text=t("settings.installed") + " ✓", state="disabled")
        else:
            btn = ttk.Button(row, text=t("settings.install"),
                             command=lambda b=browser, bt=None: self._install_browser_ext(b, bt))
        btn.pack(side="right", padx=4)
```

Add `_install_browser_ext` method and i18n keys.

- [ ] **Step 3: Add i18n keys**

In `src/i18n.py`, add:
```python
"settings.browser_extensions": "Розширення для браузерів:" / "Browser extensions:",
"settings.no_browsers_found": "Браузери не знайдено" / "No browsers found",
"settings.install": "Встановити" / "Install",
"settings.installed": "Встановлено" / "Installed",
"settings.uninstall": "Видалити" / "Uninstall",
```

- [ ] **Step 4: Test browser detection**

Run the app, open Settings → Interface. Verify found browsers are displayed with correct Install/Installed status.

- [ ] **Step 5: Commit**

```bash
git add src/browser_installer.py src/settings_ui.py src/i18n.py
git commit -m "feat: browser extension installer — auto-detect + HKCU registry"
```

---

## Task 5: Integration, Installer, Version Bump

**Files:**
- Modify: `src/translate_server.py` (update.xml serving)
- Modify: `installer.iss`

- [ ] **Step 1: Implement update.xml serving in translate_server.py**

Replace the stub `_serve_update_xml` with actual XML generation using `get_extension_id()`.

```python
def _serve_update_xml(self):
    from .browser_installer import get_extension_id
    from .config import APP_VERSION
    ext_id = get_extension_id()
    xml = f'''<?xml version="1.0"?>
<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">
  <app appid="{ext_id}">
    <updatecheck codebase="http://127.0.0.1:19378/extension/apk.crx" version="{APP_VERSION}"/>
  </app>
</gupdate>'''
    self.send_response(200)
    self.send_header("Content-Type", "application/xml")
    self._cors_headers()
    self.end_headers()
    self.wfile.write(xml.encode("utf-8"))
```

- [ ] **Step 2: Update installer.iss**

Add `extension\` directory to the installer:

```iss
[Files]
; ... existing files ...
Source: "C:\tmp\dist\AIPolyglotKit\extension\*"; DestDir: "{app}\extension"; Flags: recursesubdirs
```

Bump version to `5.0.0`.

- [ ] **Step 3: Full end-to-end test**

1. Build with PyInstaller
2. Run app
3. `curl http://127.0.0.1:19378/health` → OK
4. Open Settings → Interface → Install extension to a browser
5. Verify extension appears in browser
6. Open a page → click extension → select language → Translate
7. Verify inline translation works
8. Scroll → verify new elements translate
9. Click "Show original" → verify revert

- [ ] **Step 4: Build installer**

```bash
pyinstaller groq_dictation.spec --distpath C:/tmp/groq-dist --workpath C:/tmp/groq-work --noconfirm
cp -r C:/tmp/groq-dist/AIPolyglotKit C:/tmp/dist/AIPolyglotKit
ISCC.exe C:/tmp/installer.iss
```

- [ ] **Step 5: Commit, tag, release**

```bash
git add -A
git commit -m "feat: v5.0.0 — browser page translation extension"
git tag v5.0.0
git push origin master --tags
gh release create v5.0.0 installer.exe --title "v5.0.0 — Browser Page Translation"
```

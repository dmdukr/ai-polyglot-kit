# AI Polyglot Kit v5.0.0 — Browser Page Translation Extension

## Overview

Add full-page inline translation to Chromium-based browsers (Chrome, Vivaldi, Edge, Brave, Opera) via a browser extension that communicates with the AI Polyglot Kit desktop application through a local REST API.

## Architecture

```
┌─────────────────────────────────────┐
│  Browser Extension (Chromium MV3)   │
│  ┌───────────┐  ┌────────────────┐  │
│  │  Popup UI │  │ Content Script │  │
│  │ (lang +   │  │ (DOM walker,   │  │
│  │  status)  │  │  inline swap,  │  │
│  └─────┬─────┘  │  hover tooltip)│  │
│        │        └───────┬────────┘  │
│  ┌─────┴────────────────┴────────┐  │
│  │     Background Service Worker │  │
│  │  (batching, API calls, state) │  │
│  └──────────────┬────────────────┘  │
└─────────────────┼───────────────────┘
                  │ REST API
                  │ http://127.0.0.1:19378
                  │ Authorization: Bearer <token>
┌─────────────────┼───────────────────┐
│  AI Polyglot Kit (Desktop)          │
│  ┌──────────────┴────────────────┐  │
│  │   Translation HTTP Server     │  │
│  │   /health /translate /token   │  │
│  │   /extension/update.xml .crx  │  │
│  └──────────────┬────────────────┘  │
│  ┌──────────────┴────────────────┐  │
│  │   TranslateEngine             │  │
│  │   DeepL → LLM fallback       │  │
│  │   (shared with overlay)       │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

## REST API

Server binds to `127.0.0.1:19378` only. Traffic never leaves the machine.

### `GET /health`

No auth required.

```json
→ 200 { "status": "ok", "version": "5.0.0" }
```

### `GET /token`

No auth required. Returns a one-time token. After first call, returns 403.

```json
→ 200 { "token": "a1b2c3d4..." }
→ 403 { "error": "token_already_issued" }
```

Token is a `secrets.token_hex(32)`, stored in memory only. New token generated on each app restart. Extension re-fetches via `/token` when old token stops working.

### `POST /translate`

Requires `Authorization: Bearer <token>`.

```json
Request:
{
  "texts": ["Hello world", "Click here", "Privacy policy"],
  "target_lang": "uk",
  "source_lang": "auto"
}

→ 200
{
  "translations": ["Привіт світ", "Натисніть тут", "Політика конфіденційності"],
  "engine": "DeepL #1"
}

→ 401 { "error": "unauthorized" }
→ 503 { "error": "no_providers" }
```

Batch limit: 50 texts per request. Extension splits larger sets into parallel requests.

### `GET /extension/update.xml`

No auth. Chrome update manifest for force-install.

```xml
<?xml version="1.0"?>
<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">
  <app appid="<extension-id>">
    <updatecheck codebase="http://127.0.0.1:19378/extension/apk.crx" version="5.0.0"/>
  </app>
</gupdate>
```

### `GET /extension/apk.crx`

No auth. Serves the signed `.crx` extension package.

### Security

- **Bind**: `127.0.0.1` only (not `0.0.0.0`)
- **Auth**: Bearer token on all translate requests
- **CORS**: `Access-Control-Allow-Origin: chrome-extension://<id>` (dev: `*` with auth check)
- **Token lifecycle**: one-time issue, in-memory only, rotates on app restart
- **CRX signing**: `.pem` key in `%APPDATA%\AIPolyglotKit\extension.pem`, Chrome validates signature

## Browser Extension

### Manifest V3

```json
{
  "manifest_version": 3,
  "name": "AI Polyglot Kit — Page Translator",
  "version": "5.0.0",
  "permissions": ["storage", "activeTab"],
  "host_permissions": ["http://127.0.0.1:19378/*"],
  "action": { "default_popup": "popup.html" },
  "content_scripts": [{
    "matches": ["<all_urls>"],
    "js": ["content.js"],
    "run_at": "document_idle"
  }],
  "background": { "service_worker": "background.js" }
}
```

### File Structure

```
extension/
  manifest.json
  background.js
  content.js
  popup.html
  popup.js
  popup.css
  icons/
    icon16.png
    icon48.png
    icon128.png
```

Plain JS, no bundler, no framework.

### Popup (popup.html + popup.js)

- Language dropdown (14 languages), last selection saved in `chrome.storage.local`
- Button: "Translate page" / "Show original" (toggle)
- Status line: "Connected" / "App not running — launch AI Polyglot Kit"
- Progress: "Translating... 3/7 batches"

### Content Script (content.js)

**DOM Walker:**
- `TreeWalker` with `SHOW_TEXT` filter collects text nodes
- Skips: `<script>`, `<style>`, `<code>`, `<pre>`, `<noscript>`, empty/whitespace-only
- Skips elements already translated (marked with `data-apk-translated`)

**Viewport-based translation:**
1. User clicks "Translate" in popup
2. Content script collects text nodes visible in current viewport
3. Batches of up to 50 texts sent to background worker
4. Background worker sends parallel `POST /translate` requests
5. Results returned to content script → inline text replacement
6. `IntersectionObserver` watches for new elements entering viewport on scroll
7. New visible untranslated elements → next batch → translate → replace
8. Scrolling is never blocked; replacement happens asynchronously

**Inline replacement:**
- Original text saved in `data-apk-original` attribute on parent element
- Text node content replaced with translation
- Parent element marked with `data-apk-translated="true"`
- Hover on translated element → CSS tooltip showing original text

**Revert:**
- "Show original" button → all elements with `data-apk-original` restored to original text
- `data-apk-translated` attributes removed

### Background Service Worker (background.js)

- Stores auth token in `chrome.storage.local`
- On first use: `GET /health` → `GET /token` → save token
- On token expired (401): re-fetch `/token`
- On connection refused: status "App not running"
- Receives messages from content script: `{action: "translate", texts: [...], lang: "uk"}`
- Splits into batches of 50, sends parallel `POST /translate`
- Returns results to content script

## Desktop Changes

### New Files

**`src/translate_server.py`** — HTTP server

- `http.server.HTTPServer` from stdlib, runs in daemon thread
- Handles all API endpoints listed above
- Serves `.crx` and `update.xml` from `%APPDATA%\AIPolyglotKit\extension\`
- Token generation and validation
- CORS headers on all responses

**`src/translate_engine.py`** — Shared translation logic

- Extracted from `translate_overlay.py`
- `translate_batch(texts: list[str], target_lang: str, source_lang: str) -> TranslateResult`
- DeepL with key rotation → LLM fallback (same chain as overlay)
- Used by both `translate_overlay.py` and `translate_server.py`

**`src/browser_installer.py`** — Browser detection and extension install

- `find_browsers() -> list[BrowserInfo]` — scans registry + standard paths for Chromium browsers
- `is_extension_installed(browser) -> bool` — checks `HKCU\SOFTWARE\Policies\<browser>\ExtensionInstallForcelist`
- `install_extension(browser) -> None` — generates .crx (if not exists), writes HKCU registry entry
- `uninstall_extension(browser) -> None` — removes registry entry
- CRX generation using `.pem` key (stored in `%APPDATA%\AIPolyglotKit\extension.pem`)

Supported browsers and their registry paths:

| Browser | Registry key |
|---------|-------------|
| Chrome | `HKCU\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist` |
| Edge | `HKCU\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist` |
| Vivaldi | `HKCU\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist` (uses Chrome policies) |
| Brave | `HKCU\SOFTWARE\Policies\BraveSoftware\Brave\ExtensionInstallForcelist` |
| Opera | `HKCU\SOFTWARE\Policies\Opera Software\Opera Stable\ExtensionInstallForcelist` |

No UAC required (HKCU, not HKLM).

### Modified Files

**`src/tray_app.py`**
- Start translate server in `_setup()`: `TranslateServer(config, provider_manager).start()`

**`src/translate_overlay.py`**
- Refactor: delegate translation logic to `translate_engine.py`

**`src/settings_ui.py`**
- Add "Browser extensions" section to Interface tab
- For each found browser: label + "Install" / "Installed ✓" / "Uninstall" button
- Buttons call `browser_installer.install_extension()` / `uninstall_extension()`

**`src/config.py`**
- `APP_VERSION = "5.0.0"`
- Add `server_port: int = 19378` to config

**`installer.iss`**
- Version bump to 5.0.0
- Include `extension/` directory in installer package

## Translation Flow (end to end)

```
User clicks extension icon → popup opens
  → popup checks GET /health
  → connected: show language dropdown + "Translate" button
  → not connected: show "Launch AI Polyglot Kit"

User selects language (e.g. "uk"), clicks "Translate"
  → popup sends message to content script: {action: "translate", lang: "uk"}
  → content script: TreeWalker collects visible text nodes
  → 150 visible text nodes found
  → batch 1: texts[0..49]   → background → POST /translate ─┐
  → batch 2: texts[50..99]  → background → POST /translate ─┤ parallel
  → batch 3: texts[100..149]→ background → POST /translate ─┘
  → results arrive → inline replacement (text by text)
  → popup shows "Translating... 2/3 batches"
  → all done → popup shows "Translated ✓"

User scrolls down
  → IntersectionObserver fires for new visible elements
  → new untranslated text nodes collected
  → next batch → POST /translate → inline replacement

User clicks "Show original"
  → content script restores all data-apk-original values
  → translation state cleared
```

## Extension Installation Flow

```
User opens Settings → Interface tab → "Browser extensions" section

App scans for installed browsers (registry + paths)
  → Chrome found at C:\Program Files\Google\Chrome\...
  → Vivaldi found at C:\Users\...\Vivaldi\...
  → Edge not found

For each found browser, check HKCU registry for extension:
  → Chrome: not installed → [Install] button active
  → Vivaldi: installed → [Installed ✓] button disabled

User clicks [Install] next to Chrome:
  1. Generate extension.pem if not exists (first time)
  2. Pack extension/ → apk.crx (signed with .pem)
  3. Compute extension ID from .pem public key
  4. Write to HKCU\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist:
     "<extension-id>;http://127.0.0.1:19378/extension/update.xml"
  5. Button changes to [Installed ✓]
  6. Chrome picks up extension automatically (within ~60s or on restart)
```

## Version

- Desktop: 5.0.0
- Extension: 5.0.0 (synced with desktop version)

# AI Polyglot Kit v6.0 — Major Update Design Specification

**Date:** 2026-03-26
**Updated:** 2026-03-28 (post-review: architecture, STRIDE, dependency audit, UI technology decision, Adaptive Correction Engine, mockup alignment, pipeline redesign)
**Status:** Draft
**Author:** Claude (orchestrator) + User (product owner)

---

## 1. Overview

Major feature update transforming AI Polyglot Kit from a basic voice dictation tool into a full-featured desktop dictation platform competing with Aqua Voice, Wispr Flow, and SuperWhisper. Covers microphone improvements, new UI design, extended functionality, and infrastructure for future growth.

**Goals:**
- Reduce recording latency to <200ms (from ~500ms)
- Add noise suppression and adaptive gain
- Support device hotplugging without restart
- Separate hotkeys for recording and feedback
- Add text replacements, history, dictionary UI, custom instructions
- Redesign UI to match Aqua Voice quality (dark-first, clean, accessible)
- Add context-aware formatting and multi-app text injection
- Add speaker verification (post-STT filtering)
- Add offline STT fallback mode
- Encrypt sensitive data at rest (voice biometrics, history, API keys)

---

## 2. Feature Specifications

### 2.1 Hotkey Separation

**Problem:** Single F12 key handles both hold-to-record and double-tap-feedback. 300ms delay needed to distinguish them, adding latency to recording.

**Design:**

| Action | Default Key | Behavior |
|--------|------------|----------|
| Record | F12 (hold) | Keydown → immediate mic open + start recording. Keyup → stop + process. If held <200ms → discard buffer (accidental tap). |
| Feedback | F11 (double-tap) | Double-tap within 500ms. Single tap = ignored (accident protection). |
| Cancel | Escape | During recording → abort, discard audio, don't type anything. |
| Paste Last | Ctrl+Shift+V | Insert last transcript again at cursor position. |

**Feedback guard conditions** (ALL must be true):
1. `_last_normalized_text` is not empty
2. Focus is still in the same HWND where text was injected
   - Saved at injection time: `_injection_hwnd = GetForegroundWindow()`
   - Checked at feedback time: current `GetForegroundWindow()` matches saved value
   - Note: `GetFocus()` check dropped — too strict, can break when user clicks within the same window

**Config:**
```yaml
hotkey: f12
hotkey_mode: hold
feedback_hotkey: f11
cancel_hotkey: escape
paste_last_hotkey: ctrl+shift+v
```
All keys configurable in Settings UI.

**Files:**
- Modify: `src/tray_app.py` — split `_on_ptt_event` into separate handlers
- Modify: `src/engine.py` — add `cancel()`, `paste_last()`, update `on_tap()` with HWND guard
- Modify: `src/config.py` — add new hotkey fields
- Modify: `src/settings_ui.py` → `src/ui/pages/settings_keybindings.py` — keybindings page
- Modify: `src/text_injector.py` — save HWND at injection time

---

### 2.2 Reduced Recording Latency

**Problem:** 500ms delay from keypress to recording start (300ms hold threshold + 200ms warmup).

**Design:**
- Remove 300ms hold threshold entirely (no longer needed with separate keys)
- On F12 keydown → immediately call `ac.start()` + `engine.start_if_idle()`
- Reduce ChunkManager warmup skip from 150ms to 60ms (2 frames) — RNNoise handles click removal
- Background gain calibration at app startup (not on first press)
- Tap on F12 (<200ms hold) → discard buffer, no processing (see 2.1)

**Target:** <200ms from keypress to actual recording (limited only by `pa.open()` ~100-150ms).

**Files:**
- Modify: `src/tray_app.py` — simplify F12 handler to immediate start/stop
- Modify: `src/chunk_manager.py` — reduce `_warmup_skip` from 5 to 2
- Modify: `src/audio_capture.py` — calibrate gain on `__init__` background thread

---

### 2.3 Device Hotplug Detection

**Problem:** PyAudio doesn't detect new audio devices (e.g., plugging in headset) without terminate + reinitialize. Currently requires app restart.

**Design:**
- Use `pycaw` library (`IMMNotificationClient`) to receive Windows Core Audio device change events
- **COM threading:** Monitoring thread must call `comtypes.CoInitializeEx(COINIT_MULTITHREADED)` before registering callback. If COM registration fails, fall back to 10s polling.
- **Debounce:** Device change events debounced with 2s cooldown, max 5 rescans/minute with backoff.
- On device change event:
  1. Set flag `_pending_device_rescan = True`
  2. Show toast notification: "New device detected: {name}"
  3. Do NOT interrupt current recording
- After current recording ends (or if idle):
  1. Stop stream, `pa.terminate()`, `pa = PyAudio()` — reinitialize
  2. Scan for new device
  3. If external mic (headset/USB) → auto-switch + toast "Switched to: {name}"
  4. If built-in → add to list, don't switch
- Device matching by name (not index — index changes on replug)

**Config persistence:**
```yaml
audio:
  mic_device_name: "Jabra Link 370"    # saved by name
  mic_device_index: null                # resolved at startup
  calibrated_gain: 3.2                  # cached per device
  noise_suppression: true
```

**New dependency:** `pycaw`

**Files:**
- Create: `src/device_monitor.py` — pycaw IMMNotificationClient wrapper with COM init + polling fallback
- Modify: `src/audio_capture.py` — reinit logic, device-by-name matching, persistent gain
- Modify: `src/config.py` — add `mic_device_name`, `calibrated_gain`, `noise_suppression`
- Modify: `src/tray_app.py` — device change toast notifications
- Modify: `src/engine.py` — post-recording device rescan

---

### 2.4 Noise Suppression (RNNoise)

**Problem:** Background noise (printer, fan, keyboard) degrades STT accuracy. Volume oscillates too loud/quiet.

**Design — two components:**

**A. RNNoise neural denoising:**
- Library: `pyrnnoise==0.4.3` (Python wrapper for RNNoise v0.2, pin exact version — single maintainer)
- Process: each 30ms frame → resample 16kHz→48kHz → RNNoise denoise → resample 48kHz→16kHz
- Note: resample chain adds ~0.5ms per frame CPU overhead. `pyrnnoise` requires 48kHz input.
- Returns `(speech_probability, denoised_audio)` — speech_prob can supplement VAD
- **IMPORTANT: NOT in audio callback.** RNNoise runs in a separate `AudioPreprocessor` thread:
  - PyAudio callback → raw_queue (minimal: gain only)
  - `AudioPreprocessor` thread reads raw_queue → RNNoise + AGC → processed_queue
  - ChunkManager reads from processed_queue
  - This prevents audio buffer overruns on slow machines (30ms frame budget)
- Auto-disable: if frame drop rate exceeds 5%, noise suppression is automatically disabled with a warning toast.
- Configurable: `audio.noise_suppression: true/false`

**B. Adaptive AGC (Automatic Gain Control):**
- Replace one-shot calibration with continuous EMA-based AGC
- Runs in `AudioPreprocessor` thread (after RNNoise, before processed_queue)
- Sliding window: 500ms (~17 frames), compute running RMS
- Target RMS: 3000 (existing value)
- EMA smoothing: `new_gain = 0.9 * old_gain + 0.1 * (target / current_rms)`
- Constraints: min 1.0, max 10.0, peak < 30000 (clipping protection)
- Persists `calibrated_gain` to config for next startup

**New dependency:** `pyrnnoise==0.4.3`

**Files:**
- Create: `src/noise_suppression.py` — RNNoise wrapper (init, process_frame, speech_prob)
- Create: `src/audio_preprocessor.py` — thread: raw_queue → RNNoise → AGC → processed_queue
- Modify: `src/audio_capture.py` — callback only does gain + raw_queue.put(), no denoise
- Modify: `src/chunk_manager.py` — read from processed_queue instead of raw audio queue
- Modify: `src/config.py` — `noise_suppression` field
- Modify: `src/settings_ui.py` → `src/ui/pages/settings_audio.py` — toggle for noise suppression

---

### 2.5 Microphone Test Mode

**Problem:** Users can't verify their mic works before recording.

**Design:**
- Button "Test" next to mic selector in Settings (like Aqua Voice)
- Opens mic stream → plays audio back through default output (loopback)
- Shows real-time RMS bar (visual level meter)
- Auto-stops after 10 seconds or on button press
- Uses existing `add_listener_queue()` mechanism for visualization

**Files:**
- Modify: `src/audio_capture.py` — add `start_monitor()` / `stop_monitor()` (output stream)
- Modify: `src/ui/pages/settings_audio.py` — "Test" button, RMS bar canvas widget

---

### 2.6 Speaker Lock (Post-STT Filtering)

**Problem:** In rooms with multiple speakers, STT transcribes everyone's speech.

**Design — Post-STT soft gating (no audio cutting):**

**Enrollment:**
- Button "Register Voice" in Settings → record 3-5 seconds
- ONNX-based speaker encoder generates 192-dim speaker embedding
- Saved to `%APPDATA%/AIPolyglotKit/voice_profile.npy`, **encrypted with DPAPI** (biometric data — see Section 8)

**Runtime filtering:**
1. Audio always goes to STT unmodified (no audio cutting)
2. Speaker verification submitted to `ThreadPoolExecutor` alongside STT task
3. Each chunk split into 1s segments → compute embeddings via ONNX speaker encoder
4. `speaker_ratio` = fraction of segments with `cosine_similarity > 0.65` (configurable via `speaker_lock.cosine_threshold`)
5. Decision per chunk:
   - `ratio > 0.7` → accept (target speaker dominant) (configurable via `speaker_lock.accept_threshold`)
   - `ratio 0.3-0.7` → accept with flag (mixed, let STT handle) (configurable via `speaker_lock.reject_threshold`)
   - `ratio < 0.3` → suppress text output (other speaker dominant)
6. **Synchronization:** Both STT and speaker verification submitted to the same `ThreadPoolExecutor`. Use `concurrent.futures.wait(return_when=ALL_COMPLETED, timeout=10s)`. If speaker verification times out → **suppress text (fail-closed)** to prevent unauthorized speech injection.
7. **Performance:** ONNX model (~15MB) lazy-loaded in background thread on first use (not at startup). If model not yet loaded when recording ends, skip verification (accept). Embedding computation for 1s segment takes ~20ms on CPU via ONNX Runtime (already a dependency of faster-whisper). On low-end machines (4GB RAM), speaker lock can be disabled.

**New dependency:** `wespeaker-onnx` or custom ONNX speaker encoder model (NO PyTorch — see dependency audit)
- `resemblyzer` REJECTED: pulls PyTorch (~200MB), unmaintained 2.5 years, conflicts with webrtcvad-wheels
- Alternative: ONNX-based speaker encoder via `onnxruntime` (shared with faster-whisper)

**Files:**
- Create: `src/speaker_lock.py` — enrollment, DPAPI-encrypted storage, ONNX verification
- Modify: `src/engine.py` → `src/pipeline.py` — parallel speaker verification via ThreadPoolExecutor
- Modify: `src/ui/pages/settings_speaker.py` — "Register Voice" button, enable/disable toggle
- Modify: `src/config.py` — `speaker_lock.enabled`, `speaker_lock.cosine_threshold`, `speaker_lock.accept_threshold`, `speaker_lock.reject_threshold`

---

### 2.7 Context-Aware Formatting & Per-App Scripts

**Problem:** Same normalization style regardless of target app. Formal text in Slack, casual text in email.

**Design (updated 2026-03-28 — aligned with mockup):**

Instead of a flat `APP_STYLES` dict, the system uses **Scripts** — reusable instruction profiles assigned to apps.

**Built-in presets (read-only):**
| Script | Style | Description |
|--------|-------|-------------|
| Messenger | Informal | No caps at start, minimal punctuation, emoji-friendly |
| Email | Formal | Proper punctuation, greeting and signature preserved |
| Code Editor | Technical | English only, camelCase/snake_case preserved |
| Document | Formal | Full sentences, paragraph breaks on long pauses |

**Custom scripts:** User can create own scripts (e.g., "My Slack Rules: all lowercase, no periods, short sentences"). Stored in SQLite.

**App Rules:** Map detected apps to scripts:
```
slack.exe    → Messenger (or custom "My Slack Rules")
code.exe     → Code Editor
outlook.exe  → Email
default      → (no script, use global normalization settings)
```

**Context sources for LLM prompt (ordered by value/cost):**
1. **App name** (exe) — always available, sanitized (alphanumeric + dots, max 50 chars)
2. **Window title** — available but UNTRUSTED. Sanitized, truncated to 100 chars. Used for topic hints, NOT sent raw to LLM.
3. **Last 3 dictations** — from History DB (`SELECT normalized_text FROM history WHERE app = ? ORDER BY timestamp DESC LIMIT 3`). Gives conversation/topic context.
4. **Dictionary terms subset** — fuzzy-matched from raw_text, sent as terminology hints.

**Security:** Window titles are UNTRUSTED input — sanitized before any use. Process name sanitized (alphanumeric + dots only, max 50 chars). Clipboard content NEVER read for context (privacy).

**LLM system prompt assembly (by `prompt_builder.py`):**
```
[Base rules from Normalization Features toggles]
if punctuation ON → "Add proper punctuation."
if grammar ON     → "Fix grammar errors."
if capitalize ON  → "Capitalize sentences."

[Per-app script]
"Style: Messenger — informal, no caps, minimal punctuation"

[Context]
"App: slack.exe"
"Window: Slack — #dev-backend" (sanitized)

[Recent dictations]
"Recent context in this app:
- давай замержим цей пр після рев'ю
- я пушнув фікс в дев бранч"

[Dictionary terms — context-dependent only]
"Use these terms when appropriate: PR (pull request), бранч → branch (git)"
```

**Files:**
- Create: `src/app_context.py` — detect active app (full path), resolve script, sanitize
- Create: `src/prompt_builder.py` — assemble LLM system prompt from toggles + script + context + dict
- Create: `src/scripts_store.py` — SQLite CRUD for custom scripts, preset scripts
- Modify: `src/normalizer.py` — accept assembled prompt from prompt_builder
- Modify: `src/pipeline.py` — capture app context at recording start, query history for recent dictations
- Modify: `src/config.py` — `app_rules` dict (app → script_id)

---

### 2.8 Multi-App Text Injection Adaptation

**Problem:** Single injection method doesn't work well in all apps.

**Design:**
- Per-app injection profile:
  ```python
  INJECTION_PROFILES = {
      "code.exe": {"method": "clipboard", "delay_ms": 0},
      "cursor.exe": {"method": "clipboard", "delay_ms": 0},
      "slack.exe": {"method": "clipboard", "delay_ms": 0},
      "discord.exe": {"method": "clipboard", "delay_ms": 0},
      "cmd.exe": {"method": "clipboard_sanitized", "delay_ms": 0},
      "powershell.exe": {"method": "clipboard_sanitized", "delay_ms": 0},
      "default": {"method": "keyboard_sim", "delay_ms": 5},
  }
  ```
- **Injection methods:**
  - `keyboard_sim` (default): simulate key-by-key input via `pynput` (existing `_type_text`). Works in most apps but slow for long text and may fail in some controls.
  - `clipboard`: save clipboard → copy text → Ctrl+V → restore clipboard. Fast, reliable in editors/messengers.
  - `clipboard_sanitized` (for terminals): sanitize text by stripping shell metacharacters (`|`, `&`, `;`, backticks, `$()`, newlines→spaces) before clipboard paste. **No bracketed-paste** — older `cmd.exe` does not support it. Show confirmation dialog for multi-line text in terminal targets.
- **Auto-fallback mechanism:**
  1. After `keyboard_sim` injection, wait 50ms, then read the target control's text via `win32gui.GetWindowText()` (own window only — no UIA enumeration of other windows).
  2. If the control text doesn't contain the injected text (or control is unreadable) → retry with `clipboard` method.
  3. Fallback limited to 1 retry to avoid loops. Per-app config option to disable auto-fallback.

**Files:**
- Modify: `src/text_injector.py` — per-app profiles, sanitized paste, auto-fallback
- Create: `src/app_context.py` — (shared with 2.7) active app detection
- Modify: `src/config.py` — `injection_profiles` dict (modeled as dataclass)

---

### 2.9 Text Replacements (Voice Macros)

**Problem:** Users repeatedly dictate same emails, URLs, addresses.

**Design:**
- Replacement table: `trigger phrase` → `replacement text`
- Applied after STT, before normalization
- **Matching:** Substring search within the full transcript. Scan the transcript for each trigger phrase using case-insensitive, whitespace-normalized comparison. **Fuzzy tolerance scaled by trigger length:**
  - Trigger < 5 chars → exact match only (Levenshtein 0)
  - Trigger 5-10 chars → Levenshtein distance ≤ 1
  - Trigger 11+ chars → Levenshtein distance ≤ 2
  - Per-replacement "strict match" option available
  - Use `rapidfuzz` library for performance (O(n*m) with short-circuit)
- When a trigger is found within the transcript, only the matched substring is replaced — surrounding text is preserved. Example: trigger "my email", transcript "check my email address" → "check dmitry@example.com address"
- **Storage:** `replacements` table in `history.db` (SQLite) — consolidated with history storage, no separate YAML file. DPAPI-encrypted for PII protection (see Section 8).
- UI: table in Settings with Add/Edit/Delete buttons (like Aqua Voice Replacements page)
- **Security:** Warn users in UI that replacement values are stored locally. Option to mark specific replacements as "sensitive" (DPAPI-encrypted values column).

**Files:**
- Create: `src/replacements.py` — SQLite CRUD, match with rapidfuzz, apply
- Modify: `src/engine.py` → `src/pipeline.py` — apply replacements after STT, before normalization
- Modify: `src/ui/pages/settings_replacements.py` — Replacements page with CRUD table

**New dependency:** `rapidfuzz`

---

### 2.10 Dictation History

**Problem:** No way to review or re-use past dictations.

**Design:**
- SQLite database: `%APPDATA%/AIPolyglotKit/history.db`
- **Encryption:** Sensitive columns (`raw_text`, `normalized_text`) encrypted with DPAPI before insertion (see Section 8)
- Table: `dictations(id, timestamp, raw_text_enc, normalized_text_enc, duration_s, language, app_name, word_count)`
- Each completed dictation → auto-save to history
- **Sensitive mode:** Toggle in tray menu — pauses history recording (for password entry, confidential dictation)
- Auto-exclude entries where `app_name` matches known password managers (1Password, KeePass, LastPass, Bitwarden)
- UI: History page in Settings
  - List view: timestamp, preview (first 50 chars), duration, app
  - Search: full-text search across raw and normalized text (decrypted in memory)
  - Actions: Copy, Re-paste (insert at cursor), Delete
- Retention: configurable, default 90 days, max 10000 entries. **Purge on every startup**, not lazy.

**Files:**
- Create: `src/history.py` — SQLite CRUD, DPAPI encrypt/decrypt, search, cleanup
- Modify: `src/engine.py` → `src/pipeline.py` — save to history after normalization
- Modify: `src/ui/pages/settings_history.py` — History page
- Modify: `src/config.py` — `history.enabled`, `history.retention_days`
- Modify: `src/tray_app.py` — "Sensitive mode" toggle in tray menu

---

### 2.11 Dictionary

**Problem:** `known_terms` exists in config but no UI to manage it. Terms need context-awareness.

**Design (updated 2026-03-28):**

Dictionary stores domain-specific terms with two types:

| Type | Example | Processing | Tokens |
|------|---------|-----------|--------|
| **Exact** | пайтон→Python, жс→JS | Local post-check (regex) | 0 |
| **Context** | замок (lock vs castle), ключ (key vs key) | Sent to LLM as candidates | ~5 per term |

- **Exact terms:** Unambiguous replacements. Applied locally after LLM normalization (post-check). No LLM tokens consumed. Auto-learned terms default to this type.
- **Context terms:** Ambiguous, require LLM to decide based on surrounding text. Fuzzy-matched against raw_text, matched candidates included in LLM prompt as terminology hints.

**UI (aligned with mockup):**
- Statistics card: Total terms / Auto-learned / Added manually
- Add Term: input field with type selector (Exact/Context)
- Search: filter + results with manual/auto badges
- Import / Export: txt (one word per line) or JSON

**Storage:** `dictionary` table in `history.db` (SQLite):
```sql
CREATE TABLE dictionary (
    id INTEGER PRIMARY KEY,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    term_type TEXT DEFAULT 'exact',  -- 'exact' or 'context'
    origin TEXT DEFAULT 'manual',     -- 'manual' or 'auto'
    hit_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Pipeline integration:**
1. **Pre-STT:** All terms injected into Whisper `prompt` parameter (helps recognition)
2. **Pre-LLM:** Context terms fuzzy-matched against raw_text → matched candidates sent in LLM prompt
3. **Post-LLM:** Exact terms applied as local string replacement on normalized_text

**Files:**
- Create: `src/dictionary.py` — SQLite CRUD, fuzzy match, import/export
- Modify: `src/prompt_builder.py` — inject context terms into LLM prompt
- Modify: `src/pipeline.py` — post-LLM exact term replacement
- Modify: `src/connectors/*.py` — inject all terms into STT prompt parameter

---

### 2.12 Per-App Instructions (Scripts)

**Problem:** Normalization prompt customization only via config.yaml. No per-app differentiation.

**Design (updated 2026-03-28 — replaces freeform textarea with scripts system):**

See Section 2.7 for full script system design. This section covers the UI page.

**UI page "Per-App" (3 cards):**
1. **Presets** — 4 built-in read-only scripts (Messenger, Email, Code Editor, Document). Shown with icons and descriptions.
2. **App Rules** — Map detected apps to scripts. Each row: app name + script dropdown + Edit/Delete. Button "Add App Rule" opens modal with app selector + script selector.
3. **Custom Scripts** — User-created scripts. Each shown with name, description preview, Edit/Delete buttons. "New Script" opens editor modal.

**Script editor modal:**
- Script name (text input)
- Instructions (textarea, monospace font, 500 char limit)
- Format: one rule per line, sent as LLM system prompt
- Example: "all lowercase, never capitalize\nno periods\nkeep sentences short"

**Storage:** `scripts` table in `history.db`:
```sql
CREATE TABLE scripts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    is_builtin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE app_rules (
    id INTEGER PRIMARY KEY,
    app_name TEXT NOT NULL UNIQUE,
    script_id INTEGER REFERENCES scripts(id)
);
```

**Security:** Character limit 500 chars per script. Changes logged in audit log.
- Storage: `config.yaml` under `normalization.custom_instructions`

**Files:**
- Create: `src/ui/pages/settings_instructions.py` — Custom Instructions text area
- Modify: `src/config.py` — add `custom_instructions` field (max 500 chars)
- Modify: `src/normalizer.py` — append custom instructions to prompt

---

### 2.13 Mute Background Audio

**Problem:** Media playing (YouTube, Spotify) interferes with recording.

**Design:**
- On recording start → **gradually** lower volume of all non-APK audio sessions to 10% (fade over 500ms)
- On recording end → gradually restore volumes (fade over 500ms)
- Only mute sessions that are actively playing (check session state before muting)
- Uses `pycaw` (already a dependency for hotplug): `ISimpleAudioVolume.SetMasterVolume()`
- Configurable: `audio.mute_background: true/false`
- Per-app exclusions from muting (e.g., keep call apps audible)
- Exclude own app PID from muting

**Files:**
- Create: `src/audio_muter.py` — gradual mute/unmute using pycaw sessions
- Modify: `src/engine.py` → `src/pipeline.py` — call mute on start, unmute on stop
- Modify: `src/config.py` — `audio.mute_background`, `audio.mute_exclusions`
- Modify: `src/ui/pages/settings_audio.py` — checkbox toggle + exclusions list

---

### 2.14 Stats UI

**Problem:** Telemetry data collected but not shown to user.

**Design:**
- Stats page (like Aqua Voice Stats): total words, sessions, time saved, streak
- Data source: existing `TelemetryCollector` + new counters
- Metrics: total_words, total_sessions, total_duration_s, words_today, streak_days
- Simple card layout with big numbers
- **Storage:** Persistent counters in SQLite (reuse `history.db`)
- **Privacy:** New stats counters are local-only — never sent to Amplitude. Existing telemetry payload should be audited.

**Files:**
- Modify: `src/telemetry.py` — add persistent counters in SQLite (`history.db`)
- Create: `src/ui/pages/settings_stats.py` — Stats page with card layout

---

### 2.15 Offline STT Fallback

**Problem:** No STT when internet is down.

**Design:**
- `faster-whisper` as **optional** offline STT provider (CTranslate2 backend)
- **Optional dependency:** `pip install ai-polyglot-kit[offline]`. Not a hard requirement for all users.
- Model: `medium` int8 quantization (~750MB, downloaded on first use via HuggingFace Hub)
- **Model download UX:**
  - Dedicated download dialog with progress bar in Settings
  - Pre-flight disk space check (require 2GB free)
  - Resume support (HuggingFace supports range requests)
  - SHA-256 checksum verification after download
  - Cancel button
- **Model integrity:** Verify checksum on each load, not just after download. Alert user if model file modified.
- Registered as provider slot: `provider: "offline"`, `model: "medium"`
- **Mode selection:** Per-session, not per-chunk:
  - At session start: probe online STT endpoint (HEAD request, 2s timeout)
  - If online → stay online for entire session
  - If offline → use offline for entire session
  - Between sessions → re-probe
  - Tray icon indicator: green = online, yellow = offline
- Config: `stt_mode: auto | online | offline`
  - `auto`: per-session probe, fallback to offline
  - `online`: online only (current behavior)
  - `offline`: offline only
- Warning in UI: "Offline mode: reduced accuracy for multilingual dictation"
- **Offline normalization:** Simple rule-based cleanup only (capitalize first letter, fix spacing around punctuation, apply text replacements). No LLM call.

**New dependency (optional):** `faster-whisper==1.2.1` + `ctranslate2==4.5.0` (pinned for compatibility)

**Files:**
- Create: `src/connectors/offline_stt.py` — faster-whisper connector with model integrity check
- Modify: `src/provider_manager.py` — offline provider support, per-session fallback with probe
- Modify: `src/config.py` — `stt_mode` field
- Create: `src/ui/pages/settings_offline.py` — offline mode selector, model download dialog
- Modify: `src/tray_app.py` — online/offline status indicator

---

## 3. UI Redesign — Aqua Voice Style

### 3.0 UI Technology

**Decision:** Settings UI rendered via **PyWebView** (Edge WebView2 on Windows). Recording overlay remains **tkinter**.

**Rationale:**
- Aqua Voice uses Electron for the same reason — web tech enables polished UI (CSS animations, gradients, blur, shimmer effects)
- PyWebView reuses Edge WebView2 already installed on Win10/11 — adds ~2-3MB vs Electron's 150MB
- HTML/CSS/JS mockups (`docs/mockups/settings-ui.html`) work as-is in PyWebView
- Cross-platform ready: WebKit on macOS, WebKitGTK on Linux
- Recording overlay stays tkinter: small, no effects needed, must be always-on-top transparent window

**PyWebView integration:**
- `webview.create_window()` for Settings, loads `src/ui/web/index.html`
- Python↔JS bridge via `window.pywebview.api` (expose config read/write, audio test, etc.)
- Settings pages are SPA routes in JS, no server needed
- Window size: 900×640, resizable, dark title bar via `webview.create_window(background_color='#1a1a2e')`

**Files:**
- `src/ui/web/` — HTML/CSS/JS for Settings SPA
- `src/ui/web_bridge.py` — Python API exposed to JS via PyWebView
- `src/ui/overlay.py` — tkinter recording overlay (unchanged)
- `src/ui/settings_window.py` — PyWebView launcher

### 3.1 Design System

**Color Palette (Dark theme — primary):**
| Token | Value | Usage |
|-------|-------|-------|
| `bg-primary` | `#1a1a2e` | Main window background |
| `bg-secondary` | `#16213e` | Sidebar, sections |
| `bg-card` | `#0f3460` | Cards, panels |
| `bg-input` | `#1a1a3e` | Input fields |
| `fg-primary` | `#ffffff` | Primary text |
| `fg-secondary` | `#9e9e9e` | Secondary text, hints |
| `accent` | `#85600a` | Primary actions — dark gold |
| `accent-hover` | `#a07010` | Hover state |
| `accent-shimmer` | linear-gradient gold sweep | Upgrade button, toggles ON |
| `accent-secondary` | `#533483` | Secondary accent |
| `success` | `#4CAF50` | Connected, success states |
| `warning` | `#FF9800` | Warnings, progress |
| `error` | `#F44336` | Errors, destructive actions |
| `border` | `#2a2a4a` | Subtle borders |

**Color Palette (Light theme):**
| Token | Value | Usage |
|-------|-------|-------|
| `bg-primary` | `#f8f9fa` | Main background |
| `bg-secondary` | `#ffffff` | Cards |
| `bg-card` | `#ffffff` | Panels |
| `fg-primary` | `#1a1a1a` | Primary text |
| `fg-secondary` | `#555555` | Secondary text |
| `accent` | `#007AFF` | Primary actions |

**Typography:**
- Font: "Segoe UI" (Windows system font)
- Weights: 400 (body), 500 (labels), 600 (headings)
- Sizes: 12px (body), 14px (section heads), 18px (page title), 24px (stats)
- Line height: 1.5

**Spacing:** 8px grid (4/8/12/16/24/32)

**Components:**
- Rounded corners: 8px (cards), 4px (inputs), 16px (toggles)
- Shadows: subtle `0 2px 8px rgba(0,0,0,0.15)` for cards
- Toggle switches instead of checkboxes where boolean
- Clean separators between sections (1px border-color)
- Gold shimmer animation on Upgrade button and active toggle switches
- Primary buttons: static gold gradient at randomized angles

**Mockups:**
- `docs/mockups/settings-ui.html` — full-fidelity PyWebView target (gold shimmer effects)
- `docs/mockups/recording-overlay.html` — tkinter overlay states

### 3.2 Settings Window Layout

Sidebar navigation (like Aqua). Rendered as SPA in PyWebView. Each page is a JS route.
Sidebar organized into 3 sections. STT merged into Dictation page. LLM renamed to Normalization.

```
┌─────────────────────────────────────────────┐
│  AI Polyglot Kit — Settings         [X]     │
├──────────┬──────────────────────────────────┤
│          │                                  │
│ SETTINGS │  [Selected page content]         │
│ General  │                                  │
│ Audio    │                                  │
│ Dictation│  (STT providers + recognition)   │
│ Normaliz.│  (LLM providers + features)      │
│ Translate│  (translation + extension)       │
│          │                                  │
│ CONTENT  │                                  │
│ Dictionary│                                 │
│ Replace- │                                  │
│  ments   │                                  │
│ Per-App  │  (presets + scripts, was Instr.)  │
│ History  │                                  │
│          │                                  │
│ PERSONAL │  (was Advanced)                  │
│ Speaker  │  (was Speaker Lock)              │
│  Lock    │                                  │
│ Offline  │                                  │
│ Network  │                                  │
│ Stats    │                                  │
│ Account  │  (data management, danger zone)  │
│          │                                  │
│          │  v6.0.0-beta.1  ↑v6.1.0 available│
│          │                 [Cancel] [Save]  │
└──────────┴──────────────────────────────────┘
```

**Changes from v5:**
- "STT" page removed — merged into "Dictation" (combined STT providers + recognition settings)
- "LLM" renamed to "Normalization" (clearer for non-technical users)
- "Instructions" renamed to "Per-App" (presets + custom scripts system)
- "Advanced" section renamed to "Personal"
- "Upgrade to Pro" button removed
- API Keys removed from Account — distributed to provider cards on Dictation/Normalization/Translate pages
- Footer shows version + update availability badge
- Each provider page has 3 prioritized provider slots with fallback

### 3.3 Recording Overlay (tkinter)
- Compact floating pill (like Aqua Voice first screenshot)
- Waveform visualization (existing, style update)
- Show active mic name and language
- Semi-transparent solid dark background (`wm_attributes('-alpha', 0.85)`)
- Online/offline status indicator (green dot = online, yellow = offline)
- Stays on tkinter — always-on-top transparent overlay, no web effects needed

---

## 4. Architectural Changes

### 4.1 Engine Decomposition & Full Pipeline

**Problem:** `engine.py` (631 lines, ~15 state vars) is becoming a god object with all new features.

**Solution:** Extract per-recording lifecycle into `Pipeline`/`SessionCoordinator`:
- `src/engine.py` — thin state machine (IDLE→RECORDING→PROCESSING→TYPING→IDLE), delegates to pipeline
- `src/pipeline.py` — per-recording session orchestrator
- `src/prompt_builder.py` — assembles LLM system prompt from all context sources
- `src/feedback_handler.py` — extracted feedback capture logic (HWND guard, text grab, LLM re-normalization)

**Full pipeline (updated 2026-03-28):**

```
┌─────────────────────────────────────────────────────────────┐
│ STAGE 1: AUDIO CAPTURE (local, 0 tokens)                    │
│                                                             │
│ Microphone → PyAudio callback (30ms frames)                 │
│   ├─ AGC (if ON) — normalize amplitude to target RMS        │
│   ├─ RNNoise (if noise suppression ON) — neural denoise     │
│   ├─ VAD — voice activity detection (sensitivity slider)    │
│   ├─ Speaker Lock (if ON) — ONNX voice verify → accept/reject│
│   └─ Mute background audio (if ON) — lower other apps       │
│                                                             │
│ Output: audio chunks (voice segments only)                   │
├─────────────────────────────────────────────────────────────┤
│ STAGE 2: STT — Speech-to-Text (API, tokens consumed)        │
│                                                             │
│ 3 providers in priority order (fallback on failure/quota):   │
│   #1 AssemblyAI → #2 Deepgram → #3 OpenAI                  │
│                                                             │
│ STT prompt parameter includes:                               │
│   - All dictionary terms (helps Whisper recognize them)      │
│   - Recent dictation context (last 3, for consistent output) │
│                                                             │
│ Output: raw_text                                             │
├─────────────────────────────────────────────────────────────┤
│ STAGE 3: REPLACEMENTS — Voice Macros (local, 0 tokens)      │
│                                                             │
│ raw_text → fuzzy match against replacement triggers          │
│   - Levenshtein tolerance scaled by phrase length            │
│   - Substring match within full transcript                   │
│   - DPAPI-encrypted sensitive replacements                   │
│                                                             │
│ Output: replaced_text                                        │
├─────────────────────────────────────────────────────────────┤
│ STAGE 4: LLM NORMALIZATION (API, tokens consumed)            │
│                                                             │
│ 3 providers in priority order (fallback):                    │
│   #1 Groq → #2 OpenAI → #3 Anthropic                       │
│                                                             │
│ System prompt assembled by prompt_builder.py:                │
│   ┌─ Base rules (from Normalization Features toggles):      │
│   │    if punctuation ON  → "Add proper punctuation."       │
│   │    if grammar ON      → "Fix grammar errors."           │
│   │    if capitalize ON   → "Capitalize sentences."         │
│   │    if terminology ON  → (dict terms injected below)     │
│   │    if numbers ON      → (handled locally in Stage 5)    │
│   │                                                         │
│   ├─ Per-app script (from App Rules):                       │
│   │    "Style: Messenger — informal, no caps, minimal punct"│
│   │                                                         │
│   ├─ App context:                                           │
│   │    "App: slack.exe"                                     │
│   │    "Window: Slack — #dev-backend" (sanitized)           │
│   │                                                         │
│   ├─ Recent dictations (last 3 from History DB):            │
│   │    Provides conversation context for term disambiguation │
│   │                                                         │
│   └─ Dictionary terms (context-type, fuzzy-matched):        │
│        "Use these terms: PR (pull request), branch (git)"   │
│                                                             │
│ If ALL normalization toggles OFF → skip LLM entirely        │
│                                                             │
│ Output: normalized_text                                      │
├─────────────────────────────────────────────────────────────┤
│ STAGE 5: LOCAL POST-PROCESSING (local, 0 tokens)            │
│                                                             │
│ a) Number formatting (if ON):                                │
│    "двадцять три" → "23", "п'ятсот доларів" → "$500"        │
│    Regex/rule-based, no LLM needed                           │
│                                                             │
│ b) Dictionary exact terms (post-check):                      │
│    "пайтон" → "Python", "жс" → "JS" (unambiguous only)     │
│    Verify LLM didn't break known exact terms                 │
│                                                             │
│ Output: final_text                                           │
├─────────────────────────────────────────────────────────────┤
│ STAGE 6: TEXT INJECTION                                      │
│                                                             │
│ Detect app + field type → choose injection method:           │
│   keyboard_sim (default) / clipboard / clipboard_sanitized   │
│ Auto-fallback: keyboard_sim fails → retry clipboard          │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ STAGE 7: HISTORY & TELEMETRY (async, SQLite)                 │
│                                                             │
│ Save to history.db:                                          │
│   raw_text, normalized_text (DPAPI encrypted)                │
│   app_name, window_title, duration_s, word_count             │
│   provider_used (stt + llm), tokens_consumed, confidence     │
│   timestamp, language                                        │
│                                                             │
│ Update stats counters:                                       │
│   total_words, total_sessions, streak_days                   │
│   per-provider token usage (for Stats page table)            │
│                                                             │
│ Feed Adaptive Correction Engine (if feedback received):      │
│   Store triad: raw_stt → normalized → user_corrected         │
│   Auto-classify error source (STT vs LLM)                    │
└─────────────────────────────────────────────────────────────┘
```

**Token budget per request (typical):**
| Component | Tokens |
|-----------|--------|
| Base rules + toggles | ~50 |
| Per-app script | ~30 |
| App context (name + window) | ~20 |
| Last 3 dictations | ~60 |
| Dictionary terms (5-10 candidates) | ~40 |
| Input text | ~30 |
| Output text | ~30 |
| **Total per request** | **~260** |

### 4.2 Settings UI (PyWebView + HTML/CSS/JS)

**Problem:** `settings_ui.py` (822 lines) heading to 1500+ with 12 sidebar pages. Tkinter cannot achieve the target visual quality (Aqua Voice style).

**Solution:** PyWebView SPA + Python bridge:
```
src/ui/
  __init__.py
  settings_window.py          # PyWebView launcher (webview.create_window)
  web_bridge.py               # Python API exposed to JS (config CRUD, audio test, etc.)
  overlay.py                  # tkinter recording overlay (unchanged)
  web/
    index.html                # SPA entry point
    css/
      styles.css              # design system (tokens, components, shimmer effects)
    js/
      app.js                  # router, page switching, bridge calls
      pages/
        general.js            # theme, language, startup, hotkeys
        audio.js              # mic, noise suppression, test, mute, AGC
        dictation.js          # STT providers (3 slots), recognition mode, languages
        normalization.js      # LLM providers (3 slots), features toggles, feedback
        translate.js          # translation providers (3 slots), extension, security
        dictionary.js         # term CRUD, search, import/export, stats
        replacements.js       # trigger → text CRUD, fuzzy/strict
        per-app.js            # presets, app rules, custom scripts
        history.js            # history list, search, filters
        speaker.js            # speaker lock, voice enrollment
        offline.js            # offline mode, model download, system detection
        network.js            # proxy, timeouts, HTTP server
        stats.js              # stats cards, token usage table
        account.js            # version, data management, danger zone
```

**Python↔JS bridge API** (exposed via `window.pywebview.api`):
- `get_config() -> dict` — read current config
- `save_config(data: dict) -> bool` — validate + save
- `get_audio_devices() -> list[dict]` — enumerate microphones
- `test_audio(device_id: str)` — play test recording
- `get_history(offset, limit, query, filters) -> list[dict]` — paginated history with filters
- `delete_history(ids: list[int])` — delete entries
- `get_stats() -> dict` — usage statistics + per-provider token usage
- `get_dictionary(query) -> list[dict]` — search dictionary terms
- `add_dictionary_term(source, target, type) -> dict` — add term (exact/context)
- `get_scripts() -> list[dict]` — list all scripts (builtin + custom)
- `save_script(id, name, body) -> dict` — create/update custom script
- `get_app_rules() -> list[dict]` — list app → script mappings
- `save_app_rule(app_name, script_id) -> dict` — create/update app rule
- `get_replacements() -> list[dict]` — list voice macros
- `find_browsers() -> list[dict]` — detect installed browsers for extension
- `install_extension(browser_id) -> dict` — trigger extension install flow
- `enroll_speaker()` — start voice enrollment flow
- `download_model(model_id: str)` — trigger offline model download
- `check_update() -> dict` — check for app updates
- `get_token_usage(period) -> dict` — per-provider token consumption

### 4.3 Config Validation

**Problem:** Current `_apply_dict()` doesn't handle nested dicts (`app_styles`, `injection_profiles`).

**Solution:** Model complex config sections as proper nested dataclasses with `from_dict()` class methods. Add round-trip tests for every config shape.

### 4.4 Audio Pipeline Thread Architecture

```
PyAudio callback thread       AudioPreprocessor thread       Main pipeline
┌─────────────────┐          ┌──────────────────────┐      ┌──────────────────┐
│ raw_queue.put()  │──raw──→ │ RNNoise denoise      │─proc→│ ChunkManager     │
│ (< 1ms budget)   │  queue  │ Adaptive AGC         │ queue│ VAD split        │
│                  │          │ frame drop monitor   │      │ Speaker Lock     │
│                  │          │ Mute background apps │      │ STT (3 providers)│
└─────────────────┘          └──────────────────────┘      │ Replacements     │
                                                           │ LLM (3 providers)│
                                                           │ Post-processing  │
                                                           │ Inject + History │
                                                           └──────────────────┘
```

**STT providers (ordered by quality):**
1. AssemblyAI (Universal-2) — best accuracy, 100h free
2. Deepgram (Nova-2) — low latency streaming, $200 credit
3. OpenAI (Whisper V3) — best multilingual, $5 credit
4. Google Cloud STT (Chirp 2.0) — enterprise
5. Groq (Whisper V3 Turbo) — free with rate limits, fastest

**LLM providers:** Groq, OpenAI, Anthropic, OpenRouter
**Translation providers:** Groq, OpenAI, Anthropic, Google Translate, DeepL

---

## 5. Security

### 5.1 Data Encryption at Rest (DPAPI)

All sensitive data encrypted using Windows DPAPI (`CryptProtectData`/`CryptUnprotectData`), which binds decryption to the Windows user session.

| Data | Location | Encryption |
|------|----------|------------|
| Voice profile | `voice_profile.npy` | DPAPI (biometric) |
| History (raw_text, normalized_text) | `history.db` columns | DPAPI per-value |
| Replacements (marked sensitive) | `history.db` | DPAPI per-value |
| API keys | `config.yaml` → migrate to Credential Manager | Windows Credential Manager (`CredRead`/`CredWrite`) |

**Implementation:** `src/crypto.py` — DPAPI wrapper via `ctypes` (`crypt32.dll`), encrypt/decrypt helpers.

### 5.2 LLM Prompt Injection Prevention

- Process names sanitized: alphanumeric + dots only, max 50 chars
- Window titles NEVER included in LLM prompts
- Custom instructions: max 500 chars, changes logged
- Chrome URL domain sent via extension (not window title)

### 5.3 Terminal Injection Safety

- Shell metacharacters stripped for terminal targets (`|`, `&`, `;`, `` ` ``, `$()`, newlines)
- Confirmation dialog for multi-line text in terminal processes
- No bracketed-paste (unreliable in older terminals)

### 5.4 Chrome Extension Authentication

- Shared secret generated at install time
- Stored in `chrome.storage.local` (extension) and DPAPI-encrypted config (backend)
- All HTTP requests between extension and backend require secret in header
- HTTP server bound to `127.0.0.1` only
- CORS headers restrict to extension origin

### 5.5 Audit Log

Append-only log at `%APPDATA%/AIPolyglotKit/audit.log`:
- Voice profile enrollment/deletion
- Custom instruction changes
- Replacement rule CRUD
- Speaker lock enable/disable
- Online/offline mode switches
- Config file modifications

**File:** Create `src/audit.py` — append-only logger with restrictive NTFS ACLs.

### 5.6 Offline Model Security

- SHA-256 checksum verification on download AND on each load
- Expected hash stored in application code
- HTTPS-only download from HuggingFace Hub
- Disk space check before download (require 2GB free)
- Alert user if model file modified externally

---

## 5.7 Adaptive Correction Engine

**Problem:** Current pipeline treats each recognition as independent. User corrections (double-tap feedback) are stored as flat word→word pairs in `user_profile.md` with no semantic context. The same word can be correct in one context and wrong in another ("pie chart" is fine, "pie audio" should be "PyAudio"). Dictionary, STT vocabulary hints, and LLM instructions are all manually maintained and disconnected.

**Core concept:** Replace flat user_profile.md with a **triad-based correction store**. Every user correction captures the full pipeline output (raw STT → LLM normalized → user corrected) plus context. The system auto-classifies where the error occurred (STT vs LLM) and dynamically generates prompts from accumulated corrections.

**Triads:**
```
raw_stt:     "use pie audio for recording"
normalized:  "Use pie audio for recording."
corrected:   "Use PyAudio for recording."
→ error_source: stt (Whisper misheard), diff_tokens: [{"pos":1, "was":"pie audio", "now":"PyAudio"}]
→ context: app=code.exe, technical discussion
```

**Three storage approaches to evaluate (design spike before implementation):**

| Approach | Pros | Cons | Fit |
|----------|------|------|-----|
| **A. SQLite + Python cosine** | Zero new deps, simple, proven | Slow similarity search at scale (>10K) | Good for v6.0 MVP |
| **B. SQLite + sqlite-vss** | Fast vector search, single file | C extension, build complexity on Windows | Good if A is too slow |
| **C. LanceDB (embedded)** | Purpose-built vector DB, fast, no server | New dependency (~20MB), less mature | Best if we outgrow SQLite |

**Decision:** Design spike in Phase 5.7 to benchmark all three with realistic data (1000+ triads). Pick simplest that meets <50ms query time.

**Auto-classification of errors:**
- Diff `raw_stt` vs `corrected` → STT errors (Whisper misheard)
- Diff `normalized` vs `corrected` → LLM errors (formatter broke it)
- If both differ → STT error (LLM couldn't fix what it didn't know)

**Dynamic prompt generation:**
- **STT prompt:** Before each Whisper call, query correction store for vocabulary relevant to current app + recent context. Inject as Whisper `prompt` parameter.
- **LLM prompt:** Before each normalization, query similar past corrections as few-shot examples. Inject into system prompt alongside user's formatting instructions.
- **Fast path:** If correction has high confidence (≥0.85) and ≥3 hits, apply auto-correction without LLM call.

**What replaces what:**
- `user_profile.md` → `corrections` table in SQLite (triads with context)
- Manual Dictionary → auto-populated from STT corrections + manual additions
- Static STT `previous_text` → dynamic prompt from correction store + dictionary + app context
- Generic LLM system prompt → base prompt + few-shot examples from similar corrections

**Embedding model:** Reuse ONNX speaker encoder infrastructure. Small sentence embedding model (~15MB ONNX, e.g., all-MiniLM-L6-v2 quantized) for context similarity.

**Files:**
- Create: `src/correction_store.py` — SQLite storage, triad CRUD, vector search
- Create: `src/prompt_builder.py` — dynamic STT/LLM prompt generation from correction store
- Create: `src/error_classifier.py` — auto-classify STT vs LLM errors from triads
- Modify: `src/engine.py` — integrate correction store into feedback loop
- Modify: `src/normalizer.py` — accept dynamic few-shot examples in prompt
- Modify: `src/connectors/openai_stt.py` — accept dynamic vocabulary prompt
- Remove: `src/user_profile.py` → migrate data to correction_store on first launch

---

## 6. New Dependencies

| Package | Version | Purpose | Size | Risk |
|---------|---------|---------|------|------|
| `pycaw` | `>=20230407` | Windows Core Audio (hotplug + mute) | ~50KB | LOW |
| `pyrnnoise` | `==0.4.3` | RNNoise neural denoising | ~13MB | MEDIUM (pin, single maintainer) |
| `rapidfuzz` | `>=3.0` | Fast fuzzy matching for replacements | ~2MB | LOW |
| `faster-whisper` | `==1.2.1` | Offline STT (CTranslate2) — **OPTIONAL** | ~80MB + 750MB model | MEDIUM |
| `ctranslate2` | `==4.5.0` | Pinned for faster-whisper compat — **OPTIONAL** | ~11MB | MEDIUM |
| ONNX speaker encoder | TBD | Speaker embeddings (replaces resemblyzer) | ~15MB | LOW (uses onnxruntime) |

**REJECTED:** `resemblyzer` — PyTorch dependency (~200MB+), unmaintained 2.5 years, webrtcvad conflict.

---

## 7. Migration Plan

- v5.x → v6.0: config.yaml auto-migration for new fields (defaults for all new settings)
- No breaking changes to existing config
- API keys: one-time migration from config.yaml to Windows Credential Manager (old keys removed from YAML after migration)
- New SQLite database created on first launch (`history.db` — history + replacements + stats)
- Voice profile created when user first configures speaker lock (DPAPI-encrypted)
- Offline model downloaded only when user enables offline mode
- Existing `settings_ui.py` refactored into `src/ui/` package (Phase 0)

---

## 8. Testing Strategy

- Unit tests for each new module (noise_suppression, audio_preprocessor, speaker_lock, replacements, history, app_context, device_monitor, audio_muter, crypto, audit, pipeline, feedback_handler)
- Config round-trip tests for all new config shapes (nested dataclasses)
- Integration tests: hotkey flow, recording pipeline, injection per-app
- UI tests: pywinauto for automated widget validation
- Manual Windows VM testing after each module
- Analysis pipeline (ruff, mypy, bandit, etc.) after every iteration
- Security: bandit + pip-audit on expanded dependency tree before each release

---

## 9. Implementation Order

| Phase | Modules | Priority |
|-------|---------|----------|
| **0** | **Structural refactoring:** engine→pipeline decomposition, settings_ui→src/ui/ split, config validation, crypto.py, audit.py | **Critical** |
| 1 | Hotkey separation + reduced latency + cancel/paste-last | Critical |
| 2 | Device hotplug (pycaw) + settings persistence | Critical |
| 3 | Audio preprocessor thread + Adaptive AGC + RNNoise noise suppression | High |
| 4 | Mic test mode | High |
| **5** | **Adaptive Correction Engine — design spike:** benchmark 3 storage approaches (SQLite+Python cosine, SQLite+sqlite-vss, LanceDB), pick one. Design triad schema, error classifier, prompt builder interfaces. | **High** |
| 6 | **ACE implementation:** correction_store.py, error_classifier.py, prompt_builder.py, migrate user_profile.md → SQLite, integrate into engine.py feedback loop | High |
| 7 | UI redesign (Aqua style, sidebar navigation, PyWebView SPA) | High |
| 8 | Text replacements (SQLite) + Dictionary (auto-populated from ACE) + Formatting instructions UI | Medium |
| 9 | History (SQLite, DPAPI) + Stats UI | Medium |
| 10 | Context-aware formatting + Multi-app injection + terminal safety | Medium |
| 11 | Chrome extension authentication (shared secret) | Medium |
| 12 | Mute background audio | Low |
| 13 | Speaker lock (ONNX encoder, fail-closed) | Low |
| 14 | Offline STT fallback (faster-whisper, optional dep) | Low |

"""Internationalization — UI string localization (UA/EN)."""

from __future__ import annotations

_STRINGS: dict[str, dict[str, str]] = {
    # ── Tray menu ────────────────────────────────────────────────
    "tray.ready": {
        "en": "Ready",
        "uk": "Готово",
    },
    "tray.recording": {
        "en": "Recording...",
        "uk": "Запис...",
    },
    "tray.processing": {
        "en": "Processing...",
        "uk": "Обробка...",
    },
    "tray.typing": {
        "en": "Typing...",
        "uk": "Введення...",
    },
    "tray.error": {
        "en": "Error",
        "uk": "Помилка",
    },
    "tray.settings": {
        "en": "Settings",
        "uk": "Налаштування",
    },
    "tray.open_profile": {
        "en": "Open Profile",
        "uk": "Відкрити профіль",
    },
    "tray.open_logs": {
        "en": "Open Logs",
        "uk": "Відкрити логи",
    },
    "tray.update_install": {
        "en": "Install update v{version}",
        "uk": "Встановити оновлення v{version}",
    },
    "tray.update_check": {
        "en": "Check for updates",
        "uk": "Перевірити оновлення",
    },
    "tray.quit": {
        "en": "Quit",
        "uk": "Вихід",
    },
    "tray.title": {
        "en": "Groq Dictation",
        "uk": "Groq Dictation",
    },
    "tray.mic": {
        "en": "Mic",
        "uk": "Мік",
    },

    # ── Notifications ────────────────────────────────────────────
    "notify.no_speech": {
        "en": "No speech detected",
        "uk": "Мовлення не виявлено",
    },
    "notify.too_short": {
        "en": "Recording too short",
        "uk": "Запис занадто короткий",
    },
    "notify.api_error": {
        "en": "API error",
        "uk": "Помилка API",
    },
    "notify.feedback_ok": {
        "en": "Correction saved",
        "uk": "Виправлення збережено",
    },
    "notify.feedback_empty": {
        "en": "Could not read text",
        "uk": "Не вдалося прочитати текст",
    },
    "notify.feedback_same": {
        "en": "Text unchanged",
        "uk": "Текст не змінено",
    },
    "notify.update_available": {
        "en": "Update available: v{version}",
        "uk": "Доступне оновлення: v{version}",
    },
    "notify.already_running": {
        "en": "Groq Dictation is already running.",
        "uk": "Groq Dictation вже запущено.",
    },

    # ── Settings window ──────────────────────────────────────────
    "settings.title": {
        "en": "Groq Dictation — Settings",
        "uk": "Groq Dictation — Налаштування",
    },
    "settings.tab_api": {
        "en": "API",
        "uk": "API",
    },
    "settings.tab_audio": {
        "en": "Audio",
        "uk": "Аудіо",
    },
    "settings.tab_normalization": {
        "en": "Normalization",
        "uk": "Нормалізація",
    },
    "settings.tab_ui": {
        "en": "Interface",
        "uk": "Інтерфейс",
    },
    "settings.api_key": {
        "en": "API Key:",
        "uk": "API Ключ:",
    },
    "settings.api_hint": {
        "en": "1. Go to console.groq.com  2. Sign up / Log in  3. API Keys → Create  4. Copy and paste here",
        "uk": "1. Відкрийте console.groq.com  2. Зареєструйтесь  3. API Keys → Create  4. Скопіюйте сюди",
    },
    "settings.stt_model": {
        "en": "STT Model:",
        "uk": "STT Модель:",
    },
    "settings.llm_model": {
        "en": "LLM Model:",
        "uk": "LLM Модель:",
    },
    "settings.language": {
        "en": "Languages:",
        "uk": "Мови:",
    },
    "settings.language_hint": {
        "en": "Select none for auto-detect, or choose languages to restrict recognition",
        "uk": "Не обирайте жодної для автовизначення, або оберіть мови для обмеження розпізнавання",
    },
    "settings.hotkey": {
        "en": "Hotkey:",
        "uk": "Гаряча клавіша:",
    },
    "settings.mic_device": {
        "en": "Microphone:",
        "uk": "Мікрофон:",
    },
    "settings.normalization_enabled": {
        "en": "Enable normalization",
        "uk": "Увімкнути нормалізацію",
    },
    "settings.known_terms": {
        "en": "Known terms:",
        "uk": "Відомі терміни:",
    },
    "settings.save": {
        "en": "Save",
        "uk": "Зберегти",
    },
    "settings.cancel": {
        "en": "Cancel",
        "uk": "Скасувати",
    },
    "settings.saved_ok": {
        "en": "Settings saved. Restart to apply.",
        "uk": "Налаштування збережено. Перезапустіть для застосування.",
    },
    "settings.restart_prompt": {
        "en": "Settings saved. Restart now to apply changes?",
        "uk": "Налаштування збережено. Перезапустити зараз для застосування?",
    },
    "settings.ui_language": {
        "en": "UI Language:",
        "uk": "Мова інтерфейсу:",
    },
    "settings.sound_on_start": {
        "en": "Beep on recording start",
        "uk": "Звук на початку запису",
    },
    "settings.profile_path": {
        "en": "Profile:",
        "uk": "Профіль:",
    },
    "settings.tab_telemetry": {
        "en": "Telemetry",
        "uk": "Телеметрія",
    },
    "settings.telemetry_enabled": {
        "en": "Send anonymous statistics to improve speech recognition",
        "uk": "Надсилати анонімну статистику для покращення розпізнавання",
    },
    "settings.telemetry_hint": {
        "en": "Sent: session counts, latency, model names, hallucination rates, crash logs, and recognition triads (raw/normalized/edited text). No audio or API keys.",
        "uk": "Надсилається: кількість сесій, затримки, назви моделей, частота галюцинацій, логи збоїв та тріади розпізнавання (розпізнано/нормалізовано/виправлено). Без аудіо та API ключів.",
    },
    "settings.autostart": {
        "en": "Start with Windows",
        "uk": "Запускати з Windows",
    },
    "settings.show_key": {
        "en": "Show key",
        "uk": "Показати ключ",
    },
    "settings.mic_device": {
        "en": "Microphone:",
        "uk": "Мікрофон:",
    },
    "settings.mic_auto": {
        "en": "Auto (loudest)",
        "uk": "Авто (найгучніший)",
    },
    "settings.noise_filter": {
        "en": "Noise filter:",
        "uk": "Фільтр шуму:",
    },
    "settings.vad_0": {
        "en": "All sounds (noisy rooms)",
        "uk": "Усі звуки (шумні кімнати)",
    },
    "settings.vad_1": {
        "en": "Soft filter",
        "uk": "М'який фільтр",
    },
    "settings.vad_2": {
        "en": "Balanced (recommended)",
        "uk": "Збалансований (рекомендовано)",
    },
    "settings.vad_3": {
        "en": "Strict (only clear speech)",
        "uk": "Суворий (тільки чіткий голос)",
    },
    "settings.pause_to_split": {
        "en": "Pause to split:",
        "uk": "Пауза для розділення:",
    },
    "settings.pause_hint": {
        "en": "How long to wait in silence before sending audio for recognition",
        "uk": "Скільки чекати тиші перед відправкою аудіо на розпізнавання",
    },
    "settings.hotkey_label": {
        "en": "Hotkey:",
        "uk": "Гаряча клавіша:",
    },
    "settings.record_btn": {
        "en": "Record...",
        "uk": "Записати...",
    },
    "settings.recording_mode": {
        "en": "Recording mode:",
        "uk": "Режим запису:",
    },
    "settings.mode_toggle": {
        "en": "Toggle: press to start, press again to stop",
        "uk": "Перемикач: натисніть для старту, ще раз для зупинки",
    },
    "settings.mode_hold": {
        "en": "Hold: record while key is held down",
        "uk": "Утримання: запис поки клавіша натиснута",
    },
    "settings.hold_key": {
        "en": "Hold key:",
        "uk": "Клавіша утримання:",
    },
    "settings.hold_hint": {
        "en": "Key to hold for push-to-talk (only in Hold mode)",
        "uk": "Клавіша для утримання (тільки в режимі Утримання)",
    },
    "settings.normalize_check": {
        "en": "Enable LLM normalization after dictation",
        "uk": "Увімкнути LLM-нормалізацію після диктування",
    },
    "settings.beep_start": {
        "en": "Beep on recording start",
        "uk": "Звук на початку запису",
    },
    "settings.beep_stop": {
        "en": "Beep on recording stop",
        "uk": "Звук при зупинці запису",
    },
    "settings.show_notif": {
        "en": "Show tray notifications",
        "uk": "Показувати сповіщення в треї",
    },
    "settings.tab_dictation": {
        "en": "Dictation",
        "uk": "Диктування",
    },
    "settings.feedback_hint": {
        "en": "Self-learning: after dictation, edit the text manually, then double-tap the hotkey. "
              "The app will compare your edits with its output and learn from the corrections.",
        "uk": "Самонавчання: після диктування відредагуйте текст вручну, потім двічі натисніть гарячу клавішу. "
              "Додаток порівняє ваші правки зі своїм результатом і навчиться на виправленнях.",
    },

    "tray.about": {
        "en": "About",
        "uk": "Про програму",
    },

    # ── Overlay ──────────────────────────────────────────────────
    "overlay.rec": {
        "en": "REC",
        "uk": "ЗАП",
    },
}

# Current language
_current_lang: str = "uk"


def set_language(lang: str) -> None:
    """Set UI language ('uk' or 'en')."""
    global _current_lang
    _current_lang = lang if lang in ("uk", "en") else "uk"


def get_language() -> str:
    """Get current UI language."""
    return _current_lang


def t(key: str, **kwargs) -> str:
    """Get translated string by key. Supports {placeholder} formatting."""
    entry = _STRINGS.get(key)
    if not entry:
        return key

    text = entry.get(_current_lang) or entry.get("en") or key
    if kwargs:
        text = text.format(**kwargs)
    return text

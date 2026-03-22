"""Quick-translate overlay — triggered by double Ctrl+C.

Shows clipboard text translated to selected language.
Design: flat UI — navy header, light cards, orange accents.
"""

import logging
import threading
import time
import tkinter as tk
from tkinter import ttk

import httpx
import pyperclip

from .config import GroqConfig
from .i18n import t
from .provider_manager import ProviderManager
from .utils import detect_windows_theme, load_translate_settings, save_translate_settings, load_deepl_keys

logger = logging.getLogger(__name__)

# ── Color Themes ──────────────────────────────────────────────────────

THEME_LIGHT = {
    "header": "#f0f0f0",         # Windows light title bar
    "header_text": "#1a1a1a",
    "bg": "#f3f3f3",             # Windows light background
    "card": "#ffffff",           # white card
    "card_input": "#f9f9f9",     # light grey text area (like Windows input)
    "text": "#1a1a1a",           # primary text
    "text_mid": "#666666",       # secondary
    "text_dim": "#999999",       # dimmed
    "accent": "#0078d4",         # Windows blue accent
    "accent_hover": "#106ebe",
    "success": "#107c10",        # Windows green
    "danger": "#d13438",         # Windows red
    "info": "#0078d4",           # Windows blue
    "border": "#e5e5e5",         # Windows border
    "btn_text": "#ffffff",
}

THEME_DARK = {
    "header": "#202020",         # Windows dark title bar (Explorer)
    "header_text": "#ffffff",
    "bg": "#191919",             # Windows dark background
    "card": "#2d2d2d",           # dark card (Explorer panels)
    "card_input": "#1e1e1e",     # dark input area
    "text": "#ffffff",           # primary text
    "text_mid": "#999999",       # secondary
    "text_dim": "#666666",       # dimmed
    "accent": "#4cc2ff",         # Windows dark blue accent
    "accent_hover": "#2eaadc",
    "success": "#6ccb5f",        # green
    "danger": "#ff6b6b",         # red
    "info": "#4cc2ff",           # blue
    "border": "#3d3d3d",         # dark border
    "btn_text": "#1a1a1a",
}


def _get_theme() -> dict:
    """Get active theme dict based on user setting (auto/light/dark)."""
    pref = load_translate_settings().get("theme", "auto")
    if pref == "light":
        return THEME_LIGHT
    elif pref == "dark":
        return THEME_DARK
    else:  # auto
        return THEME_LIGHT if detect_windows_theme() == "light" else THEME_DARK

# ── Languages ─────────────────────────────────────────────────────────

LANGUAGES = [
    ("English", "en"),
    ("Ukrainian", "uk"),
    ("Russian", "ru"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Polish", "pl"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Japanese", "ja"),
    ("Chinese", "zh"),
    ("Korean", "ko"),
    ("Turkish", "tr"),
    ("Arabic", "ar"),
]

TRANSLATE_PROMPT = """\
Translate the following text to {language}.
Return ONLY the translation, no explanations or commentary.
Preserve formatting, line breaks, and punctuation style."""



class TranslateOverlay:
    """Floating overlay for quick translation — flat UI dashboard style."""

    def __init__(self, groq_config: GroqConfig, provider_manager: ProviderManager | None = None):
        self._groq = groq_config
        self._provider_manager = provider_manager
        self._window: tk.Tk | None = None
        self._thread: threading.Thread | None = None
        self._source_text = ""
        self._target_lang = load_translate_settings().get("target_lang", "en")
        self._deepl_rotation_idx = 0

    def show(self, text: str) -> None:
        if not text.strip():
            return
        self._source_text = text.strip()
        self.hide()
        # Wait for previous window to fully close
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = threading.Thread(target=self._build_and_run, daemon=True)
        self._thread.start()

    def hide(self) -> None:
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    def _build_and_run(self) -> None:
        try:
            T = _get_theme()

            root = tk.Tk()
            self._window = root
            root.title("AI Polyglot Kit — Translate")
            root.attributes("-topmost", True)
            root.overrideredirect(False)
            root.configure(bg=T["bg"])
            root.minsize(420, 320)

            # Load saved size
            settings = load_translate_settings()
            w = settings.get("window_w", 500)
            h = settings.get("window_h", 400)
            root.update_idletasks()
            sx = (root.winfo_screenwidth() - w) // 2
            sy = (root.winfo_screenheight() - h) // 2
            root.geometry(f"{w}x{h}+{sx}+{sy}")

            def on_close():
                try:
                    save_translate_settings({
                        "window_w": root.winfo_width(),
                        "window_h": root.winfo_height(),
                    })
                except Exception:
                    pass
                root.destroy()

            root.protocol("WM_DELETE_WINDOW", on_close)

            # ── Top bar: Translate tab + language selector ───────────
            top_bar = tk.Frame(root, bg=T["header"], height=44)
            top_bar.pack(fill="x")
            top_bar.pack_propagate(False)

            # "Translate" tab button (always active)
            tab_btn = tk.Label(
                top_bar, text=" \U0001F5E8 Translate ",
                fg=T["btn_text"], bg=T["accent"],
                font=("Segoe UI", 10, "bold"), padx=12, pady=8,
            )
            tab_btn.pack(side="left", padx=(8, 0), pady=6)

            # Engine label (right side)
            engine_var = tk.StringVar(value="")
            tk.Label(
                top_bar, textvariable=engine_var,
                fg=T["text_dim"], bg=T["header"], font=("Segoe UI", 8),
            ).pack(side="right", padx=12)

            # ── Language selector row ────────────────────────────────
            lang_row = tk.Frame(root, bg=T["bg"], padx=12, pady=8)
            lang_row.pack(fill="x")

            lang_var = tk.StringVar()
            lang_names = [name for name, code in LANGUAGES]

            lang_combo = ttk.Combobox(
                lang_row, textvariable=lang_var, values=lang_names,
                width=16, state="readonly", font=("Segoe UI", 10),
            )
            for i, (name, code) in enumerate(LANGUAGES):
                if code == self._target_lang:
                    lang_combo.current(i)
                    break
            lang_combo.pack(side="left")

            status_var = tk.StringVar(value="")
            tk.Label(
                lang_row, textvariable=status_var,
                fg=T["text_dim"], bg=T["bg"], font=("Segoe UI", 8),
            ).pack(side="right")

            # ── Translation result area ──────────────────────────────
            text_frame = tk.Frame(root, bg=T["border"], padx=1, pady=1)
            text_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

            result_text = tk.Text(
                text_frame, wrap="word",
                fg=T["text"], bg=T["card"], font=("Segoe UI", 11),
                borderwidth=0, highlightthickness=0, padx=12, pady=10,
                selectbackground=T["accent"], insertbackground=T["text"],
            )
            result_text.insert("1.0", t("translate.loading"))
            result_text.config(state="disabled")
            result_text.pack(fill="both", expand=True)

            # ── Bottom buttons bar ───────────────────────────────────
            btn_bar = tk.Frame(root, bg=T["bg"], padx=12, pady=8)
            btn_bar.pack(fill="x")

            # Helper to make styled buttons
            def _make_btn(parent, text, bg_color, hover_color, side="left"):
                btn = tk.Label(
                    parent, text=text,
                    fg=T["text"] if bg_color == T["bg"] else T["btn_text"],
                    bg=bg_color, font=("Segoe UI", 9),
                    cursor="hand2", padx=14, pady=7,
                    bd=1, relief="solid",
                    highlightbackground=T["border"], highlightthickness=1,
                )
                btn.pack(side=side, padx=(0, 6) if side == "left" else (6, 0))
                btn.bind("<Enter>", lambda e, b=btn, c=hover_color: b.config(bg=c))
                btn.bind("<Leave>", lambda e, b=btn, c=bg_color: b.config(bg=c))
                return btn

            copy_btn = _make_btn(btn_bar, "\U0001F4CB  Копіювати", T["card"], T["border"])
            replace_btn = _make_btn(btn_bar, "\u21B5  Замінити", T["accent"], T["accent_hover"], side="right")

            # ── Handlers ────────────────────────────────────────────

            def do_copy(event=None):
                result_text.config(state="normal")
                text = result_text.get("1.0", "end").strip()
                result_text.config(state="disabled")
                if text and text != t("translate.loading"):
                    pyperclip.copy(text)
                    status_var.set("\u2713 " + t("translate.copied"))
                    copy_btn.config(bg=T["success"], fg=T["btn_text"])
                    root.after(2000, lambda: copy_btn.config(bg=T["card"], fg=T["text"]))

            copy_btn.bind("<Button-1>", do_copy)

            def do_replace(event=None):
                result_text.config(state="normal")
                translated = result_text.get("1.0", "end").strip()
                result_text.config(state="disabled")
                if not translated or translated == t("translate.loading"):
                    return
                pyperclip.copy(translated)
                on_close()

                import ctypes
                time.sleep(0.2)
                user32 = ctypes.windll.user32
                VK_CONTROL, VK_V = 0x11, 0x56
                KEYEVENTF_KEYUP = 0x0002
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_V, 0, 0, 0)
                user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                logger.info("Replaced selection with translation (%d chars)", len(translated))

            replace_btn.bind("<Button-1>", do_replace)

            def do_translate(lang_name=None):
                if lang_name is None:
                    lang_name = lang_var.get()

                for name, code in LANGUAGES:
                    if name == lang_name:
                        self._target_lang = code
                        save_translate_settings({"target_lang": code})
                        break

                result_text.config(state="normal")
                result_text.delete("1.0", "end")
                result_text.insert("1.0", t("translate.loading"))
                result_text.config(state="disabled")
                status_var.set("")
                engine_var.set("")

                def _api_call():
                    try:
                        start = time.monotonic()
                        translated, engine = self._translate(self._source_text, lang_name)
                        elapsed = time.monotonic() - start

                        def _update():
                            result_text.config(state="normal")
                            result_text.delete("1.0", "end")
                            result_text.insert("1.0", translated)
                            result_text.config(state="disabled")
                            status_var.set(f"{elapsed:.1f}s \u2022 {len(translated)} chars")
                            engine_var.set(f"via {engine}")

                        root.after(0, _update)

                    except Exception as exc:
                        logger.error("Translation failed: %s", exc)
                        err_msg = str(exc)
                        # User-friendly error messages
                        if "Illegal header" in err_msg or "Bearer" in err_msg:
                            err_msg = "API ключ не налаштовано. Відкрийте Налаштування → Переклад"
                        elif "No translation" in err_msg:
                            err_msg = "Не налаштовано жодного сервісу перекладу"

                        def _error(msg=err_msg):
                            result_text.config(state="normal")
                            result_text.delete("1.0", "end")
                            result_text.insert("1.0", msg)
                            result_text.config(state="disabled")
                            status_var.set("Failed")

                        root.after(0, _error)

                threading.Thread(target=_api_call, daemon=True).start()

            def on_lang_change(event=None):
                do_translate(lang_var.get())

            lang_combo.bind("<<ComboboxSelected>>", on_lang_change)

            # Keyboard shortcuts
            root.bind("<Escape>", lambda e: on_close())
            root.bind("<Control-c>", do_copy)

            # Start first translation
            do_translate()

            root.mainloop()

        except Exception as e:
            logger.error(f"Translate overlay error: {e}")
        finally:
            self._window = None

    # ── Translation engines ─────────────────────────────────────────

    def _translate(self, text: str, target_language: str) -> tuple[str, str]:
        """Translate text. Returns (translated_text, engine_name)."""
        lang_code = "en"
        for name, code in LANGUAGES:
            if name == target_language:
                lang_code = code
                break

        # Try DeepL with key rotation
        keys = load_deepl_keys()
        if keys:
            for attempt in range(len(keys)):
                key = self._next_deepl_key(keys)
                try:
                    result = self._translate_deepl(text, lang_code, key)
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

            logger.warning("All DeepL keys exhausted, falling back to Groq")

        # Fallback to translation LLM via ProviderManager
        if self._provider_manager:
            llm = self._provider_manager.get_translation_llm()
            if llm:
                try:
                    result = llm.chat([
                        {"role": "system", "content": TRANSLATE_PROMPT.format(language=target_language)},
                        {"role": "user", "content": text},
                    ], temperature=0.3)
                    return result, "LLM"
                except Exception as e:
                    logger.warning("Translation LLM failed: %s", e)

        # Legacy fallback to groq.api_key
        if self._groq.api_key:
            result = self._translate_groq(text, target_language)
            return result, "Groq LLM"

        raise ValueError("Не налаштовано жодного сервісу перекладу. Додайте API ключ у Налаштування → Переклад")


    def _next_deepl_key(self, keys: list[str]) -> str:
        if not keys:
            return ""
        idx = self._deepl_rotation_idx % len(keys)
        self._deepl_rotation_idx += 1
        return keys[idx]

    def _translate_deepl(self, text: str, target_lang: str, api_key: str) -> str:
        base_url = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
        deepl_lang = target_lang.upper()
        lang_map = {"EN": "EN-US", "PT": "PT-BR", "ZH": "ZH-HANS"}
        deepl_lang = lang_map.get(deepl_lang, deepl_lang)

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{base_url}/v2/translate",
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                data={"text": text, "target_lang": deepl_lang},
            )
            if resp.status_code == 456:
                raise ValueError("DeepL quota exceeded for this key")
            resp.raise_for_status()
            data = resp.json()
            translations = data.get("translations", [])
            if translations:
                return translations[0].get("text", "")
            raise ValueError("No translations in DeepL response")

    def _translate_groq(self, text: str, target_language: str) -> str:
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
                        {"role": "system", "content": TRANSLATE_PROMPT.format(language=target_language)},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

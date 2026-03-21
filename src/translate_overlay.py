"""Quick-translate overlay — triggered by double Ctrl+C.

Shows clipboard text translated to selected language.
Design: flat UI — navy header, light cards, orange accents.
"""

import json
import logging
import threading
import time
import tkinter as tk
from tkinter import ttk

import httpx
import pyperclip

from .config import GroqConfig, APP_DIR
from .i18n import t

logger = logging.getLogger(__name__)

# ── Color Scheme (Flat UI Dashboard) ──────────────────────────────────

NAVY = "#2c3e50"             # header/sidebar
NAVY_LIGHT = "#34495e"       # header hover
BG_PAGE = "#ecf0f1"          # page background
BG_CARD = "#ffffff"          # card surface
TEXT_DARK = "#2c3e50"        # primary text
TEXT_MID = "#7f8c8d"         # secondary text
TEXT_LIGHT = "#bdc3c7"       # dimmed text
ACCENT = "#e67e22"           # orange accent (buttons)
ACCENT_HOVER = "#d35400"     # darker orange hover
SUCCESS = "#27ae60"          # green
DANGER = "#e74c3c"           # red
INFO = "#3498db"             # blue
BORDER = "#dcdde1"           # card borders

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

_SETTINGS_FILE = APP_DIR / "translate_settings.json"


def _load_settings() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_settings(updates: dict) -> None:
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = _load_settings()
        data.update(updates)
        _SETTINGS_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


class TranslateOverlay:
    """Floating overlay for quick translation — flat UI dashboard style."""

    def __init__(self, groq_config: GroqConfig):
        self._groq = groq_config
        self._window: tk.Tk | None = None
        self._thread: threading.Thread | None = None
        self._source_text = ""
        self._target_lang = _load_settings().get("target_lang", "en")
        self._deepl_rotation_idx = 0

    def show(self, text: str) -> None:
        if not text.strip():
            return
        self._source_text = text.strip()
        self.hide()
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
            root = tk.Tk()
            self._window = root
            root.title("Groq Translate")
            root.attributes("-topmost", True)
            root.configure(bg=BG_PAGE)
            root.minsize(450, 350)

            # Load saved size
            settings = _load_settings()
            w = settings.get("window_w", 640)
            h = settings.get("window_h", 460)
            root.update_idletasks()
            sx = (root.winfo_screenwidth() - w) // 2
            sy = (root.winfo_screenheight() - h) // 2
            root.geometry(f"{w}x{h}+{sx}+{sy}")

            def on_close():
                try:
                    _save_settings({
                        "window_w": root.winfo_width(),
                        "window_h": root.winfo_height(),
                    })
                except Exception:
                    pass
                root.destroy()

            root.protocol("WM_DELETE_WINDOW", on_close)

            # ── Header (navy bar) ───────────────────────────────────
            header = tk.Frame(root, bg=NAVY, height=48)
            header.pack(fill="x")
            header.pack_propagate(False)

            tk.Label(
                header, text="\u2630  Groq Translate",
                fg="white", bg=NAVY, font=("Segoe UI", 12, "bold"),
                padx=16,
            ).pack(side="left")

            # Header buttons (right side)
            btn_frame = tk.Frame(header, bg=NAVY)
            btn_frame.pack(side="right", padx=8)

            # Replace button
            replace_btn = tk.Label(
                btn_frame, text="  \u21c4 Replace  ",
                fg="white", bg=ACCENT, font=("Segoe UI", 9, "bold"),
                cursor="hand2", padx=8, pady=4,
            )
            replace_btn.pack(side="left", padx=(0, 6), pady=8)
            replace_btn.bind("<Enter>", lambda e: replace_btn.config(bg=ACCENT_HOVER))
            replace_btn.bind("<Leave>", lambda e: replace_btn.config(bg=ACCENT))

            # Copy button
            copy_btn = tk.Label(
                btn_frame, text="  \u2398 Copy  ",
                fg="white", bg=INFO, font=("Segoe UI", 9, "bold"),
                cursor="hand2", padx=8, pady=4,
            )
            copy_btn.pack(side="left", padx=(0, 6), pady=8)
            copy_btn.bind("<Enter>", lambda e: copy_btn.config(bg="#2980b9"))
            copy_btn.bind("<Leave>", lambda e: copy_btn.config(bg=INFO))

            # ── Toolbar (language selector) ─────────────────────────
            toolbar = tk.Frame(root, bg=BG_PAGE, padx=16, pady=10)
            toolbar.pack(fill="x")

            tk.Label(
                toolbar, text="Translate to:",
                fg=TEXT_MID, bg=BG_PAGE, font=("Segoe UI", 10),
            ).pack(side="left")

            lang_var = tk.StringVar()
            lang_names = [name for name, code in LANGUAGES]

            style = ttk.Style()
            style.configure("Translate.TCombobox", padding=4)

            lang_combo = ttk.Combobox(
                toolbar, textvariable=lang_var, values=lang_names,
                width=14, state="readonly", style="Translate.TCombobox",
            )
            for i, (name, code) in enumerate(LANGUAGES):
                if code == self._target_lang:
                    lang_combo.current(i)
                    break
            lang_combo.pack(side="left", padx=(8, 0))

            # Engine indicator
            engine_var = tk.StringVar(value="")
            tk.Label(
                toolbar, textvariable=engine_var,
                fg=TEXT_LIGHT, bg=BG_PAGE, font=("Segoe UI", 8),
            ).pack(side="right")

            # ── Content area ────────────────────────────────────────
            content = tk.Frame(root, bg=BG_PAGE, padx=16)
            content.pack(fill="both", expand=True)

            # Source card
            src_card = tk.Frame(content, bg=BG_CARD, bd=1, relief="solid",
                                highlightbackground=BORDER, highlightthickness=1)
            src_card.pack(fill="x", pady=(0, 8))

            src_header = tk.Frame(src_card, bg=BG_CARD)
            src_header.pack(fill="x", padx=12, pady=(8, 0))
            tk.Label(
                src_header, text="ORIGINAL",
                fg=TEXT_LIGHT, bg=BG_CARD, font=("Segoe UI", 8, "bold"),
            ).pack(side="left")

            src_text = tk.Text(
                src_card, height=4, wrap="word",
                fg=TEXT_MID, bg=BG_CARD, font=("Segoe UI", 10),
                borderwidth=0, highlightthickness=0, padx=12, pady=8,
                selectbackground=INFO,
            )
            src_text.insert("1.0", self._source_text[:2000])
            src_text.config(state="disabled")
            src_text.pack(fill="x")

            # Translation card
            result_card = tk.Frame(content, bg=BG_CARD, bd=1, relief="solid",
                                   highlightbackground=BORDER, highlightthickness=1)
            result_card.pack(fill="both", expand=True, pady=(0, 8))

            result_header = tk.Frame(result_card, bg=BG_CARD)
            result_header.pack(fill="x", padx=12, pady=(8, 0))
            tk.Label(
                result_header, text="TRANSLATION",
                fg=TEXT_LIGHT, bg=BG_CARD, font=("Segoe UI", 8, "bold"),
            ).pack(side="left")

            result_text = tk.Text(
                result_card, wrap="word",
                fg=TEXT_DARK, bg=BG_CARD, font=("Segoe UI", 11),
                borderwidth=0, highlightthickness=0, padx=12, pady=8,
                selectbackground=INFO,
            )
            result_text.insert("1.0", t("translate.loading"))
            result_text.config(state="disabled")
            result_text.pack(fill="both", expand=True)

            # ── Status bar ──────────────────────────────────────────
            status_frame = tk.Frame(root, bg=BG_PAGE, padx=16, pady=(0, 8))
            status_frame.pack(fill="x")

            status_var = tk.StringVar(value="")
            tk.Label(
                status_frame, textvariable=status_var,
                fg=TEXT_LIGHT, bg=BG_PAGE, font=("Segoe UI", 8), anchor="w",
            ).pack(side="left")

            # ── Handlers ────────────────────────────────────────────

            def do_copy(event=None):
                result_text.config(state="normal")
                text = result_text.get("1.0", "end").strip()
                result_text.config(state="disabled")
                if text and text != t("translate.loading"):
                    pyperclip.copy(text)
                    status_var.set("\u2713 " + t("translate.copied"))
                    copy_btn.config(bg=SUCCESS)
                    root.after(2000, lambda: copy_btn.config(bg=INFO))

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
                        _save_settings({"target_lang": code})
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
                            status_var.set(f"{elapsed:.1f}s  \u2022  {len(translated)} chars")
                            engine_var.set(f"via {engine}")

                        root.after(0, _update)

                    except Exception as e:
                        logger.error(f"Translation failed: {e}")

                        def _error():
                            result_text.config(state="normal")
                            result_text.delete("1.0", "end")
                            result_text.insert("1.0", f"Error: {e}")
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
        keys = self._load_deepl_keys()
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

        # Fallback to Groq LLM
        result = self._translate_groq(text, target_language)
        return result, "Groq LLM"

    def _load_deepl_keys(self) -> list[str]:
        try:
            data = _load_settings()
            keys = data.get("deepl_keys", [])
            if not keys and data.get("deepl_key"):
                keys = [data["deepl_key"]]
            return [k for k in keys if k.strip()]
        except Exception:
            return []

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
                data={"auth_key": api_key, "text": text, "target_lang": deepl_lang},
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
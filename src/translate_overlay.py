"""Quick-translate overlay — triggered by double Ctrl+C.

Shows clipboard text translated to selected language in a floating overlay.
2026 design: elevated neutrals, warm tones, frosted glass effect.
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

# ── Color Scheme (2026 Material Elevated Neutrals) ────────────────────

BG_PRIMARY = "#2b2d31"       # warm dark grey (not pure black)
BG_SURFACE = "#383a40"       # elevated surface
BG_CARD = "#404249"          # card/input background
ACCENT = "#5dadec"           # soft sky blue
ACCENT_HOVER = "#7abfff"     # lighter blue hover
TEXT_PRIMARY = "#f2f3f5"     # warm white
TEXT_SECONDARY = "#b5bac1"   # muted text
TEXT_DIM = "#80848e"         # dimmed text
SUCCESS = "#57d59f"          # mint green
DANGER = "#ed4245"           # soft red
BORDER = "#4e5058"           # subtle border

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

# Persisted settings
_SETTINGS_FILE = APP_DIR / "translate_settings.json"


def _load_target_lang() -> str:
    """Load last used target language."""
    try:
        if _SETTINGS_FILE.exists():
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            return data.get("target_lang", "en")
    except Exception:
        pass
    return "en"


def _save_target_lang(lang_code: str) -> None:
    """Save target language for next time."""
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps({"target_lang": lang_code}),
            encoding="utf-8",
        )
    except Exception:
        pass


class TranslateOverlay:
    """Floating overlay window for quick translation."""

    def __init__(self, groq_config: GroqConfig):
        self._groq = groq_config
        self._window: tk.Tk | None = None
        self._thread: threading.Thread | None = None
        self._source_text = ""
        self._target_lang = _load_target_lang()

    def show(self, text: str) -> None:
        """Show overlay with text to translate."""
        if not text.strip():
            return

        self._source_text = text.strip()

        # Close existing overlay if open
        self.hide()

        self._thread = threading.Thread(target=self._build_and_run, daemon=True)
        self._thread.start()

    def hide(self) -> None:
        """Close overlay window."""
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
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.96)  # slight frosted glass effect
            root.configure(bg=BG_PRIMARY)

            # Size and position (center of screen)
            w, h = 620, 420
            root.update_idletasks()
            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            x = (screen_w - w) // 2
            y = (screen_h - h) // 2
            root.geometry(f"{w}x{h}+{x}+{y}")

            # Make window draggable
            drag_data = {"x": 0, "y": 0}

            def on_press(event):
                drag_data["x"] = event.x
                drag_data["y"] = event.y

            def on_drag(event):
                dx = event.x - drag_data["x"]
                dy = event.y - drag_data["y"]
                nx = root.winfo_x() + dx
                ny = root.winfo_y() + dy
                root.geometry(f"+{nx}+{ny}")

            root.bind("<ButtonPress-1>", on_press)
            root.bind("<B1-Motion>", on_drag)

            # Main frame with padding
            frame = tk.Frame(root, bg=BG_PRIMARY, padx=20, pady=14)
            frame.pack(fill="both", expand=True)

            # ── Header ──────────────────────────────────────────────
            header = tk.Frame(frame, bg=BG_PRIMARY)
            header.pack(fill="x", pady=(0, 12))

            # Title
            tk.Label(
                header, text="Translate",
                fg=ACCENT, bg=BG_PRIMARY, font=("Segoe UI", 13, "bold"),
            ).pack(side="left")

            # Close button (rounded feel)
            close_btn = tk.Label(
                header, text="  \u2715  ", fg=TEXT_DIM, bg=BG_SURFACE,
                font=("Segoe UI", 10), cursor="hand2",
            )
            close_btn.pack(side="right", padx=(8, 0))
            close_btn.bind("<Button-1>", lambda e: root.destroy())
            close_btn.bind("<Enter>", lambda e: close_btn.config(fg=DANGER, bg=BG_CARD))
            close_btn.bind("<Leave>", lambda e: close_btn.config(fg=TEXT_DIM, bg=BG_SURFACE))

            # Copy button
            copy_btn = tk.Label(
                header, text="  Copy  ", fg=TEXT_SECONDARY, bg=BG_SURFACE,
                font=("Segoe UI", 9), cursor="hand2",
            )
            copy_btn.pack(side="right", padx=(6, 0))
            copy_btn.bind("<Enter>", lambda e: copy_btn.config(fg=SUCCESS, bg=BG_CARD))
            copy_btn.bind("<Leave>", lambda e: copy_btn.config(fg=TEXT_SECONDARY, bg=BG_SURFACE))

            # Language selector
            lang_frame = tk.Frame(header, bg=BG_PRIMARY)
            lang_frame.pack(side="right", padx=(6, 0))

            tk.Label(
                lang_frame, text="\u2192", fg=TEXT_DIM, bg=BG_PRIMARY,
                font=("Segoe UI", 12),
            ).pack(side="left", padx=(0, 6))

            lang_var = tk.StringVar()
            lang_names = [name for name, code in LANGUAGES]
            lang_combo = ttk.Combobox(
                lang_frame, textvariable=lang_var, values=lang_names,
                width=12, state="readonly",
            )
            # Set saved language
            for i, (name, code) in enumerate(LANGUAGES):
                if code == self._target_lang:
                    lang_combo.current(i)
                    break
            lang_combo.pack(side="left")

            # ── Source text ─────────────────────────────────────────
            src_label = tk.Label(
                frame, text="Original", fg=TEXT_DIM, bg=BG_PRIMARY,
                font=("Segoe UI", 8), anchor="w",
            )
            src_label.pack(fill="x", pady=(0, 2))

            src_frame = tk.Frame(frame, bg=BG_SURFACE, padx=10, pady=8)
            src_frame.pack(fill="x", pady=(0, 10))

            src_text = tk.Text(
                src_frame, height=4, wrap="word",
                fg=TEXT_SECONDARY, bg=BG_SURFACE, font=("Segoe UI", 10),
                borderwidth=0, highlightthickness=0, selectbackground=ACCENT,
            )
            src_text.insert("1.0", self._source_text[:1000])
            src_text.config(state="disabled")
            src_text.pack(fill="x")

            # ── Translation result ──────────────────────────────────
            result_label = tk.Label(
                frame, text="Translation", fg=TEXT_DIM, bg=BG_PRIMARY,
                font=("Segoe UI", 8), anchor="w",
            )
            result_label.pack(fill="x", pady=(0, 2))

            result_frame = tk.Frame(frame, bg=BG_SURFACE, padx=10, pady=8)
            result_frame.pack(fill="both", expand=True)

            result_text = tk.Text(
                result_frame, wrap="word",
                fg=TEXT_PRIMARY, bg=BG_SURFACE, font=("Segoe UI", 11),
                borderwidth=0, highlightthickness=0, selectbackground=ACCENT,
            )
            result_text.insert("1.0", t("translate.loading"))
            result_text.config(state="disabled")
            result_text.pack(fill="both", expand=True)

            # ── Status bar ──────────────────────────────────────────
            status_var = tk.StringVar(value="")
            tk.Label(
                frame, textvariable=status_var,
                fg=TEXT_DIM, bg=BG_PRIMARY, font=("Segoe UI", 8), anchor="w",
            ).pack(fill="x", pady=(6, 0))

            # ── Handlers ────────────────────────────────────────────

            def do_copy(event=None):
                result_text.config(state="normal")
                text = result_text.get("1.0", "end").strip()
                result_text.config(state="disabled")
                if text and text != t("translate.loading"):
                    pyperclip.copy(text)
                    status_var.set(t("translate.copied"))
                    copy_btn.config(fg=SUCCESS)

            copy_btn.bind("<Button-1>", do_copy)

            def do_translate(lang_name=None):
                if lang_name is None:
                    lang_name = lang_var.get()

                # Save selected language
                for name, code in LANGUAGES:
                    if name == lang_name:
                        self._target_lang = code
                        _save_target_lang(code)
                        break

                result_text.config(state="normal")
                result_text.delete("1.0", "end")
                result_text.insert("1.0", t("translate.loading"))
                result_text.config(state="disabled")
                status_var.set("")

                def _api_call():
                    try:
                        start = time.monotonic()
                        translated = self._translate(self._source_text, lang_name)
                        elapsed = time.monotonic() - start

                        def _update():
                            result_text.config(state="normal")
                            result_text.delete("1.0", "end")
                            result_text.insert("1.0", translated)
                            result_text.config(state="disabled")
                            status_var.set(f"{elapsed:.1f}s  \u2022  {len(translated)} chars")

                        root.after(0, _update)

                    except Exception as e:
                        logger.error(f"Translation failed: {e}")

                        def _error():
                            result_text.config(state="normal")
                            result_text.delete("1.0", "end")
                            result_text.insert("1.0", f"Error: {e}")
                            result_text.config(state="disabled")

                        root.after(0, _error)

                threading.Thread(target=_api_call, daemon=True).start()

            def on_lang_change(event=None):
                do_translate(lang_var.get())

            lang_combo.bind("<<ComboboxSelected>>", on_lang_change)

            # Keyboard shortcuts
            root.bind("<Escape>", lambda e: root.destroy())
            root.bind("<Control-c>", do_copy)

            # Start first translation
            do_translate()

            root.mainloop()

        except Exception as e:
            logger.error(f"Translate overlay error: {e}")
        finally:
            self._window = None

    def _translate(self, text: str, target_language: str) -> str:
        """Call Groq LLM to translate text."""
        try:
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
                            {
                                "role": "system",
                                "content": TRANSLATE_PROMPT.format(language=target_language),
                            },
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 4000,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logger.error(f"Translation API error: {e}")
            raise
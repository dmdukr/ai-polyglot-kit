"""Quick-translate overlay — triggered by double Ctrl+C.

Shows clipboard text translated to selected language in a floating overlay.
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

logger = logging.getLogger(__name__)

# Supported target languages
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
]

TRANSLATE_PROMPT = """\
Translate the following text to {language}.
Return ONLY the translation, no explanations or commentary.
Preserve formatting, line breaks, and punctuation style."""


class TranslateOverlay:
    """Floating overlay window for quick translation."""

    def __init__(self, groq_config: GroqConfig):
        self._groq = groq_config
        self._window: tk.Tk | None = None
        self._thread: threading.Thread | None = None
        self._source_text = ""
        self._target_lang = "en"  # default

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
            root.configure(bg="#1e1e2e")

            # Size and position (center of screen)
            w, h = 600, 400
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

            # Main frame
            frame = tk.Frame(root, bg="#1e1e2e", padx=16, pady=12)
            frame.pack(fill="both", expand=True)

            # Header with language selector and close button
            header = tk.Frame(frame, bg="#1e1e2e")
            header.pack(fill="x", pady=(0, 8))

            tk.Label(
                header, text="Groq Translate",
                fg="#89b4fa", bg="#1e1e2e", font=("Segoe UI", 11, "bold"),
            ).pack(side="left")

            # Close button
            close_btn = tk.Label(
                header, text=" X ", fg="#f38ba8", bg="#313244",
                font=("Segoe UI", 10, "bold"), cursor="hand2",
            )
            close_btn.pack(side="right", padx=(8, 0))
            close_btn.bind("<Button-1>", lambda e: root.destroy())

            # Copy button
            copy_btn = tk.Label(
                header, text=" Copy ", fg="#a6e3a1", bg="#313244",
                font=("Segoe UI", 9), cursor="hand2",
            )
            copy_btn.pack(side="right", padx=(4, 0))

            # Language selector
            lang_var = tk.StringVar(value=self._target_lang)
            lang_names = [name for name, code in LANGUAGES]
            lang_combo = ttk.Combobox(
                header, textvariable=lang_var, values=lang_names,
                width=12, state="readonly",
            )
            # Set default to English
            for i, (name, code) in enumerate(LANGUAGES):
                if code == self._target_lang:
                    lang_combo.current(i)
                    break
            lang_combo.pack(side="right", padx=(8, 0))

            tk.Label(
                header, text="->", fg="#6c7086", bg="#1e1e2e",
                font=("Segoe UI", 10),
            ).pack(side="right")

            # Source text (top, dimmed)
            src_frame = tk.Frame(frame, bg="#313244", padx=8, pady=6)
            src_frame.pack(fill="x", pady=(0, 8))

            src_text = tk.Text(
                src_frame, height=4, wrap="word",
                fg="#a6adc8", bg="#313244", font=("Segoe UI", 10),
                borderwidth=0, highlightthickness=0,
            )
            src_text.insert("1.0", self._source_text[:500])
            src_text.config(state="disabled")
            src_text.pack(fill="x")

            # Translation result (bottom, bright)
            result_frame = tk.Frame(frame, bg="#313244", padx=8, pady=6)
            result_frame.pack(fill="both", expand=True)

            result_text = tk.Text(
                result_frame, wrap="word",
                fg="#cdd6f4", bg="#313244", font=("Segoe UI", 11),
                borderwidth=0, highlightthickness=0,
            )
            result_text.insert("1.0", t("translate.loading"))
            result_text.config(state="disabled")
            result_text.pack(fill="both", expand=True)

            # Status bar
            status_var = tk.StringVar(value="")
            status_label = tk.Label(
                frame, textvariable=status_var,
                fg="#6c7086", bg="#1e1e2e", font=("Segoe UI", 8),
                anchor="w",
            )
            status_label.pack(fill="x", pady=(4, 0))

            # Copy button handler
            def do_copy(event=None):
                result_text.config(state="normal")
                text = result_text.get("1.0", "end").strip()
                result_text.config(state="disabled")
                if text and text != t("translate.loading"):
                    pyperclip.copy(text)
                    status_var.set(t("translate.copied"))

            copy_btn.bind("<Button-1>", do_copy)

            # Translate function
            def do_translate(lang_name=None):
                if lang_name is None:
                    lang_name = lang_var.get()

                # Find language code
                target_lang = "en"
                for name, code in LANGUAGES:
                    if name == lang_name:
                        target_lang = code
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
                            status_var.set(f"{elapsed:.1f}s")

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

            # Language change handler
            def on_lang_change(event=None):
                do_translate(lang_var.get())

            lang_combo.bind("<<ComboboxSelected>>", on_lang_change)

            # Escape to close
            root.bind("<Escape>", lambda e: root.destroy())

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
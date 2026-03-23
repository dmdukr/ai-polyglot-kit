"""Quick-translate overlay — triggered by double Ctrl+C.

Shows clipboard text translated to selected language.
Design: flat UI — navy header, light cards, orange accents.
"""

import logging
import threading
import time
import tkinter as tk
from tkinter import ttk

import pyperclip

from .config import GroqConfig
from .i18n import t
from .provider_manager import ProviderManager
from .translate_engine import TranslateEngine, LANGUAGES
from .utils import detect_windows_theme, load_translate_settings, save_translate_settings

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
    "accent": "#0078d4",         # Windows accent blue
    "accent_hover": "#106ebe",
    "success": "#6ccb5f",        # green
    "danger": "#ff6b6b",         # red
    "info": "#4cc2ff",           # blue
    "border": "#3d3d3d",         # dark border
    "btn_text": "#ffffff",       # white text on buttons
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



class TranslateOverlay:
    """Floating overlay for quick translation — flat UI dashboard style."""

    def __init__(self, groq_config: GroqConfig, provider_manager: ProviderManager | None = None):
        self._groq = groq_config
        self._provider_manager = provider_manager
        self._engine = TranslateEngine(provider_manager=provider_manager, groq_config=groq_config)
        self._window: tk.Toplevel | None = None
        self._source_text = ""
        self._target_lang = load_translate_settings().get("target_lang", "en")

    def show(self, text: str) -> None:
        if not text.strip():
            return
        self._source_text = text.strip()
        self.hide()
        from . import tk_host
        tk_host.run_on_tk(self._build)

    def hide(self) -> None:
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    def _build(self) -> None:
        """Build translate overlay. Runs on Tk host thread."""
        try:
            from . import tk_host
            T = _get_theme()
            is_dark = T is THEME_DARK

            win = tk.Toplevel(tk_host.get_root())
            self._window = win
            win.title("AI Polyglot Kit — Translate")
            win.attributes("-topmost", True)
            win.configure(bg=T["bg"])
            win.minsize(420, 320)

            if is_dark:
                from .utils import set_dwm_dark_title_bar
                win.update_idletasks()
                set_dwm_dark_title_bar(win)

            # Load saved size
            settings = load_translate_settings()
            w = settings.get("window_w", 500)
            h = settings.get("window_h", 400)
            win.update_idletasks()
            sx = (win.winfo_screenwidth() - w) // 2
            sy = (win.winfo_screenheight() - h) // 2
            win.geometry(f"{w}x{h}+{sx}+{sy}")

            def on_close():
                try:
                    save_translate_settings({
                        "window_w": win.winfo_width(),
                        "window_h": win.winfo_height(),
                    })
                except Exception:
                    pass
                self._window = None
                win.destroy()

            win.protocol("WM_DELETE_WINDOW", on_close)

            # ── Top bar: Translate tab + language selector ───────────
            top_bar = tk.Frame(win, bg=T["header"], height=44)
            top_bar.pack(fill="x")
            top_bar.pack_propagate(False)

            tab_btn = tk.Label(
                top_bar, text=" \U0001F5E8 Translate ",
                fg=T["btn_text"], bg=T["accent"],
                font=("Segoe UI", 10, "bold"), padx=12, pady=8,
            )
            tab_btn.pack(side="left", padx=(8, 0), pady=6)

            engine_var = tk.StringVar(value="")
            tk.Label(
                top_bar, textvariable=engine_var,
                fg=T["text_dim"], bg=T["header"], font=("Segoe UI", 8),
            ).pack(side="right", padx=12)

            # ── Language selector row ────────────────────────────────
            lang_row = tk.Frame(win, bg=T["bg"], padx=12, pady=8)
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
            text_frame = tk.Frame(win, bg=T["border"], padx=1, pady=1)
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
            btn_bar = tk.Frame(win, bg=T["bg"], padx=12, pady=8)
            btn_bar.pack(fill="x")

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
                    win.after(2000, lambda: copy_btn.config(bg=T["card"], fg=T["text"]))

            copy_btn.bind("<Button-1>", do_copy)

            def do_replace(event=None):
                result_text.config(state="normal")
                translated = result_text.get("1.0", "end").strip()
                result_text.config(state="disabled")
                if not translated or translated == t("translate.loading"):
                    return
                pyperclip.copy(translated)
                on_close()

                # Simulate Ctrl+V in worker thread (sleep would block Tk)
                def _paste():
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

                threading.Thread(target=_paste, daemon=True).start()

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

                        tk_host.run_on_tk(_update)

                    except Exception as exc:
                        logger.error("Translation failed: %s", exc)
                        err_msg = str(exc)
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

                        tk_host.run_on_tk(_error)

                threading.Thread(target=_api_call, daemon=True).start()

            def on_lang_change(event=None):
                do_translate(lang_var.get())

            lang_combo.bind("<<ComboboxSelected>>", on_lang_change)

            win.bind("<Escape>", lambda e: on_close())
            win.bind("<Control-c>", do_copy)

            # Start first translation
            do_translate()

        except Exception as e:
            logger.error(f"Translate overlay error: {e}")
            self._window = None

    # ── Translation (delegated to TranslateEngine) ─────────────────

    def _translate(self, text: str, target_language: str) -> tuple[str, str]:
        """Translate text. Returns (translated_text, engine_name)."""
        return self._engine.translate(text, target_language)

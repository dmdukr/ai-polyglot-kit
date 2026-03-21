"""Settings GUI window using tkinter."""

import logging
import sys
import threading
import tkinter as tk
import winreg
from tkinter import ttk, messagebox
from pathlib import Path

import yaml

from .config import AppConfig, APP_NAME
from .audio_capture import AudioCapture
from .i18n import t
from .utils import set_dwm_dark_title_bar, detect_windows_theme, normalize_key_name, save_translate_settings, load_translate_settings

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_autostart() -> bool:
    """Check if app is in Windows startup registry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _cleanup_duplicate_autostart() -> None:
    """Remove duplicate autostart entries (installer vs app name mismatch)."""
    # Installer used "Groq Dictation" (with space), app uses "GroqDictation"
    alt_names = ["Groq Dictation", "GroqDictation", "AI Polyglot Kit", "AIPolyglotKit"]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            found = []
            for name in alt_names:
                try:
                    winreg.QueryValueEx(key, name)
                    found.append(name)
                except FileNotFoundError:
                    pass
            # If both exist, remove the one that doesn't match APP_NAME
            if len(found) > 1:
                for name in found:
                    if name != APP_NAME:
                        winreg.DeleteValue(key, name)
                        logger.info(f"Removed duplicate autostart: {name}")
    except Exception:
        pass


def _set_autostart(enabled: bool) -> None:
    """Add or remove app from Windows startup registry."""
    try:
        _cleanup_duplicate_autostart()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                # Use the exe path if frozen, otherwise pythonw -m src.main
                if getattr(sys, "frozen", False):
                    exe_path = sys.executable
                else:
                    exe_path = f'"{sys.executable}" -m src.main'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
                logger.info(f"Autostart enabled: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    logger.info("Autostart disabled")
                except FileNotFoundError:
                    pass
    except Exception as e:
        logger.warning(f"Failed to set autostart: {e}")


class SettingsWindow:
    """Modal settings window with tabs for all configurable options."""

    def __init__(self, config: AppConfig, audio_capture: AudioCapture, on_save=None):
        self._config = config
        self._audio = audio_capture
        self._on_save = on_save
        self._window: tk.Tk | None = None

    def show(self) -> None:
        """Open settings window in a new thread (non-blocking)."""
        thread = threading.Thread(target=self._build_and_run, daemon=True)
        thread.start()

    def _build_and_run(self) -> None:
        self._window = tk.Tk()
        self._window.title(t("settings.title"))
        self._window.geometry("740x750")
        self._window.resizable(True, True)
        self._window.minsize(700, 650)

        # Center on screen
        self._window.update_idletasks()
        x = (self._window.winfo_screenwidth() - 520) // 2
        y = (self._window.winfo_screenheight() - 620) // 2
        self._window.geometry(f"+{x}+{y}")

        # Apply Sun Valley theme (Windows 11 native look)
        pref = load_translate_settings().get("theme", "auto")
        if pref == "dark":
            self._is_dark = True
        elif pref == "light":
            self._is_dark = False
        else:
            self._is_dark = detect_windows_theme() == "dark"

        try:
            import sv_ttk
            sv_ttk.set_theme("dark" if self._is_dark else "light")
            if self._is_dark:
                self._window.update()
                set_dwm_dark_title_bar(self._window)
        except ImportError:
            pass

        # Colors for manually created tk widgets (hints, usage labels)
        if self._is_dark:
            self._dark_bg = "#1c1c1c"
            self._dark_fg = "#ffffff"
            self._dark_fg2 = "#9e9e9e"
        else:
            self._dark_bg = None
            self._dark_fg = None
            self._dark_fg2 = "#888888"

        # Always on top
        self._window.attributes("-topmost", True)

        # --- Buttons (fixed at bottom, pack FIRST so notebook gets remaining space) ---
        btn_frame = ttk.Frame(self._window)
        btn_frame.pack(side="bottom", fill="x", padx=12, pady=12)

        ttk.Button(btn_frame, text=t("settings.save"), command=self._save, style="Accent.TButton").pack(side="right", padx=4)
        ttk.Button(btn_frame, text=t("settings.cancel"), command=self._window.destroy).pack(side="right", padx=4)

        # Notebook (tabs)
        notebook = ttk.Notebook(self._window)
        notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        # --- Tab 1: STT Providers ---
        tab_stt = ttk.Frame(notebook, padding=8)
        notebook.add(tab_stt, text=f"  {t('settings.tab_stt')}  ")
        self._stt_slots = self._build_provider_slots(tab_stt, self._config.providers.stt, stt=True)

        # Languages (for STT)
        lang_sep = ttk.Separator(tab_stt, orient="horizontal")
        lang_sep.pack(fill="x", pady=(8, 4))

        ttk.Label(tab_stt, text=t("settings.language"), font=("Segoe UI", 9, "bold")).pack(anchor="w")
        lang_frame = ttk.Frame(tab_stt)
        lang_frame.pack(fill="x", pady=(4, 0))

        self._all_languages = [
            ("uk", "Українська"), ("ru", "Русский"), ("en", "English"),
            ("de", "Deutsch"), ("fr", "Français"), ("es", "Español"),
            ("pl", "Polski"), ("it", "Italiano"), ("pt", "Português"),
            ("nl", "Nederlands"), ("tr", "Türkçe"), ("cs", "Čeština"),
            ("ja", "日本語"), ("zh", "中文"), ("ko", "한국어"),
        ]
        current_langs = set()
        if self._config.groq.stt_language:
            current_langs = {lc.strip() for lc in self._config.groq.stt_language.split(",")}

        self._lang_vars: dict[str, tk.BooleanVar] = {}
        for i, (code, name) in enumerate(self._all_languages):
            var = tk.BooleanVar(master=self._window, value=(code in current_langs) if current_langs else False)
            self._lang_vars[code] = var
            col = i % 5
            row = i // 5
            ttk.Checkbutton(lang_frame, text=name, variable=var).grid(
                row=row, column=col, sticky="w", padx=(0, 8),
            )

        # --- Tab 2: LLM Normalization ---
        tab_llm = ttk.Frame(notebook, padding=8)
        notebook.add(tab_llm, text=f"  {t('settings.tab_llm')}  ")
        self._llm_slots = self._build_provider_slots(tab_llm, self._config.providers.llm, stt=False)

        self._normalize_var = tk.BooleanVar(master=self._window, value=self._config.normalization.enabled)
        ttk.Checkbutton(tab_llm, text=t("settings.normalize_check"),
                        variable=self._normalize_var).pack(anchor="w", pady=(8, 0))

        # --- Tab 3: Translation ---
        tab_trans = ttk.Frame(notebook, padding=8)
        notebook.add(tab_trans, text=f"  {t('settings.tab_translation')}  ")
        self._trans_slots = self._build_provider_slots(
            tab_trans, self._config.providers.translation, stt=False, translation=True)

        # --- Tab 4: Dictation & Audio (merged) ---
        tab_dict = ttk.Frame(notebook, padding=12)
        notebook.add(tab_dict, text=f"  {t('settings.tab_dictation')}  ")

        # Hotkey section
        ttk.Label(tab_dict, text=t("settings.hotkey_label")).grid(row=0, column=0, sticky="w", pady=4)
        hotkey_frame = ttk.Frame(tab_dict)
        hotkey_frame.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=4)
        self._hotkey_var = tk.StringVar(master=self._window, value=self._config.hotkey)
        self._hotkey_entry = ttk.Entry(hotkey_frame, textvariable=self._hotkey_var, width=25, state="readonly")
        self._hotkey_entry.pack(side="left")
        self._record_btn = ttk.Button(hotkey_frame, text=t("settings.record_btn"), command=self._start_hotkey_capture)
        self._record_btn.pack(side="left", padx=(8, 0))

        ttk.Label(tab_dict, text=t("settings.recording_mode")).grid(row=1, column=0, sticky="nw", pady=4)
        mode_frame = ttk.Frame(tab_dict)
        mode_frame.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=4)
        self._hotkey_mode_var = tk.StringVar(master=self._window, value=self._config.hotkey_mode)
        ttk.Radiobutton(mode_frame, text=t("settings.mode_toggle"),
                        variable=self._hotkey_mode_var, value="toggle").pack(anchor="w")
        ttk.Radiobutton(mode_frame, text=t("settings.mode_hold"),
                        variable=self._hotkey_mode_var, value="hold").pack(anchor="w")

        ttk.Label(tab_dict, text=t("settings.hold_key")).grid(row=2, column=0, sticky="w", pady=4)
        ptt_frame = ttk.Frame(tab_dict)
        ptt_frame.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=4)
        self._ptt_var = tk.StringVar(master=self._window, value=self._config.ptt_key)
        self._ptt_entry = ttk.Entry(ptt_frame, textvariable=self._ptt_var, width=15, state="readonly")
        self._ptt_entry.pack(side="left")
        self._ptt_record_btn = ttk.Button(ptt_frame, text=t("settings.record_btn"), command=self._start_ptt_capture)
        self._ptt_record_btn.pack(side="left", padx=(8, 0))
        ttk.Label(tab_dict, text=t("settings.hold_hint"),
                  foreground="gray").grid(row=3, column=1, sticky="w", padx=(8, 0))

        # Audio section separator
        ttk.Separator(tab_dict, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="we", pady=(12, 4))

        ttk.Label(tab_dict, text=t("settings.mic_device")).grid(row=5, column=0, sticky="w", pady=4)
        devices = self._audio.list_devices()
        device_names = [t("settings.mic_auto")] + [f"[{d.index}] {d.name}" for d in devices]
        self._mic_var = tk.StringVar(master=self._window)
        if self._config.audio.mic_device_index is None:
            self._mic_var.set(t("settings.mic_auto"))
        else:
            for d in devices:
                if d.index == self._config.audio.mic_device_index:
                    self._mic_var.set(f"[{d.index}] {d.name}")
                    break
        mic_combo = ttk.Combobox(tab_dict, textvariable=self._mic_var, width=45, values=device_names)
        mic_combo.grid(row=5, column=1, sticky="we", pady=4, padx=(8, 0))

        ttk.Label(tab_dict, text=t("settings.noise_filter")).grid(row=6, column=0, sticky="nw", pady=4)
        self._vad_var = tk.IntVar(master=self._window, value=self._config.audio.vad_aggressiveness)
        vad_frame = ttk.Frame(tab_dict)
        vad_frame.grid(row=6, column=1, sticky="w", padx=(8, 0))
        for val, label in {0: t("settings.vad_0"), 1: t("settings.vad_1"),
                           2: t("settings.vad_2"), 3: t("settings.vad_3")}.items():
            ttk.Radiobutton(vad_frame, text=label, variable=self._vad_var, value=val).pack(anchor="w")

        ttk.Label(tab_dict, text=t("settings.pause_to_split")).grid(row=7, column=0, sticky="w", pady=(8, 4))
        self._silence_var = tk.IntVar(master=self._window, value=self._config.audio.silence_threshold_ms)
        silence_frame = ttk.Frame(tab_dict)
        silence_frame.grid(row=7, column=1, sticky="we", pady=(8, 4), padx=(8, 0))
        ttk.Scale(silence_frame, from_=500, to=5000, variable=self._silence_var,
                  orient="horizontal", length=250).pack(side="left")
        self._silence_label = ttk.Label(silence_frame, text=f"{self._silence_var.get()} ms")
        self._silence_label.pack(side="left", padx=8)
        self._silence_var.trace_add("write", lambda *_: self._silence_label.config(
            text=f"{self._silence_var.get()} ms"))

        # Feedback hint
        feedback_hint = tk.Label(
            tab_dict, text=t("settings.feedback_hint"),
            fg=self._dark_fg2 if self._is_dark else "#888888",
            bg=self._dark_bg if self._is_dark else tab_dict.winfo_toplevel().cget("bg"),
            font=("Segoe UI", 8), anchor="w", justify="left", wraplength=550,
        )
        feedback_hint.grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 0))

        tab_dict.columnconfigure(1, weight=1)

        # --- Tab 5: Interface & Telemetry (merged) ---
        tab_iface = ttk.Frame(notebook, padding=12)
        notebook.add(tab_iface, text=f"  {t('settings.tab_interface')}  ")

        self._sound_start_var = tk.BooleanVar(master=self._window, value=self._config.ui.sound_on_start)
        ttk.Checkbutton(tab_iface, text=t("settings.beep_start"),
                        variable=self._sound_start_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=2)

        self._sound_stop_var = tk.BooleanVar(master=self._window, value=self._config.ui.sound_on_stop)
        ttk.Checkbutton(tab_iface, text=t("settings.beep_stop"),
                        variable=self._sound_stop_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=2)

        self._notif_var = tk.BooleanVar(master=self._window, value=self._config.ui.show_notifications)
        ttk.Checkbutton(tab_iface, text=t("settings.show_notif"),
                        variable=self._notif_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=2)

        self._autostart_var = tk.BooleanVar(master=self._window, value=_get_autostart())
        ttk.Checkbutton(tab_iface, text=t("settings.autostart"),
                        variable=self._autostart_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Separator(tab_iface, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="we", pady=(12, 4))

        ttk.Label(tab_iface, text=t("settings.ui_language")).grid(row=5, column=0, sticky="w", pady=4)
        self._ui_lang_var = tk.StringVar(master=self._window, value=self._config.ui.language)
        ttk.Combobox(tab_iface, textvariable=self._ui_lang_var, width=15, values=[
            "uk", "en",
        ], state="readonly").grid(row=5, column=1, sticky="w", padx=(8, 0), pady=4)

        ttk.Label(tab_iface, text=t("settings.theme")).grid(row=6, column=0, sticky="w", pady=4)
        self._theme_var = tk.StringVar(master=self._window, value=self._load_theme())
        ttk.Combobox(tab_iface, textvariable=self._theme_var, width=15, values=[
            "auto", "light", "dark",
        ], state="readonly").grid(row=6, column=1, sticky="w", padx=(8, 0), pady=4)

        ttk.Separator(tab_iface, orient="horizontal").grid(
            row=7, column=0, columnspan=2, sticky="we", pady=(12, 4))

        self._telemetry_var = tk.BooleanVar(master=self._window, value=self._config.telemetry.enabled)
        ttk.Checkbutton(tab_iface, text=t("settings.telemetry_enabled"),
                        variable=self._telemetry_var).grid(row=8, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Label(tab_iface, text=t("settings.telemetry_hint"),
                  foreground="#888888", font=("Segoe UI", 8), wraplength=550,
                  ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(2, 0))

        tab_iface.columnconfigure(1, weight=1)

        self._window.mainloop()

    # --- Hotkey capture (uses `keyboard` library to detect all keys incl. Win) ---

    # ── Provider slot builder ─────────────────────────────────────────

    def _build_provider_slots(self, parent, slots_config: list[dict],
                              stt: bool = False, translation: bool = False) -> list[dict]:
        """Build 3 provider slots UI with best-practice layout.

        Each slot:
          ┌─ #1 ──────────────────────────────────────────────┐
          │  API Key: [****************************]  Groq ✓  │
          │  Service: [Groq        ▼]  Model: [whisper  ▼]    │
          └───────────────────────────────────────────────────┘

        Args:
            parent: ttk.Frame to build in.
            slots_config: list of 3 slot dicts from config.
            stt: If True, filter models for STT (whisper).
            translation: If True, include DeepL in provider list.
        """
        from .providers import detect_provider, fetch_models, ALL_STT_PROVIDERS, ALL_LLM_PROVIDERS

        # Hint
        ttk.Label(parent, text=t("settings.provider_fallback_hint"),
                  foreground="#888888", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 6))

        slot_widgets = []
        provider_list = list(ALL_STT_PROVIDERS) if stt else list(ALL_LLM_PROVIDERS)
        if translation:
            provider_list.insert(0, "DeepL")

        for idx in range(3):
            slot_data = slots_config[idx] if idx < len(slots_config) else {}

            frame = ttk.LabelFrame(parent, text=f"  #{idx + 1}  ", padding=(10, 6))
            frame.pack(fill="x", pady=(0, 4))

            # Row 1: "API Key:" label + entry + status
            row1 = ttk.Frame(frame)
            row1.pack(fill="x")

            ttk.Label(row1, text="API Key:", width=8).pack(side="left")
            api_var = tk.StringVar(master=self._window, value=slot_data.get("api_key", ""))
            key_entry = ttk.Entry(row1, textvariable=api_var, show="*")
            key_entry.pack(side="left", fill="x", expand=True, padx=(4, 8))

            usage_label = tk.Label(
                row1, text=t("settings.provider_not_connected"),
                fg=self._dark_fg2 if self._is_dark else "#888888",
                bg=self._dark_bg if self._is_dark else row1.winfo_toplevel().cget("bg"),
                font=("Segoe UI", 8), anchor="e", width=18,
            )
            usage_label.pack(side="right")

            # Row 2: Service dropdown + Model dropdown (with labels)
            row2 = ttk.Frame(frame)
            row2.pack(fill="x", pady=(6, 0))

            ttk.Label(row2, text="Service:", width=8).pack(side="left")
            provider_var = tk.StringVar(master=self._window, value=slot_data.get("provider", ""))
            provider_combo = ttk.Combobox(row2, textvariable=provider_var, values=provider_list,
                                          width=16, state="readonly")
            provider_combo.pack(side="left", padx=(4, 0))

            ttk.Label(row2, text="Model:", width=6).pack(side="left", padx=(12, 0))
            model_var = tk.StringVar(master=self._window, value=slot_data.get("model", ""))
            model_combo = ttk.Combobox(row2, textvariable=model_var, width=28)
            model_combo.pack(side="left", padx=(4, 0), fill="x", expand=True)

            # Auto-detect provider on key change + lock dropdown
            def _on_key_change(var=api_var, pvar=provider_var, pcombo=provider_combo,
                               mcombo=model_combo, mvar=model_var, ulabel=usage_label,
                               is_stt=stt):
                key = var.get().strip()
                if not key:
                    pvar.set("")
                    pcombo.config(state="readonly")  # unlock
                    mcombo["values"] = []
                    mvar.set("")
                    ulabel.config(text=t("settings.provider_not_connected"),
                                 fg=self._dark_fg2 or "#888888")
                    return
                info = detect_provider(key)
                if info:
                    pvar.set(info.name)
                    pcombo.config(state="disabled")  # lock — auto-detected
                    # Fetch models in background
                    def _fetch(base=info.base_url, k=key):
                        models = fetch_models(base, k, stt=is_stt)
                        if self._window:
                            def _update():
                                if models:
                                    mcombo.config(values=models)
                                    if not mvar.get():
                                        mvar.set(models[0])
                                ulabel.config(text=f"{info.name} \u2713", fg="#27ae60")
                            self._window.after(0, _update)
                    threading.Thread(target=_fetch, daemon=True).start()
                else:
                    # Unknown prefix — keep dropdown unlocked for manual selection
                    pcombo.config(state="readonly")
                    ulabel.config(text="? " + t("settings.provider_not_connected"),
                                 fg="#e67e22")

            api_var.trace_add("write", lambda *_, fn=_on_key_change: fn())

            # Init: if key already set, trigger detection
            if api_var.get().strip():
                self._window.after(100 + idx * 200, _on_key_change)

            slot_widgets.append({
                "api_key_var": api_var,
                "provider_var": provider_var,
                "provider_combo": provider_combo,
                "model_var": model_var,
                "usage_label": usage_label,
            })

        # Show/hide keys toggle
        show_var = tk.BooleanVar(master=self._window, value=False)

        def _toggle_show():
            show = show_var.get()
            for sw in slot_widgets:
                # Find entry in the parent frame
                pass
            # Walk all entries in LabelFrames
            for child in parent.winfo_children():
                if isinstance(child, ttk.LabelFrame):
                    for row in child.winfo_children():
                        if isinstance(row, ttk.Frame):
                            for w in row.winfo_children():
                                if isinstance(w, ttk.Entry):
                                    w.config(show="" if show else "*")

        ttk.Checkbutton(parent, text=t("settings.show_key"), variable=show_var,
                        command=_toggle_show).pack(anchor="w", pady=(4, 0))

        return slot_widgets

    def _start_hotkey_capture(self) -> None:
        """Enter hotkey recording mode using keyboard library for Win key support."""
        self._record_btn.config(text="Press keys...", state="disabled")
        self._hotkey_var.set("...")
        self._capture_target = "hotkey"
        self._run_keyboard_capture()

    def _start_ptt_capture(self) -> None:
        """Enter PTT key recording mode using keyboard library for Win key support."""
        self._ptt_record_btn.config(text="Press key...", state="disabled")
        self._ptt_var.set("...")
        self._capture_target = "ptt"
        self._run_keyboard_capture()

    def _run_keyboard_capture(self) -> None:
        """Run keyboard capture in a background thread; update UI via window.after()."""
        import keyboard as kb

        captured_keys: list[str] = []
        cancelled = False

        def _do_capture():
            nonlocal captured_keys, cancelled
            try:
                pressed: set[str] = set()
                max_combo: list[str] = []  # longest combo seen during this capture
                done = threading.Event()

                def on_press(event):
                    nonlocal cancelled
                    name = normalize_key_name(event.name)
                    if name == "esc":
                        cancelled = True
                        done.set()
                        return
                    pressed.add(name)
                    # Track the widest combo (most keys held at once)
                    combo = sorted(pressed, key=self._modifier_sort)
                    if len(combo) >= len(max_combo):
                        max_combo.clear()
                        max_combo.extend(combo)
                    self._window.after(0, self._update_capture_display, "+".join(combo))

                def on_release(event):
                    name = normalize_key_name(event.name)
                    pressed.discard(name)
                    # Finish only when ALL keys are released
                    if not pressed and max_combo:
                        done.set()

                hook_press = kb.on_press(on_press, suppress=True)
                hook_release = kb.on_release(on_release, suppress=True)

                # Wait up to 5 seconds for capture to complete
                done.wait(timeout=5.0)

                kb.unhook(hook_press)
                kb.unhook(hook_release)

                if cancelled or not max_combo:
                    captured_keys.clear()
                else:
                    captured_keys.extend(max_combo)
            except Exception as e:
                logger.error(f"Keyboard capture error: {e}")

            # Finalize on the tkinter thread
            if self._window:
                self._window.after(0, self._finish_capture, captured_keys, cancelled)

        thread = threading.Thread(target=_do_capture, daemon=True)
        thread.start()

    def _update_capture_display(self, combo: str) -> None:
        """Update the display field while capturing (called on tkinter thread)."""
        if self._capture_target == "ptt":
            self._ptt_var.set(combo)
        else:
            self._hotkey_var.set(combo)

    def _finish_capture(self, keys: list[str], cancelled: bool) -> None:
        """Finalize capture: set result or revert on cancel/timeout."""
        if self._capture_target == "ptt":
            if cancelled or not keys:
                self._ptt_var.set(self._config.ptt_key)
            else:
                self._ptt_var.set("+".join(keys))
            self._ptt_record_btn.config(text=t("settings.record_btn"), state="normal")
        else:
            if cancelled or not keys:
                self._hotkey_var.set(self._config.hotkey)
            else:
                self._hotkey_var.set("+".join(keys))
            self._record_btn.config(text=t("settings.record_btn"), state="normal")

    @staticmethod
    def _modifier_sort(key: str) -> int:
        """Sort modifiers first, then regular keys."""
        order = {"ctrl": 0, "alt": 1, "shift": 2, "win": 3}
        return order.get(key, 10)

    def _save(self) -> None:
        """Save settings to config and YAML file."""
        from .provider_manager import ProviderManager
        from .providers import detect_provider, get_provider_base_url

        # Provider slots → config
        def _read_slots(slot_widgets):
            result = []
            for sw in slot_widgets:
                key = sw["api_key_var"].get().strip()
                provider = sw["provider_var"].get().strip()
                model = sw["model_var"].get().strip()
                base_url = ""
                if key:
                    info = detect_provider(key)
                    if info:
                        base_url = info.base_url
                    elif provider:
                        base_url = get_provider_base_url(provider)
                result.append({"api_key": key, "provider": provider,
                               "base_url": base_url, "model": model})
            return result

        self._config.providers.stt = _read_slots(self._stt_slots)
        self._config.providers.llm = _read_slots(self._llm_slots)
        self._config.providers.translation = _read_slots(self._trans_slots)

        # Check for duplicate keys
        for name, slots in [("STT", self._config.providers.stt),
                            ("LLM", self._config.providers.llm),
                            ("Translation", self._config.providers.translation)]:
            warnings = ProviderManager.check_duplicate_keys(slots)
            if warnings:
                from tkinter import messagebox
                messagebox.showwarning(
                    t("settings.duplicate_key_warning"),
                    f"{name}: {'; '.join(warnings)}",
                )
                return  # Don't save

        # Backward compat: copy first STT key to groq config
        if self._config.providers.stt[0].get("api_key"):
            self._config.groq.api_key = self._config.providers.stt[0]["api_key"]
            self._config.groq.stt_model = self._config.providers.stt[0].get("model", "whisper-large-v3-turbo")
        if self._config.providers.llm[0].get("api_key"):
            self._config.groq.llm_model = self._config.providers.llm[0].get("model", "llama-3.3-70b-versatile")

        # Languages
        selected_langs = [code for code, var in self._lang_vars.items() if var.get()]
        self._config.groq.stt_language = ",".join(selected_langs) if selected_langs else None

        # Audio
        mic_str = self._mic_var.get()
        if mic_str == t("settings.mic_auto"):
            self._config.audio.mic_device_index = None
        else:
            try:
                idx = int(mic_str.split("]")[0].replace("[", ""))
                self._config.audio.mic_device_index = idx
            except (ValueError, IndexError):
                self._config.audio.mic_device_index = None
        self._config.audio.vad_aggressiveness = self._vad_var.get()
        self._config.audio.silence_threshold_ms = self._silence_var.get()

        # Dictation
        self._config.hotkey = self._hotkey_var.get().strip()
        self._config.hotkey_mode = self._hotkey_mode_var.get()
        self._config.ptt_key = self._ptt_var.get().strip()
        # text_injection.method is not exposed in UI, keep existing value
        self._config.normalization.enabled = self._normalize_var.get()
        self._config.ui.sound_on_start = self._sound_start_var.get()
        self._config.ui.sound_on_stop = self._sound_stop_var.get()
        self._config.ui.show_notifications = self._notif_var.get()
        self._config.ui.language = self._ui_lang_var.get()

        # Telemetry
        self._config.telemetry.enabled = self._telemetry_var.get()

        # Autostart
        _set_autostart(self._autostart_var.get())

        # Write YAML
        self._write_config()

        # Also update .env with API key
        self._write_env()

        # Save DeepL key
        self._save_deepl_key()

        if self._on_save:
            self._on_save()

        self._window.destroy()

        # Custom dark-aware restart dialog
        dlg = tk.Tk()
        dlg.title("AI Polyglot Kit")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.geometry("400x140")
        dlg.update_idletasks()
        x = (dlg.winfo_screenwidth() - 400) // 2
        y = (dlg.winfo_screenheight() - 140) // 2
        dlg.geometry(f"+{x}+{y}")

        try:
            import sv_ttk
            dlg.update()
            sv_ttk.set_theme("dark" if self._is_dark else "light")
            if self._is_dark:
                set_dwm_dark_title_bar(dlg)
        except ImportError:
            pass

        ttk.Label(dlg, text=t("settings.restart_prompt"),
                  font=("Segoe UI", 10), wraplength=360).pack(padx=20, pady=(20, 16))

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=(0, 16))

        result = {"restart": False}

        def on_yes():
            result["restart"] = True
            dlg.destroy()

        ttk.Button(btn_frame, text=t("settings.save"),
                   command=on_yes, style="Accent.TButton").pack(side="left", padx=8)
        ttk.Button(btn_frame, text=t("settings.cancel"),
                   command=dlg.destroy).pack(side="left", padx=8)

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.mainloop()

        if result["restart"] and self._on_save:
            self._on_save(restart=True)

    def _write_config(self) -> None:
        """Write current config to config.yaml using AppConfig.to_dict()."""
        from .config import APP_DIR
        APP_DIR.mkdir(parents=True, exist_ok=True)
        save_path = APP_DIR / "config.yaml"
        try:
            data = self._config.to_dict()
            with open(save_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            logger.info(f"Config saved to {save_path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            messagebox.showerror("Error", f"Failed to save config: {e}")

    def _write_env(self) -> None:
        """Write API key to .env file in APPDATA (works for both source and exe)."""
        from .config import APP_DIR
        APP_DIR.mkdir(parents=True, exist_ok=True)
        env_path = APP_DIR / ".env"
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"GROQ_API_KEY={self._config.groq.api_key}\n")
            logger.info(f"API key saved to {env_path}")
        except Exception as e:
            logger.error(f"Failed to save .env: {e}")

    def _load_theme(self) -> str:
        """Load theme preference from translate_settings.json."""
        return load_translate_settings().get("theme", "auto")

    def _save_deepl_key(self) -> None:
        """Save all DeepL API keys and theme to translate_settings.json."""
        keys = [v.get().strip() for v in self._deepl_key_vars]
        save_translate_settings({
            "deepl_keys": [k for k in keys if k],
            "theme": self._theme_var.get(),
        })
        logger.info("DeepL keys + theme saved")

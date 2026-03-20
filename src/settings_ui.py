"""Settings GUI window using tkinter."""

import logging
import sys
import threading
import tkinter as tk
import winreg
from tkinter import ttk, messagebox
from pathlib import Path

import yaml

from .config import AppConfig, AudioConfig, APP_NAME
from .audio_capture import AudioCapture
from .i18n import t

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


def _set_autostart(enabled: bool) -> None:
    """Add or remove app from Windows startup registry."""
    try:
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
        self._window.geometry("520x480")
        self._window.resizable(False, False)

        # Center on screen
        self._window.update_idletasks()
        x = (self._window.winfo_screenwidth() - 520) // 2
        y = (self._window.winfo_screenheight() - 480) // 2
        self._window.geometry(f"+{x}+{y}")

        # Always on top
        self._window.attributes("-topmost", True)

        # Notebook (tabs)
        notebook = ttk.Notebook(self._window)
        notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        # --- Tab 1: Groq API ---
        tab_api = ttk.Frame(notebook, padding=12)
        notebook.add(tab_api, text=f"  {t('settings.tab_api')}  ")

        ttk.Label(tab_api, text=t("settings.api_key")).grid(row=0, column=0, sticky="w", pady=4)
        self._api_key_var = tk.StringVar(master=self._window, value=self._config.groq.api_key)
        api_entry = ttk.Entry(tab_api, textvariable=self._api_key_var, width=55, show="*")
        api_entry.grid(row=0, column=1, sticky="we", pady=4, padx=(8, 0))

        self._show_key_var = tk.BooleanVar(master=self._window, value=False)
        ttk.Checkbutton(
            tab_api, text=t("settings.show_key"), variable=self._show_key_var,
            command=lambda: api_entry.config(show="" if self._show_key_var.get() else "*"),
        ).grid(row=1, column=1, sticky="w", padx=(8, 0))

        # API key hint
        hint_label = ttk.Label(
            tab_api, text=t("settings.api_hint"),
            foreground="#888888",
            font=("Segoe UI", 8), wraplength=400,
        )
        hint_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(tab_api, text=t("settings.stt_model")).grid(row=3, column=0, sticky="w", pady=4)
        self._stt_model_var = tk.StringVar(master=self._window, value=self._config.groq.stt_model)
        stt_combo = ttk.Combobox(tab_api, textvariable=self._stt_model_var, width=35, values=[
            "whisper-large-v3-turbo",
            "whisper-large-v3",
        ])
        stt_combo.grid(row=3, column=1, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(tab_api, text=t("settings.llm_model")).grid(row=4, column=0, sticky="w", pady=4)
        self._llm_model_var = tk.StringVar(master=self._window, value=self._config.groq.llm_model)
        llm_combo = ttk.Combobox(tab_api, textvariable=self._llm_model_var, width=35, values=[
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "gemma2-9b-it",
        ])
        llm_combo.grid(row=4, column=1, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(tab_api, text=t("settings.language")).grid(row=5, column=0, sticky="nw", pady=4)
        lang_frame = ttk.Frame(tab_api)
        lang_frame.grid(row=5, column=1, sticky="w", padx=(8, 0), pady=4)

        # All Whisper-supported languages
        self._all_languages = [
            ("uk", "Українська"), ("ru", "Русский"), ("en", "English"),
            ("de", "Deutsch"), ("fr", "Français"), ("es", "Español"),
            ("pl", "Polski"), ("it", "Italiano"), ("pt", "Português"),
            ("nl", "Nederlands"), ("tr", "Türkçe"), ("cs", "Čeština"),
            ("ja", "日本語"), ("zh", "中文"), ("ko", "한국어"),
        ]

        # Parse current language config (comma-separated or single)
        current_langs = set()
        if self._config.groq.stt_language:
            current_langs = {l.strip() for l in self._config.groq.stt_language.split(",")}

        self._lang_vars: dict[str, tk.BooleanVar] = {}
        for i, (code, name) in enumerate(self._all_languages):
            var = tk.BooleanVar(master=self._window, value=(code in current_langs) if current_langs else False)
            self._lang_vars[code] = var
            col = i % 3
            row = i // 3
            ttk.Checkbutton(lang_frame, text=f"{name}", variable=var).grid(
                row=row, column=col, sticky="w", padx=(0, 12),
            )

        ttk.Label(tab_api, text=t("settings.language_hint"),
                  foreground="gray").grid(row=6, column=0, columnspan=2, sticky="w", padx=(0, 0))

        tab_api.columnconfigure(1, weight=1)

        # --- Tab 2: Audio ---
        tab_audio = ttk.Frame(notebook, padding=12)
        notebook.add(tab_audio, text=f"  {t('settings.tab_audio')}  ")

        ttk.Label(tab_audio, text=t("settings.mic_device")).grid(row=0, column=0, sticky="w", pady=4)
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
        mic_combo = ttk.Combobox(tab_audio, textvariable=self._mic_var, width=45, values=device_names)
        mic_combo.grid(row=0, column=1, sticky="we", pady=4, padx=(8, 0))

        ttk.Label(tab_audio, text=t("settings.noise_filter")).grid(row=1, column=0, sticky="nw", pady=4)
        self._vad_var = tk.IntVar(master=self._window, value=self._config.audio.vad_aggressiveness)
        vad_frame = ttk.Frame(tab_audio)
        vad_frame.grid(row=1, column=1, sticky="w", padx=(8, 0))
        vad_labels = {
            0: t("settings.vad_0"),
            1: t("settings.vad_1"),
            2: t("settings.vad_2"),
            3: t("settings.vad_3"),
        }
        for val, label in vad_labels.items():
            ttk.Radiobutton(vad_frame, text=label, variable=self._vad_var, value=val).pack(anchor="w")

        ttk.Label(tab_audio, text=t("settings.pause_to_split")).grid(row=2, column=0, sticky="w", pady=(12, 4))
        self._silence_var = tk.IntVar(master=self._window, value=self._config.audio.silence_threshold_ms)
        silence_frame = ttk.Frame(tab_audio)
        silence_frame.grid(row=2, column=1, sticky="we", pady=(12, 4), padx=(8, 0))
        ttk.Scale(silence_frame, from_=500, to=5000, variable=self._silence_var, orient="horizontal", length=250).pack(
            side="left"
        )
        self._silence_label = ttk.Label(silence_frame, text=f"{self._silence_var.get()} ms")
        self._silence_label.pack(side="left", padx=8)
        self._silence_var.trace_add("write", lambda *_: self._silence_label.config(
            text=f"{self._silence_var.get()} ms"
        ))
        ttk.Label(tab_audio, text=t("settings.pause_hint"),
                  foreground="gray").grid(row=3, column=1, sticky="w", padx=(8, 0))

        tab_audio.columnconfigure(1, weight=1)

        # --- Tab 3: Dictation ---
        tab_dict = ttk.Frame(notebook, padding=12)
        notebook.add(tab_dict, text=f"  {t('settings.tab_dictation')}  ")

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

        self._normalize_var = tk.BooleanVar(master=self._window, value=self._config.normalization.enabled)
        ttk.Checkbutton(tab_dict, text=t("settings.normalize_check"),
                        variable=self._normalize_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=8)

        self._sound_start_var = tk.BooleanVar(master=self._window, value=self._config.ui.sound_on_start)
        ttk.Checkbutton(tab_dict, text=t("settings.beep_start"),
                        variable=self._sound_start_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=2)

        self._sound_stop_var = tk.BooleanVar(master=self._window, value=self._config.ui.sound_on_stop)
        ttk.Checkbutton(tab_dict, text=t("settings.beep_stop"),
                        variable=self._sound_stop_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=2)

        self._notif_var = tk.BooleanVar(master=self._window, value=self._config.ui.show_notifications)
        ttk.Checkbutton(tab_dict, text=t("settings.show_notif"),
                        variable=self._notif_var).grid(row=8, column=0, columnspan=2, sticky="w", pady=2)

        # Double-tap feedback hint
        feedback_hint = tk.Label(
            tab_dict, text=t("settings.feedback_hint"),
            fg="#888888", font=("Segoe UI", 8), anchor="w", justify="left", wraplength=450,
        )
        feedback_hint.grid(row=9, column=0, columnspan=2, sticky="w", pady=(12, 4))

        self._autostart_var = tk.BooleanVar(master=self._window, value=_get_autostart())
        ttk.Checkbutton(tab_dict, text=t("settings.autostart"),
                        variable=self._autostart_var).grid(row=10, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Label(tab_dict, text=t("settings.ui_language")).grid(row=11, column=0, sticky="w", pady=(12, 4))
        self._ui_lang_var = tk.StringVar(master=self._window, value=self._config.ui.language)
        ui_lang_combo = ttk.Combobox(tab_dict, textvariable=self._ui_lang_var, width=15, values=[
            "uk", "en",
        ], state="readonly")
        ui_lang_combo.grid(row=11, column=1, sticky="w", padx=(8, 0), pady=(12, 4))

        tab_dict.columnconfigure(1, weight=1)

        # --- Tab 4: Telemetry ---
        tab_tel = ttk.Frame(notebook, padding=12)
        notebook.add(tab_tel, text=f"  {t('settings.tab_telemetry')}  ")

        self._telemetry_var = tk.BooleanVar(
            master=self._window, value=self._config.telemetry.enabled
        )
        ttk.Checkbutton(
            tab_tel, text=t("settings.telemetry_enabled"),
            variable=self._telemetry_var,
        ).grid(row=0, column=0, sticky="w", pady=(4, 0))

        ttk.Label(
            tab_tel, text=t("settings.telemetry_hint"),
            foreground="#888888", font=("Segoe UI", 8),
            wraplength=450,
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        tab_tel.columnconfigure(0, weight=1)

        # --- Buttons ---
        btn_frame = ttk.Frame(self._window)
        btn_frame.pack(fill="x", padx=8, pady=8)

        ttk.Button(btn_frame, text=t("settings.save"), command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_frame, text=t("settings.cancel"), command=self._window.destroy).pack(side="right", padx=4)

        self._window.mainloop()

    # --- Hotkey capture (uses `keyboard` library to detect all keys incl. Win) ---

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
                    name = self._normalize_kb_name(event.name)
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
                    name = self._normalize_kb_name(event.name)
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
    def _normalize_kb_name(name: str) -> str:
        """Normalize keyboard library key name to a consistent format."""
        mapping = {
            "left windows": "win", "right windows": "win",
            "left ctrl": "ctrl", "right ctrl": "ctrl",
            "left alt": "alt", "right alt": "alt",
            "left shift": "shift", "right shift": "shift",
            "caps lock": "caps lock",
            "print screen": "print screen",
            "scroll lock": "scroll lock",
            "page up": "page up", "page down": "page down",
        }
        low = name.lower()
        return mapping.get(low, low)

    @staticmethod
    def _modifier_sort(key: str) -> int:
        """Sort modifiers first, then regular keys."""
        order = {"ctrl": 0, "alt": 1, "shift": 2, "win": 3}
        return order.get(key, 10)

    def _save(self) -> None:
        """Save settings to config and YAML file."""
        # Groq
        self._config.groq.api_key = self._api_key_var.get().strip()
        self._config.groq.stt_model = self._stt_model_var.get().strip()
        self._config.groq.llm_model = self._llm_model_var.get().strip()
        # Languages: comma-separated selected codes, or None for auto
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

        if self._on_save:
            self._on_save()

        self._window.destroy()
        restart = messagebox.askyesno(
            "Groq Dictation",
            t("settings.restart_prompt"),
        )
        if restart and self._on_save:
            self._on_save(restart=True)

    def _write_config(self) -> None:
        """Write current config to config.yaml."""
        data = {
            "groq": {
                "api_key": "",  # Don't save API key in yaml, use .env
                "stt_model": self._config.groq.stt_model,
                "llm_model": self._config.groq.llm_model,
                "stt_language": self._config.groq.stt_language,
                "stt_temperature": self._config.groq.stt_temperature,
            },
            "audio": {
                "mic_device_index": self._config.audio.mic_device_index,
                "sample_rate": self._config.audio.sample_rate,
                "frame_duration_ms": self._config.audio.frame_duration_ms,
                "vad_aggressiveness": self._config.audio.vad_aggressiveness,
                "silence_threshold_ms": self._config.audio.silence_threshold_ms,
                "min_chunk_duration_ms": self._config.audio.min_chunk_duration_ms,
                "max_chunk_duration_s": self._config.audio.max_chunk_duration_s,
                "gain": self._config.audio.gain,
            },
            "hotkey": self._config.hotkey,
            "hotkey_mode": self._config.hotkey_mode,
            "ptt_key": self._config.ptt_key,
            "normalization": {
                "enabled": self._config.normalization.enabled,
                "prompt": self._config.normalization.prompt,
                "known_terms": self._config.normalization.known_terms,
                "temperature": self._config.normalization.temperature,
            },
            "text_injection": {
                "method": self._config.text_injection.method,
                "typing_delay_ms": self._config.text_injection.typing_delay_ms,
                "backspace_batch_size": self._config.text_injection.backspace_batch_size,
            },
            "telemetry": {
                "enabled": self._config.telemetry.enabled,
            },
            "ui": {
                "show_notifications": self._config.ui.show_notifications,
                "sound_on_start": self._config.ui.sound_on_start,
                "sound_on_stop": self._config.ui.sound_on_stop,
                "language": self._config.ui.language,
            },
            "logging": {
                "level": self._config.logging.level,
                "file": self._config.logging.file,
                "max_size_mb": self._config.logging.max_size_mb,
                "backup_count": self._config.logging.backup_count,
            },
        }
        from .config import APP_DIR
        APP_DIR.mkdir(parents=True, exist_ok=True)
        save_path = APP_DIR / "config.yaml"
        try:
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

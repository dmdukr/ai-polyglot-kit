"""System tray application for AI Polyglot Kit."""

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import keyboard
import pyperclip
from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from .config import AppConfig
from .engine import DictationEngine, DictationState
from .i18n import t
from .translate_engine import TranslateEngine
from .translate_overlay import TranslateOverlay
from .translate_server import TranslateServer
from .updater import Updater
from .utils import normalize_key_name

logger = logging.getLogger(__name__)

# Icon colors per state
STATE_COLORS = {
    DictationState.IDLE: "#888888",
    DictationState.RECORDING: "#FF0000",
    DictationState.PROCESSING: "#FFA500",
    DictationState.TYPING: "#00AA00",
    DictationState.ERROR: "#FF4444",
}


def _state_tooltip(state: DictationState) -> str:
    from .config import APP_VERSION
    from .i18n import t

    _keys = {
        DictationState.IDLE: "tray.ready",
        DictationState.RECORDING: "tray.recording",
        DictationState.PROCESSING: "tray.processing",
        DictationState.TYPING: "tray.typing",
        DictationState.ERROR: "tray.error",
    }
    return f"{t('tray.title')} v{APP_VERSION} — {t(_keys.get(state, 'tray.ready'))}"


def _create_mic_icon(color: str, size: int = 64) -> Image.Image:
    """Generate a microphone icon programmatically.

    Returns a pre-converted RGBA image at multiple ICO sizes to avoid
    PIL Image.convert/resize calls at runtime (not thread-safe, causes segfault
    when pystray updates icon from a non-main thread).
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Microphone head (rounded rectangle)
    draw.rounded_rectangle([20, 6, 44, 34], radius=8, fill=color)
    # Stem
    draw.rectangle([29, 34, 35, 44], fill=color)
    # Arc (stand)
    draw.arc([14, 20, 50, 48], 0, 180, fill=color, width=3)
    # Base
    draw.rectangle([24, 44, 40, 48], fill=color)

    # Recording indicator (red dot) for recording state
    if color == "#FF0000":
        draw.ellipse([46, 2, 60, 16], fill="#FF0000", outline="#FFFFFF", width=2)

    # Force RGBA conversion now (thread-safe at init time)
    img = img.convert("RGBA")
    return img


class TrayApp:
    """System tray application managing the AI Polyglot Kit lifecycle."""

    def __init__(self, engine: DictationEngine, config: AppConfig):
        self._engine = engine
        self._config = config
        self._icon: Icon | None = None
        self._icons: dict[DictationState, Image.Image] = {}
        self._known_devices: set[str] = set()
        self._suggested_device = None
        self._ptt_suppressed = False
        self._ptt_is_hold = False
        self._ptt_press_time = 0.0

        # Pre-render icons for each state
        for state, color in STATE_COLORS.items():
            self._icons[state] = _create_mic_icon(color)

        # Register engine callbacks
        self._engine.set_state_callback(self._on_state_changed)
        self._engine.set_error_callback(self._on_error)
        self._engine.set_quota_callback(self._on_quota_warning)
        self._engine.set_suppress_ptt_callback(self._on_suppress_ptt)

        # Auto-updater
        self._updater = Updater(on_update_available=self._on_update_available)
        self._pending_update: dict | None = None

        # Quick translate (double Ctrl+C)
        self._translator = TranslateOverlay(config.groq, self._engine.get_provider_manager())
        self._last_ctrl_c_time: float = 0

    def run(self) -> None:
        """Run the tray app. Blocks the main thread."""
        self._icon = Icon(
            "ai-polyglot-kit",
            self._icons[DictationState.IDLE],
            _state_tooltip(DictationState.IDLE),
            menu=self._create_menu(),
        )
        self._icon.run(setup=self._setup)

    def _setup(self, icon: Icon) -> None:
        """Called in a separate thread after icon is ready."""
        icon.visible = True
        logger.info(f"Tray app started, hotkey: {self._config.hotkey}")

        # Tk host starts lazily on first GUI open (Settings/Translate/About)
        # NOT started here to avoid Tk + pystray message loop conflicts during recording

        # Register hotkeys
        self._register_hotkeys()

        # Ctrl+C for quick translate is registered inside _register_hotkeys()

        # Select mic device (but don't open stream — opened on demand at key press)
        def _init_mic():
            try:
                ac = self._engine.get_audio_capture()
                if self._config.audio.mic_device_index is None:
                    ac.select_device(None)  # auto-select best (prefers headset)
                else:
                    ac.select_device(self._config.audio.mic_device_index)
                logger.info("Mic device selected (stream opens on demand)")
                self._update_mic_tooltip()
                self._known_devices = ac.get_known_device_names()
                self._start_device_watcher()
            except Exception as e:
                logger.warning(f"Mic init failed: {e}")

        threading.Thread(target=_init_mic, daemon=True).start()

        # Start auto-updater
        self._updater.start()

        # Start translation HTTP server for browser extensions
        engine_te = TranslateEngine(
            provider_manager=self._engine.get_provider_manager(),
            groq_config=self._config.groq,
        )
        self._translate_server = TranslateServer(engine_te, self._config.server_port)
        self._translate_server.start()

    def _register_hotkeys(self) -> None:
        """Register hotkeys based on config mode."""
        try:
            keyboard.unhook_all()
        except Exception:
            pass

        self._ptt_keys_pressed: set[str] = set()
        self._ptt_active = False

        mode = self._config.hotkey_mode
        try:
            if mode == "toggle":
                # Toggle mode: single hotkey for start/stop
                keyboard.add_hotkey(
                    self._config.hotkey,
                    self._engine.toggle,
                    suppress=True,
                )
                logger.info(f"Toggle hotkey '{self._config.hotkey}' registered")

            elif mode == "hold":
                # Hold mode: hold combo to record, release to stop
                # Uses the same hotkey as toggle mode (one key, two modes)
                ptt = self._config.hotkey
                self._ptt_combo_keys = set(k.strip().lower() for k in ptt.split("+"))
                # Hook all keyboard events for PTT tracking
                keyboard.hook(self._on_ptt_event, suppress=False)
                logger.info(f"Hold hotkey '{ptt}' registered (keys: {self._ptt_combo_keys})")

        except Exception as e:
            logger.error(f"Failed to register hotkeys: {e}")
            self._on_error(f"Hotkey registration failed: {e}")

        # Re-register Ctrl+C for quick translate (unhook_all removes it)
        keyboard.add_hotkey("ctrl+c", self._on_ctrl_c, suppress=False)

    def _on_ptt_event(self, event) -> None:
        """Track key presses/releases for push-to-talk combo.

        Algorithm:
        - DOWN: start 0.5s timer. If still held after 0.5s → HOLD → start recording.
        - UP before 0.5s: TAP → increment counter. Two taps within 0.5s → feedback.
        - UP after hold: stop recording.
        """
        # Skip during feedback capture (grab_typed_text sends synthetic keys)
        if self._ptt_suppressed:
            return

        raw_name = event.name if hasattr(event, "name") else ""
        key_name = normalize_key_name(raw_name) if raw_name else ""
        if not key_name:
            return

        if event.event_type == "down":
            self._ptt_keys_pressed.add(key_name)
            if self._ptt_combo_keys.issubset(self._ptt_keys_pressed) and not self._ptt_active:
                self._ptt_active = True
                self._ptt_is_hold = False
                self._ptt_press_time = time.monotonic()

                # Start hold timer — open mic at 0.3s (warm up), start recording at 0.5s
                hold_id = time.monotonic()
                self._ptt_hold_id = hold_id

                def _hold_check():
                    # Wait 0.3s then open mic (gives 0.2s to warm up before recording)
                    time.sleep(0.3)
                    if not (self._ptt_active and self._ptt_hold_id == hold_id):
                        return  # released before 0.3s — it's a tap, don't open mic
                    ac = self._engine.get_audio_capture()
                    if not ac.is_running:
                        try:
                            ac.start()
                            logger.info("Mic opened (hold > 0.3s, warming up)")
                        except Exception as e:
                            logger.warning(f"Mic open failed: {e}")
                    # Wait remaining 0.2s then start recording
                    time.sleep(0.2)
                    if self._ptt_active and self._ptt_hold_id == hold_id:
                        self._ptt_is_hold = True
                        logger.info("HOLD detected — starting recording")
                        self._engine.start_if_idle()

                threading.Thread(target=_hold_check, daemon=True).start()

        elif event.event_type == "up":
            was_in_combo = key_name in self._ptt_combo_keys
            self._ptt_keys_pressed.discard(key_name)
            if self._ptt_active and was_in_combo:
                self._ptt_active = False
                self._ptt_hold_id = 0  # cancel pending hold timer
                if self._ptt_is_hold:
                    # Was a hold — stop recording
                    self._ptt_is_hold = False
                    logger.info("HOLD released — stopping recording")
                    threading.Thread(target=self._engine.stop_if_recording, daemon=True).start()
                else:
                    # Was a tap (released before 0.3s — mic was never opened)
                    logger.info("TAP detected")
                    self._engine.on_tap()

    def _create_menu(self) -> Menu:
        """Build the context menu."""
        return Menu(
            MenuItem(
                "Start / Stop Dictation",
                self._on_toggle_click,
                default=True,  # left-click triggers this action
            ),
            Menu.SEPARATOR,
            MenuItem(
                "Microphone",
                self._create_mic_submenu(),
            ),
            Menu.SEPARATOR,
            MenuItem(
                t("tray.settings"),
                self._on_settings_click,
            ),
            MenuItem(
                t("tray.open_logs"),
                self._on_log_click,
            ),
            MenuItem(
                t("tray.open_profile"),
                self._on_profile_click,
            ),
            Menu.SEPARATOR,
            MenuItem(
                lambda text: (
                    t("tray.update_install", version=self._pending_update["version"])
                    if self._pending_update
                    else t("tray.update_check")
                ),
                self._on_update_click,
            ),
            MenuItem(
                "Restart",
                self._on_restart_click,
            ),
            MenuItem(
                t("tray.about"),
                self._on_about_click,
            ),
            Menu.SEPARATOR,
            MenuItem(
                t("tray.quit"),
                self._on_quit_click,
            ),
        )

    def _create_mic_submenu(self) -> Menu:
        """Build microphone selection submenu."""
        devices = self._engine.get_audio_capture().list_devices()
        if not devices:
            return Menu(MenuItem("No microphones found", None, enabled=False))

        items = []
        current = self._config.audio.mic_device_index
        for dev in devices:
            is_selected = dev.index == current
            items.append(
                MenuItem(
                    f"{'* ' if is_selected else ''}{dev.name}",
                    self._make_mic_selector(dev.index),
                )
            )

        items.append(Menu.SEPARATOR)
        items.append(
            MenuItem(
                f"{'* ' if current is None else ''}Auto (loudest)",
                self._make_mic_selector(None),
            )
        )
        return Menu(*items)

    def _make_mic_selector(self, device_index: int | None) -> Callable:
        """Create a callback for mic selection."""

        def select(_icon=None, _item=None):
            self._config.audio.mic_device_index = device_index
            self._engine.get_audio_capture().select_device(device_index)
            name = f"device {device_index}" if device_index is not None else "auto"
            logger.info(f"Microphone switched to: {name}")
            if self._icon and self._config.ui.show_notifications:
                self._icon.notify(f"Microphone: {name}", t("tray.title"))
            # Refresh menu
            if self._icon:
                self._icon.menu = self._create_menu()

        return select

    def _is_recording(self) -> bool:
        """Check if engine is currently recording (to suppress noisy notifications)."""
        return self._engine.state in (DictationState.RECORDING, DictationState.PROCESSING)

    def _on_state_changed(self, state: DictationState) -> None:
        """Update icon and tooltip on state change. No sound notifications during recording."""
        if self._icon:
            try:
                self._icon.icon = self._icons.get(state, self._icons[DictationState.IDLE])
                tooltip = _state_tooltip(state)
                try:
                    mic_name = self._engine._audio.get_active_device_name()
                    if mic_name:
                        tooltip += f"\nMic: {mic_name}"
                except Exception:
                    pass
                self._icon.title = tooltip
            except Exception as e:
                logger.warning(f"Icon update failed (non-critical): {e}")

            # Show pending notifications when recording ends
            if state == DictationState.IDLE:
                pending = getattr(self, "_pending_notification", None)
                if pending:
                    self._icon.notify(pending, t("tray.title"))
                    self._pending_notification = None

    def _on_error(self, message: str) -> None:
        """Show error notification (only when not recording)."""
        logger.error(f"Tray error notification: {message}")
        if self._icon and self._config.ui.show_notifications and not self._is_recording():
            self._icon.notify(f"Error: {message}", t("tray.title"))

    def _on_quota_warning(self, remaining: int, limit: int) -> None:
        """Show quota warning (only when not recording)."""
        minutes = remaining // 60
        total_min = limit // 60
        msg = f"Groq free quota: {minutes} min remaining (of {total_min} min)"
        logger.warning(msg)
        # Defer notification until recording stops
        if self._icon:
            if not self._is_recording():
                self._icon.notify(msg, t("tray.title"))
            else:
                # Queue it for after recording
                self._pending_notification = msg

    def _update_mic_tooltip(self) -> None:
        """Update tray tooltip with current mic name."""
        if self._icon:
            try:
                mic_name = self._engine.get_audio_capture().get_active_device_name()
                self._icon.title = f"{_state_tooltip(DictationState.IDLE)}\n{t('tray.mic')}: {mic_name}"
            except Exception:
                pass

    def _start_device_watcher(self) -> None:
        """Periodically check for new headset/bluetooth devices and notify user."""

        def _watch():
            while True:
                time.sleep(10)  # check every 10 seconds
                try:
                    ac = self._engine.get_audio_capture()
                    new_dev = ac.detect_new_headset(self._known_devices)
                    if new_dev:
                        # Update known set
                        self._known_devices = ac.get_known_device_names()
                        # Store the suggested device for menu action
                        self._suggested_device = new_dev
                        logger.info(f"New headset detected: {new_dev.name} (device {new_dev.index})")
                        if self._icon and not self._is_recording():
                            self._icon.notify(
                                f"Headset detected: {new_dev.name}\nRight-click tray → switch mic",
                                t("tray.title"),
                            )
                    else:
                        # Update known set (devices may have disappeared)
                        current = ac.get_known_device_names()
                        if current != self._known_devices:
                            self._known_devices = current
                except Exception as e:
                    logger.debug(f"Device watcher error: {e}")

        watcher_thread = threading.Thread(target=_watch, name="DeviceWatcher", daemon=True)
        watcher_thread.start()
        logger.info("Device watcher started (10s interval)")

    def _on_suppress_ptt(self, suppress: bool) -> None:
        """Suppress or unsuppress PTT hook (during feedback text grab)."""
        self._ptt_suppressed = suppress
        if not suppress:
            # Clear key state to avoid stuck keys from synthetic input
            self._ptt_keys_pressed.clear()
            self._ptt_active = False
        logger.debug("PTT suppressed: %s", suppress)

    def _on_toggle_click(self, _icon=None, _item=None) -> None:
        self._engine.toggle()

    def _on_settings_click(self, _icon=None, _item=None) -> None:
        """Open GUI settings window (PyWebView preferred, tkinter fallback)."""
        logger.info("Settings click: opening settings window")
        try:
            from .ui.settings_window import show_settings

            logger.info("Settings click: using PyWebView")
            show_settings(
                self._config,
                self._engine.get_audio_capture(),
                self._on_settings_saved,
            )
            logger.info("Settings click: show_settings() returned (queued)")
        except ImportError:
            logger.info("Settings click: pywebview not available, using tkinter")
            from .settings_ui import SettingsWindow

            settings = SettingsWindow(
                self._config,
                self._engine.get_audio_capture(),
                on_save=self._on_settings_saved,
            )
            settings.show()
        except Exception:
            logger.exception("Settings click: FAILED")

    def _on_settings_saved(self, restart: bool = False) -> None:
        """Re-register hotkeys and update mic after settings change."""
        if restart:
            logger.info("Restarting after settings change...")
            self._on_restart_click()
            return
        logger.info("Applying new settings...")
        self._register_hotkeys()
        # Update mic selection — only re-probe if device changed or set to auto
        ac = self._engine.get_audio_capture()
        new_idx = self._config.audio.mic_device_index
        if new_idx is not None:
            # Explicit device — just set it (no probing)
            ac._device_index = new_idx
            logger.info("Mic set to device %d (no re-probe)", new_idx)
        # If auto (None) — don't re-probe on save, keep current selection
        # Re-probe happens on next app start or mic disconnect
        # Refresh menu
        if self._icon:
            self._icon.menu = self._create_menu()

    def _on_log_click(self, _icon=None, _item=None) -> None:
        """Open log file in default editor."""
        import subprocess

        from .config import APP_DIR

        log_path = APP_DIR / "logs" / self._config.logging.file
        logger.info(f"Opening log: {log_path}")
        try:
            if log_path.exists():
                subprocess.Popen(["notepad.exe", str(log_path)])
            else:
                logger.warning(f"Log file not found: {log_path}")
        except Exception as e:
            logger.error(f"Failed to open log: {e}")

    def _on_profile_click(self, _icon=None, _item=None) -> None:
        """Open user profile JSON in default editor."""
        import subprocess

        from .user_profile import PROFILE_PATH

        logger.info(f"Opening profile: {PROFILE_PATH}")
        try:
            if PROFILE_PATH.exists():
                subprocess.Popen(["notepad.exe", str(PROFILE_PATH)])
            else:
                logger.warning("Profile file not found, creating empty")
                self._engine._profile.save(force=True)
                subprocess.Popen(["notepad.exe", str(PROFILE_PATH)])
        except Exception as e:
            logger.error(f"Failed to open profile: {e}")

    def _on_ctrl_c(self) -> None:
        """Handle Ctrl+C — detect double press for quick translate."""
        now = time.monotonic()
        gap = now - self._last_ctrl_c_time
        self._last_ctrl_c_time = now

        if gap < 0.5:
            # Double Ctrl+C detected — translate clipboard
            self._last_ctrl_c_time = 0  # reset to avoid triple trigger
            logger.info("Double Ctrl+C — opening translator")

            # Small delay for clipboard to update from first Ctrl+C
            def _do_translate():
                time.sleep(0.1)
                try:
                    text = pyperclip.paste()
                    if text and text.strip():
                        self._translator.show(text)
                    else:
                        logger.info("Clipboard empty, skipping translate")
                except Exception as e:
                    logger.warning(f"Translate failed: {e}")

            threading.Thread(target=_do_translate, daemon=True).start()

    def _on_update_available(self, version: str, download_url: str) -> None:
        """Called by Updater when a new version is found."""
        self._pending_update = {"version": version, "url": download_url}
        logger.info(f"Update available: v{version}")
        if self._icon:
            try:
                self._icon.update_menu()
            except Exception:
                pass
            self._icon.notify(
                t("notify.update_available", version=version),
                "AI Polyglot Kit",
            )

    def _on_update_click(self, _icon=None, _item=None) -> None:
        """Handle update menu click."""
        if self._pending_update:
            logger.info(f"User accepted update to v{self._pending_update['version']}")
            threading.Thread(
                target=self._updater.download_and_install,
                args=(self._pending_update["url"],),
                daemon=True,
            ).start()
        else:
            # Manual check
            def _check():
                result = self._updater.check_now()
                if not result and self._icon:
                    self._icon.notify("No updates available", "AI Polyglot Kit")

            threading.Thread(target=_check, daemon=True).start()

    def _on_restart_click(self, _icon=None, _item=None) -> None:
        """Restart the application (re-exec the process)."""
        import subprocess
        import sys

        from .main import release_single_instance

        logger.info("Restarting application...")
        self._engine.shutdown()
        keyboard.unhook_all()
        # Release mutex so new process can start
        release_single_instance()
        # Launch new instance
        subprocess.Popen([sys.executable, "-m", "src"], cwd=str(Path(__file__).parent.parent))
        if self._icon:
            self._icon.stop()

    def _on_about_click(self, _icon=None, _item=None) -> None:
        """Show About dialog as Toplevel on shared Tk host."""
        import tkinter as tk

        from . import tk_host
        from .config import APP_VERSION
        from .utils import set_dwm_dark_title_bar

        def _show():
            win = tk.Toplevel(tk_host.get_root())
            win.title(t("tray.about"))
            win.resizable(False, False)
            win.geometry("300x200")

            is_dark = tk_host.is_dark()
            bg = "#1c1c1c" if is_dark else "#f0f0f0"
            fg = "#ffffff" if is_dark else "#1a1a1a"
            accent = "#0078d4"

            win.configure(bg=bg)
            if is_dark:
                win.update_idletasks()
                set_dwm_dark_title_bar(win)

            frame = tk.Frame(win, bg=bg, padx=20, pady=20)
            frame.pack(fill="both", expand=True)

            tk.Label(
                frame,
                text=f"AI Polyglot Kit v{APP_VERSION}",
                font=("Segoe UI", 12, "bold"),
                bg=bg,
                fg=fg,
            ).pack(pady=(0, 12))
            tk.Label(
                frame,
                text="Author: Dmytro Dubinko\nLicense: GPL-3.0\n\ngithub.com/dmdukr/ai-polyglot-kit",
                font=("Segoe UI", 10),
                justify="center",
                bg=bg,
                fg=fg,
            ).pack()
            tk.Button(
                win,
                text="OK",
                command=win.destroy,
                bg=accent,
                fg="#ffffff",
                activebackground="#106ebe",
                activeforeground="#ffffff",
                font=("Segoe UI", 9),
                relief="flat",
                padx=16,
                pady=4,
                cursor="hand2",
            ).pack(pady=12)

            win.update_idletasks()
            x = (win.winfo_screenwidth() - win.winfo_width()) // 2
            y = (win.winfo_screenheight() - win.winfo_height()) // 2
            win.geometry(f"+{x}+{y}")
            win.attributes("-topmost", True)

        tk_host.run_on_tk(_show)

    def _on_quit_click(self, _icon=None, _item=None) -> None:
        """Quit the application — full process exit."""
        logger.info("Quitting application")
        from . import tk_host

        tk_host.stop()
        self._updater.stop()
        if hasattr(self, "_translate_server"):
            self._translate_server.stop()
        self._engine._telemetry.app_stop()
        self._engine.shutdown()
        keyboard.unhook_all()
        if self._icon:
            self._icon.stop()
        # Signal settings loop to exit
        try:
            from .ui.settings_window import shutdown_settings_loop
            shutdown_settings_loop()
        except ImportError:
            pass
        # Force exit to ensure all threads are killed
        os._exit(0)

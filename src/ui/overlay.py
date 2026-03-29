"""Modern recording overlay — dark semi-transparent pill with states.

Tkinter-based (always-on-top, transparent, no window chrome).
Designed to sit at the bottom-center of the screen.

States:
    RECORDING   — pulsing red dot + timer + device info + waveform bars
    PROCESSING  — animated spinner dots + "Transcribing..."
    HIDDEN      — window withdrawn
"""

from __future__ import annotations

import contextlib
import logging
import math
import random
import tkinter as tk
from enum import Enum, auto

logger = logging.getLogger(__name__)

# --- Layout constants ---
PILL_WIDTH = 320
PILL_HEIGHT = 72
PILL_RADIUS = 20
BG_COLOR = "#1a1a2e"
BG_ACCENT = "#16213e"
TEXT_COLOR = "#e0e0e0"
TEXT_DIM = "#888888"
RED_DOT = "#ff3333"
ACCENT_GOLD = "#d4a537"
BAR_COUNT = 16
BAR_GAP = 2
UPDATE_MS = 80
BLINK_MS = 600
BAR_LEVEL_LOW = 0.4
BAR_LEVEL_MED = 0.7
SPINNER_HALF_CYCLE = 6


class _OverlayState(Enum):
    HIDDEN = auto()
    RECORDING = auto()
    PROCESSING = auto()


class RecordingOverlay:
    """Floating pill overlay for recording / processing feedback."""

    def __init__(self, tk_root: tk.Tk) -> None:
        self._root = tk_root
        self._state = _OverlayState.HIDDEN

        # Toplevel window — no chrome, always-on-top, semi-transparent
        self._win = tk.Toplevel(tk_root)
        self._win.title("")
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.92)
        self._win.configure(bg=BG_COLOR)
        self._win.withdraw()

        # --- Canvas (entire pill drawn here) ---
        self._canvas = tk.Canvas(
            self._win,
            width=PILL_WIDTH,
            height=PILL_HEIGHT,
            bg=BG_COLOR,
            highlightthickness=0,
        )
        self._canvas.pack()

        # Internal state
        self._device_name: str = ""
        self._language: str = ""
        self._timer_seconds: float = 0.0
        self._dot_visible: bool = True
        self._spinner_step: int = 0
        self._bar_levels: list[float] = [0.0] * BAR_COUNT

        # Animation IDs (for cancellation)
        self._anim_id: str | None = None
        self._blink_id: str | None = None

        # Bind Escape to cancel hint
        self._win.bind("<Escape>", lambda _e: self.hide())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_recording(self, device_name: str = "", language: str = "") -> None:
        """Show the overlay in RECORDING state."""
        self._device_name = device_name
        self._language = language
        self._timer_seconds = 0.0
        self._dot_visible = True
        self._spinner_step = 0
        self._bar_levels = [0.0] * BAR_COUNT
        self._state = _OverlayState.RECORDING

        self._position_window()
        self._win.deiconify()
        self._win.lift()
        self._draw()
        self._schedule_animation()

    def show_processing(self, duration_s: float = 0) -> None:
        """Switch to PROCESSING state (spinner + "Transcribing...")."""
        self._timer_seconds = duration_s
        self._spinner_step = 0
        self._state = _OverlayState.PROCESSING

        if self._win.state() == "withdrawn":
            self._position_window()
            self._win.deiconify()
            self._win.lift()

        self._draw()
        self._schedule_animation()

    def hide(self) -> None:
        """Hide the overlay."""
        self._state = _OverlayState.HIDDEN
        self._cancel_animation()
        with contextlib.suppress(tk.TclError):
            self._win.withdraw()

    def update_timer(self, seconds: float) -> None:
        """Update the recording timer display (called externally)."""
        self._timer_seconds = seconds
        # Simulate simple waveform activity based on timer ticks

        self._bar_levels = [min(1.0, max(0.05, random.gauss(0.35, 0.2))) for _ in range(BAR_COUNT)]

    def destroy(self) -> None:
        """Destroy the overlay window and clean up."""
        self._cancel_animation()
        with contextlib.suppress(tk.TclError):
            self._win.destroy()

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _position_window(self) -> None:
        """Place the pill at bottom-center of the screen."""
        self._win.update_idletasks()
        screen_w = self._win.winfo_screenwidth()
        screen_h = self._win.winfo_screenheight()
        x = (screen_w - PILL_WIDTH) // 2
        y = screen_h - PILL_HEIGHT - 80  # 80px above taskbar
        self._win.geometry(f"{PILL_WIDTH}x{PILL_HEIGHT}+{x}+{y}")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        """Redraw the entire overlay canvas based on current state."""
        c = self._canvas
        c.delete("all")

        # Rounded pill background
        self._draw_rounded_rect(c, 0, 0, PILL_WIDTH, PILL_HEIGHT, PILL_RADIUS, fill=BG_COLOR, outline="#2a2a4a")

        if self._state == _OverlayState.RECORDING:
            self._draw_recording(c)
        elif self._state == _OverlayState.PROCESSING:
            self._draw_processing(c)

    def _draw_recording(self, c: tk.Canvas) -> None:
        """Draw RECORDING state: dot + timer + bars + device + language + hint."""
        y_mid = PILL_HEIGHT // 2

        # --- Pulsing red dot ---
        dot_r = 5
        dot_x, dot_y = 18, y_mid - 8
        if self._dot_visible:
            c.create_oval(dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r, fill=RED_DOT, outline="")
        else:
            c.create_oval(dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r, fill="#661111", outline="")

        # --- Timer ---
        mins = int(self._timer_seconds) // 60
        secs = int(self._timer_seconds) % 60
        timer_text = f"{mins:02d}:{secs:02d}"
        c.create_text(50, y_mid - 8, text=timer_text, fill=TEXT_COLOR, font=("Segoe UI", 13, "bold"), anchor="w")

        # --- Waveform bars ---
        bar_area_x = 110
        bar_area_w = 90
        bar_h_max = 22
        bar_w = (bar_area_w - BAR_COUNT * BAR_GAP) / BAR_COUNT
        for i, level in enumerate(self._bar_levels):
            bx = bar_area_x + i * (bar_w + BAR_GAP)
            bh = max(2, level * bar_h_max)
            by_top = y_mid - 8 - bh / 2
            by_bot = y_mid - 8 + bh / 2
            color = "#00d4aa" if level < BAR_LEVEL_LOW else ("#f0c040" if level < BAR_LEVEL_MED else RED_DOT)
            c.create_rectangle(bx, by_top, bx + bar_w, by_bot, fill=color, outline="")

        # --- Device name (truncated) ---
        dev_label = self._device_name[:22] if self._device_name else "Microphone"
        c.create_text(210, y_mid - 8, text=dev_label, fill=TEXT_DIM, font=("Segoe UI", 8), anchor="w")

        # --- Language badge ---
        if self._language:
            badge_x = PILL_WIDTH - 14
            badge_y = y_mid - 8
            lang_text = self._language.upper()[:3]
            tw = len(lang_text) * 7 + 10
            c.create_rectangle(
                badge_x - tw,
                badge_y - 9,
                badge_x,
                badge_y + 9,
                fill="#2a2a4a",
                outline=ACCENT_GOLD,
                width=1,
            )
            c.create_text(
                badge_x - tw / 2,
                badge_y,
                text=lang_text,
                fill=ACCENT_GOLD,
                font=("Segoe UI", 7, "bold"),
            )

        # --- "Esc to cancel" hint ---
        c.create_text(
            PILL_WIDTH // 2,
            PILL_HEIGHT - 12,
            text="Esc to cancel",
            fill=TEXT_DIM,
            font=("Segoe UI", 7),
        )

    def _draw_processing(self, c: tk.Canvas) -> None:
        """Draw PROCESSING state: spinner dots + 'Transcribing...' text."""
        y_mid = PILL_HEIGHT // 2

        # --- Animated spinner (3 bouncing dots) ---
        dot_count = 3
        for i in range(dot_count):
            phase = (self._spinner_step + i * 3) % 12
            offset_y = -4 * math.sin(phase * math.pi / 6)
            dx = 20 + i * 14
            dy = y_mid - 6 + offset_y
            alpha_color = ACCENT_GOLD if (phase < SPINNER_HALF_CYCLE) else TEXT_DIM
            c.create_oval(dx - 3, dy - 3, dx + 3, dy + 3, fill=alpha_color, outline="")

        # --- "Transcribing..." label ---
        c.create_text(80, y_mid - 6, text="Transcribing\u2026", fill=TEXT_COLOR, font=("Segoe UI", 11), anchor="w")

        # --- Duration ---
        if self._timer_seconds > 0:
            secs = int(self._timer_seconds)
            c.create_text(PILL_WIDTH - 20, y_mid - 6, text=f"{secs}s", fill=TEXT_DIM, font=("Segoe UI", 9), anchor="e")

        # --- Hint ---
        c.create_text(
            PILL_WIDTH // 2,
            PILL_HEIGHT - 12,
            text="Please wait\u2026",
            fill=TEXT_DIM,
            font=("Segoe UI", 7),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _draw_rounded_rect(
        canvas: tk.Canvas,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        r: int,
        **kwargs: object,
    ) -> int:
        """Draw a rounded rectangle on a canvas."""
        points = [
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
            x1 + r,
            y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Animation scheduling
    # ------------------------------------------------------------------

    def _schedule_animation(self) -> None:
        """Start the periodic update + blink timers."""
        self._cancel_animation()
        self._tick()
        self._blink()

    def _cancel_animation(self) -> None:
        """Cancel pending after() callbacks."""
        if self._anim_id is not None:
            with contextlib.suppress(tk.TclError, ValueError):
                self._win.after_cancel(self._anim_id)
            self._anim_id = None
        if self._blink_id is not None:
            with contextlib.suppress(tk.TclError, ValueError):
                self._win.after_cancel(self._blink_id)
            self._blink_id = None

    def _tick(self) -> None:
        """Periodic redraw (waveform bars / spinner)."""
        if self._state == _OverlayState.HIDDEN:
            return
        if self._state == _OverlayState.PROCESSING:
            self._spinner_step = (self._spinner_step + 1) % 12
        self._draw()
        with contextlib.suppress(tk.TclError):
            self._anim_id = self._win.after(UPDATE_MS, self._tick)

    def _blink(self) -> None:
        """Toggle the recording red dot visibility."""
        if self._state != _OverlayState.RECORDING:
            return
        self._dot_visible = not self._dot_visible
        with contextlib.suppress(tk.TclError):
            self._blink_id = self._win.after(BLINK_MS, self._blink)

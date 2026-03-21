"""Text injection into active window via keyboard simulation."""

import logging
import time
from threading import Lock

import pyperclip
from pynput.keyboard import Controller, Key

from .config import TextInjectionConfig

logger = logging.getLogger(__name__)


class TextInjector:
    """Simulates keyboard input to type text into the active window."""

    def __init__(self, config: TextInjectionConfig):
        self._config = config
        self._keyboard = Controller()
        self._chars_typed: int = 0
        self._lock = Lock()

    @property
    def chars_typed(self) -> int:
        return self._chars_typed

    def type_text(self, text: str) -> None:
        """Type text into the active window. Increments chars_typed counter.

        Uses pynput type() for reliability (works in all windows).
        Speed: ~0ms delay between chars via SendInput/Unicode.
        """
        if not text:
            return

        with self._lock:
            self._type_fast(text)
            self._chars_typed += len(text)
            logger.debug(f"Typed {len(text)} chars, total: {self._chars_typed}")

    def replace_draft(self, new_text: str) -> None:
        """Replace previously typed draft text with new normalized text.

        Sends chars_typed backspaces to delete the draft, then types new_text.
        """
        with self._lock:
            count = self._chars_typed
            if count == 0:
                self._chars_typed = 0
                if new_text:
                    self._type_fast(new_text)
                    self._chars_typed = len(new_text)
                return

            logger.info(f"Replacing {count} chars with {len(new_text)} chars")

            # Delete the draft text
            self._send_backspaces(count)
            time.sleep(0.05)

            # Type normalized text
            self._type_fast(new_text)

            self._chars_typed = len(new_text)

    def reset_counter(self) -> None:
        """Reset the character counter to 0."""
        with self._lock:
            self._chars_typed = 0

    def grab_typed_text(self, char_count: int = 0) -> str:
        """Select and copy the text around cursor for feedback learning.

        Uses SendInput (win32) for reliable key simulation:
        Shift+Left * char_count → Ctrl+C → Right.
        Returns the grabbed text, or empty string on failure.
        """
        if char_count <= 0:
            logger.warning("grab_typed_text: char_count=0, nothing to grab")
            return ""

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            INPUT_KEYBOARD = 1
            KEYEVENTF_KEYUP = 0x0002

            VK_SHIFT = 0x10
            VK_CONTROL = 0x11
            VK_RIGHT = 0x27
            VK_C = 0x43

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class MOUSEINPUT(ctypes.Structure):
                _fields_ = [
                    ("dx", ctypes.c_long),
                    ("dy", ctypes.c_long),
                    ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class INPUT(ctypes.Structure):
                class _INPUT(ctypes.Union):
                    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("_input", _INPUT),
                ]

            def _key(vk, up=False):
                inp = INPUT()
                inp.type = INPUT_KEYBOARD
                inp._input.ki.wVk = vk
                inp._input.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
                return inp

            def send(*inputs):
                arr = (INPUT * len(inputs))(*inputs)
                user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))

            # Save clipboard
            try:
                saved = pyperclip.paste()
            except Exception:
                saved = ""

            pyperclip.copy("")
            time.sleep(0.05)

            # Select all text from cursor to start of document: Ctrl+Shift+Home
            # This reliably captures multi-line text regardless of line width
            VK_HOME = 0x24

            send(_key(VK_CONTROL), _key(VK_SHIFT))
            send(_key(VK_HOME), _key(VK_HOME, up=True))
            send(_key(VK_SHIFT, up=True), _key(VK_CONTROL, up=True))
            time.sleep(0.05)

            # Ctrl+C via SendInput
            send(_key(VK_CONTROL), _key(VK_C))
            time.sleep(0.02)
            send(_key(VK_C, up=True), _key(VK_CONTROL, up=True))
            time.sleep(0.15)

            # Read clipboard
            grabbed = ""
            try:
                grabbed = pyperclip.paste()
            except Exception:
                pass

            # Deselect: Right arrow (moves cursor to end of selection)
            send(_key(VK_RIGHT), _key(VK_RIGHT, up=True))

            # Restore clipboard
            if saved:
                time.sleep(0.03)
                try:
                    pyperclip.copy(saved)
                except Exception:
                    pass

            logger.info(f"Grabbed text ({len(grabbed)} chars): {grabbed[:80]!r}")
            return grabbed.strip() if grabbed else ""

        except Exception as e:
            logger.warning(f"Failed to grab typed text: {e}")
            return ""

    def grab_context_paragraph(self) -> str:
        """Grab up to one paragraph of text before cursor from active window.

        Uses Shift+Home then Shift+Up*3 to select, copies via Ctrl+C, restores cursor.
        Returns empty string if nothing could be grabbed.
        """
        try:
            # Save clipboard
            try:
                saved = pyperclip.paste()
            except Exception:
                saved = ""

            pyperclip.copy("")  # Clear clipboard
            time.sleep(0.02)

            # Select from cursor to start of current paragraph (3 lines up max)
            self._keyboard.press(Key.shift)
            self._keyboard.press(Key.home)
            self._keyboard.release(Key.home)
            for _ in range(3):
                self._keyboard.press(Key.up)
                self._keyboard.release(Key.up)
            self._keyboard.release(Key.shift)
            time.sleep(0.02)

            # Copy selection
            self._keyboard.press(Key.ctrl)
            self._keyboard.press("c")
            self._keyboard.release("c")
            self._keyboard.release(Key.ctrl)
            time.sleep(0.05)

            # Read clipboard
            context = ""
            try:
                context = pyperclip.paste()
            except Exception:
                pass

            # Deselect — move cursor to end (Right arrow)
            self._keyboard.press(Key.end)
            self._keyboard.release(Key.end)

            # Restore clipboard
            if saved:
                time.sleep(0.02)
                try:
                    pyperclip.copy(saved)
                except Exception:
                    pass

            # Return last paragraph only (max 500 chars)
            if context:
                context = context.strip()[-500:]
                logger.debug(f"Grabbed context: {len(context)} chars")
            return context

        except Exception as e:
            logger.debug(f"Failed to grab context: {e}")
            return ""

    def _type_fast(self, text: str) -> None:
        """Type text using pynput Controller — no delay, maximum speed."""
        try:
            self._keyboard.type(text)
        except Exception as e:
            logger.warning(f"Fast type failed, falling back char-by-char: {e}")
            for char in text:
                try:
                    self._keyboard.type(char)
                except Exception:
                    pass

    def _type_via_sendinput(self, text: str) -> None:
        """Type text using pynput Controller (SendInput with KEYEVENTF_UNICODE)."""
        delay = self._config.typing_delay_ms / 1000.0
        for char in text:
            try:
                self._keyboard.type(char)
                if delay > 0:
                    time.sleep(delay)
            except Exception as e:
                logger.warning(f"Failed to type char '{char}': {e}")

    def _type_via_clipboard(self, text: str) -> None:
        """Type text by copying to clipboard and pasting (Ctrl+V)."""
        try:
            pyperclip.copy(text)
            time.sleep(0.03)
            self._keyboard.press(Key.ctrl)
            self._keyboard.press("v")
            self._keyboard.release("v")
            self._keyboard.release(Key.ctrl)
            time.sleep(0.05)
        except Exception as e:
            logger.error(f"Clipboard paste failed: {e}")
            # Fallback to sendinput
            self._type_via_sendinput(text)
            return
        finally:
            pass  # Don't restore clipboard — it interferes with rapid pastes

    def _send_backspaces(self, count: int) -> None:
        """Send N backspace key presses in batches."""
        batch_size = self._config.backspace_batch_size
        delay = self._config.typing_delay_ms / 1000.0

        sent = 0
        while sent < count:
            batch = min(batch_size, count - sent)
            for _ in range(batch):
                self._keyboard.press(Key.backspace)
                self._keyboard.release(Key.backspace)
                sent += 1
            # Small pause between batches to let the app process
            if sent < count:
                time.sleep(max(delay * 5, 0.01))

        logger.debug(f"Sent {count} backspaces")

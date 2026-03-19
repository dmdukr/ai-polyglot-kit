"""Groq Dictation — Windows system-wide Speech-to-Text service.

Entry point: bootstraps config, engine, and tray app.
"""

import sys
import os
import logging
import faulthandler
import tempfile
from pathlib import Path

from .config import AppConfig, APP_DIR, setup_logging
from .engine import DictationEngine
from .tray_app import TrayApp

logger = logging.getLogger(__name__)

LOCK_FILE = APP_DIR / "groq-dictation.lock"


def _check_single_instance() -> bool:
    """Ensure only one instance is running. Returns True if we can proceed."""
    import ctypes
    # Use a named mutex on Windows for reliable single-instance check
    mutex_name = "Global\\GroqDictation_SingleInstance"
    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183

    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        if handle:
            kernel32.CloseHandle(handle)
        return False

    # Store handle to prevent GC (keeps mutex alive for process lifetime)
    _check_single_instance._mutex_handle = handle
    return True


def release_single_instance():
    """Release the mutex so a restart can acquire it."""
    handle = getattr(_check_single_instance, '_mutex_handle', None)
    if handle:
        import ctypes
        ctypes.windll.kernel32.ReleaseMutex(handle)
        ctypes.windll.kernel32.CloseHandle(handle)
        _check_single_instance._mutex_handle = None


def main() -> None:
    """Main entry point."""
    # Single instance check
    if not _check_single_instance():
        print("Groq Dictation is already running!", file=sys.stderr)
        # Try to show a message box
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "Groq Dictation is already running.", "Groq Dictation", 0x40
            )
        except Exception:
            pass
        sys.exit(0)

    # Cleanup stale PyInstaller _MEI* temp dirs
    if getattr(sys, "frozen", False):
        try:
            import shutil
            tmp = Path(tempfile.gettempdir())
            my_mei = Path(sys._MEIPASS).name if hasattr(sys, "_MEIPASS") else ""
            for d in tmp.glob("_MEI*"):
                if d.is_dir() and d.name != my_mei:
                    try:
                        shutil.rmtree(d, ignore_errors=True)
                    except Exception:
                        pass
        except Exception:
            pass

    # Enable faulthandler for segfault debugging
    _fault_log = APP_DIR / "logs" / "crash.log"
    _fault_log.parent.mkdir(parents=True, exist_ok=True)
    _fault_file = open(_fault_log, "a")
    faulthandler.enable(file=_fault_file)

    # Load configuration
    config = AppConfig.load()

    # Setup logging
    setup_logging(config.logging)

    # Catch unhandled exceptions in threads
    import threading
    def _thread_excepthook(args):
        logger.error(
            f"Unhandled exception in thread '{args.thread.name}': {args.exc_type.__name__}: {args.exc_value}",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    threading.excepthook = _thread_excepthook

    logger.info("Groq Dictation starting...")

    # ── CRITICAL: Disable GC globally ──
    # Python 3.13 has a bug where GC firing during abc.__subclasscheck__
    # in worker threads causes "Windows fatal exception: code 0x80000003".
    # This affects httpx, pydantic, and any library using isinstance() with
    # ABCs. Disabling GC is safe for a desktop app — refcounting handles
    # most cleanup. We do manual gc.collect() when engine is idle.
    import gc
    gc.disable()
    logger.info("GC disabled (Python 3.13 ABC/GC crash workaround)")

    # Set UI language
    from .i18n import set_language
    set_language(config.ui.language)

    # Validate config (non-fatal warnings)
    errors = config.validate()
    for err in errors:
        logger.warning(f"Config issue: {err}")

    # Create engine
    engine = DictationEngine(config)

    # Telemetry: app start
    engine._telemetry.app_start()

    # Create and run tray app (blocks main thread)
    tray = TrayApp(engine, config)

    logger.info("Starting tray application")
    try:
        tray.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        engine._telemetry.app_stop()
        engine.shutdown()
        logger.info("Groq Dictation stopped")


if __name__ == "__main__":
    main()

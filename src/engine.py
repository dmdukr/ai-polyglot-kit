"""DictationEngine — central state machine coordinating all modules."""

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Callable

from .config import AppConfig
from .audio_capture import AudioCapture
from .chunk_manager import ChunkManager
from .normalizer import Normalizer
from .text_injector import TextInjector
from .recording_overlay import RecordingOverlay
from .user_profile import UserProfile
from .telemetry import TelemetryCollector
from .provider_manager import ProviderManager

logger = logging.getLogger(__name__)


class DictationState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    TYPING = "typing"
    ERROR = "error"


class DictationEngine:
    """Orchestrates the entire dictation lifecycle.

    State machine: IDLE → RECORDING → PROCESSING → TYPING → IDLE

    During RECORDING:
      - AudioCapture records from mic
      - ChunkManager splits audio on pauses via VAD
      - Each chunk → GroqSTT → text typed into active window (draft)

    On toggle (stop):
      - Flush remaining audio
      - Concatenate all session text
      - Send to Normalizer (Groq LLM)
      - Replace draft with normalized text
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._state = DictationState.IDLE
        self._state_lock = threading.Lock()
        self._last_toggle = 0.0

        # Modules
        self._audio = AudioCapture(config.audio)
        self._chunker: ChunkManager | None = None
        # User profile (learns speech patterns over time)
        self._profile = UserProfile(
            enabled=config.profile.enabled,
            min_correction_count=config.profile.min_correction_count,
            max_prompt_tokens=config.profile.max_prompt_tokens,
            decay_days=config.profile.decay_days,
        )
        self._profile.load()
        # Provider manager (multi-slot fallback for STT + LLM)
        self._quota_callback: Callable[[int, int], None] | None = None
        self._providers = ProviderManager(config.providers, on_quota_warning=self._on_quota_warning)

        # Normalizer uses LLM connector from provider manager
        llm = self._providers.get_llm()
        self._normalizer = Normalizer(llm, config.normalization, profile=self._profile)
        self._injector = TextInjector(config.text_injection)
        self._overlay = RecordingOverlay()
        self._telemetry = TelemetryCollector(enabled=config.telemetry.enabled)
        self._viz_queue: queue.Queue[bytes] | None = None

        # Thread pool for API calls
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="stt")

        # Session state
        self._session_text: list[str] = []
        self._session_lock = threading.Lock()
        self._next_chunk_id = 0
        self._next_type_id = 0
        self._pending_results: dict[int, str] = {}
        self._typing_lock = threading.Lock()
        self._previous_text = ""
        self._last_normalized_text = ""  # for feedback learning
        self._last_typed_len = 0  # length of last typed text for grab
        self._session_raw_text = ""
        self._last_tap_count = 0  # tap counter for double-tap

        # State change callback (for TrayApp)
        self._state_callback: Callable[[DictationState], None] | None = None
        self._error_callback: Callable[[str], None] | None = None
        self._suppress_ptt_callback: Callable[[bool], None] | None = None

    @property
    def state(self) -> DictationState:
        return self._state

    def set_state_callback(self, callback: Callable[[DictationState], None]) -> None:
        """Register callback for state changes (used by TrayApp)."""
        self._state_callback = callback

    def set_error_callback(self, callback: Callable[[str], None]) -> None:
        """Register callback for error notifications."""
        self._error_callback = callback

    def set_suppress_ptt_callback(self, callback: Callable[[bool], None]) -> None:
        """Register callback to suppress/unsuppress PTT during feedback capture."""
        self._suppress_ptt_callback = callback

    def set_quota_callback(self, callback: Callable[[int, int], None]) -> None:
        """Register callback for quota warnings. callback(remaining_sec, limit_sec)."""
        self._quota_callback = callback

    def _on_quota_warning(self, remaining: int, limit: int) -> None:
        """Called by GroqSTT when quota threshold is reached."""
        if self._quota_callback:
            self._quota_callback(remaining, limit)

    def get_audio_capture(self) -> AudioCapture:
        """Access AudioCapture for mic management from TrayApp."""
        return self._audio

    def toggle(self) -> None:
        """Handle hotkey press. Toggle between IDLE↔RECORDING.

        Double-tap in IDLE (within 0.8s, when we have recent typed text)
        triggers feedback capture — reads user-edited text and learns corrections.
        """
        now = time.monotonic()
        gap = now - self._last_toggle

        # Debounce: ignore if < 0.2s
        if gap < 0.2:
            return
        self._last_toggle = now

        with self._state_lock:
            if self._state == DictationState.IDLE:
                # Double-tap detection: if pressed within 0.8s and we have typed text
                if gap < 0.8 and self._last_normalized_text:
                    threading.Thread(
                        target=self._capture_feedback, name="Feedback", daemon=True
                    ).start()
                    return
                self._start_recording()
            elif self._state == DictationState.RECORDING:
                threading.Thread(target=self._stop_recording, name="StopRec", daemon=True).start()
            elif self._state in (DictationState.PROCESSING, DictationState.TYPING):
                logger.info("Ignoring toggle during processing/typing")
            elif self._state == DictationState.ERROR:
                self._reset()

    def start_if_idle(self) -> None:
        """Start recording only if currently idle. Called after hold timer (0.5s)."""
        with self._state_lock:
            if self._state != DictationState.IDLE:
                return
            self._start_recording()

    def cancel_recording(self) -> None:
        """Cancel recording silently (tap detected, discard audio)."""
        with self._state_lock:
            if self._state == DictationState.RECORDING:
                logger.info("Recording cancelled (tap)")
                self._cleanup()
                self._set_state(DictationState.IDLE)

    def stop_if_recording(self) -> None:
        """Stop recording on hold release."""
        with self._state_lock:
            if self._state == DictationState.RECORDING:
                threading.Thread(target=self._stop_recording, name="StopRec", daemon=True).start()

    def on_tap(self) -> None:
        """Handle a tap (press < 0.5s). Called from tray_app hook.

        Increments tap counter. On second tap within 0.5s,
        if there's recent typed text → capture feedback.
        """
        self._last_tap_count = getattr(self, "_last_tap_count", 0) + 1
        logger.info("Tap #%d detected", self._last_tap_count)

        if self._last_tap_count == 1:
            # First tap — wait 0.5s for second
            def _wait_for_second_tap():
                time.sleep(0.5)
                if self._last_tap_count >= 2 and self._last_normalized_text:
                    logger.info("Double-tap confirmed — capturing feedback")
                    text_to_check = self._last_normalized_text
                    self._last_normalized_text = ""
                    self._last_tap_count = 0
                    self._capture_feedback(text_to_check)
                else:
                    if self._last_tap_count >= 2:
                        logger.info("Double-tap but no recent text to compare")
                    self._last_tap_count = 0
            threading.Thread(target=_wait_for_second_tap, name="TapWait", daemon=True).start()

    def _set_state(self, new_state: DictationState) -> None:
        """Update state and notify callback."""
        old = self._state
        self._state = new_state
        logger.info(f"State: {old.value} → {new_state.value}")
        if self._state_callback:
            try:
                self._state_callback(new_state)
            except Exception as e:
                logger.error(f"State callback error: {e}")

    def _start_recording(self) -> None:
        """Begin recording session."""
        logger.info("Starting dictation session")

        # Reset session state
        self._session_text.clear()
        self._pending_results.clear()
        self._next_chunk_id = 0
        self._next_type_id = 0
        self._previous_text = ""
        self._injector.reset_counter()

        # Set state early so stop_if_recording can find us
        self._set_state(DictationState.RECORDING)
        self._recording_start_time = time.monotonic()

        # Validate API key early
        errors = self._config.validate()
        if errors:
            for err in errors:
                logger.error(f"Config error: {err}")
            self._set_state(DictationState.ERROR)
            if self._error_callback:
                self._error_callback(errors[0])
            return

        try:
            # Get STT connector from provider manager
            stt = self._providers.get_stt()
            if stt is None:
                raise RuntimeError("No STT provider configured. Add API key in Settings → STT.")

            # Start audio stream if not already running (kept open between recordings)
            if not self._audio.is_running:
                self._audio.start()

            # Drain stale frames from queue before starting chunk manager
            q = self._audio.get_frame_queue()
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break

            # Create and start chunk manager
            self._chunker = ChunkManager(
                q,
                self._config.audio,
            )
            self._chunker.start(self._on_chunk_ready)

            # Show recording overlay with waveform (non-critical)
            try:
                self._viz_queue = self._audio.add_listener_queue()
                mic_name = self._audio.get_active_device_name()
                self._overlay.show(mic_name, self._viz_queue)
            except Exception as e:
                logger.warning(f"Overlay failed to start (non-critical): {e}")

            # Audio feedback (non-blocking)
            if self._config.ui.sound_on_start:
                threading.Thread(target=self._play_beep, args=(800, 50), daemon=True).start()

        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self._set_state(DictationState.ERROR)
            if self._error_callback:
                self._error_callback(f"Failed to start: {e}")
            self._cleanup()

    def _stop_recording(self) -> None:
        """Stop recording and begin normalization."""
        logger.info("Stopping dictation session")

        # Hide overlay
        try:
            self._overlay.hide()
        except Exception:
            pass

        if self._viz_queue:
            try:
                self._audio.remove_listener_queue(self._viz_queue)
            except Exception:
                pass
            self._viz_queue = None

        # Check minimum recording duration (avoid hallucinations on short press)
        recording_duration = time.monotonic() - getattr(self, '_recording_start_time', 0)
        if recording_duration < 1.0:
            logger.info(f"Recording too short ({recording_duration:.1f}s < 1.0s), discarding")
            self._cleanup()
            self._set_state(DictationState.IDLE)
            return

        # Audio feedback
        if self._config.ui.sound_on_stop:
            self._play_beep(frequency=600, duration=100)

        try:
            # Don't stop audio stream — keep it open for instant next recording
            # Just stop the chunk manager

            # Flush remaining audio from chunker
            if self._chunker:
                remaining = self._chunker.flush()
                if remaining:
                    self._on_chunk_ready(remaining)
                self._chunker.stop()
                self._chunker = None

            # Wait for pending transcriptions
            self._set_state(DictationState.PROCESSING)
            self._wait_for_pending_transcriptions()

            # Concatenate all session text
            with self._session_lock:
                full_text = " ".join(self._session_text)

            if not full_text.strip():
                logger.info("No speech detected in session")
                self._cleanup()
                if self._error_callback:
                    self._error_callback("No speech detected")
                self._set_state(DictationState.IDLE)
                return

            logger.info(f"Session text ({len(full_text)} chars): {full_text[:100]}...")

            # Store raw text for profile learning (before normalization)
            self._session_raw_text = full_text

            if self._config.normalization.enabled:
                self._normalizer.normalize_async(
                    full_text,
                    self._on_normalization_ready,
                    self._executor,
                )
            else:
                self._cleanup()
                self._set_state(DictationState.IDLE)

        except Exception as e:
            logger.error(f"Error stopping recording: {e}")
            self._cleanup()
            self._set_state(DictationState.ERROR)
            if self._error_callback:
                self._error_callback(f"Error: {e}")

    def _on_chunk_ready(self, wav_bytes: bytes) -> None:
        """Called by ChunkManager when a speech chunk is ready."""
        chunk_id = self._next_chunk_id
        self._next_chunk_id += 1
        logger.debug(f"Chunk {chunk_id} ready ({len(wav_bytes)} bytes)")

        self._executor.submit(self._process_chunk, chunk_id, wav_bytes)

    def _process_chunk(self, chunk_id: int, wav_bytes: bytes) -> None:
        """Transcribe a chunk and queue it for typing."""
        try:
            stt = self._providers.get_stt()
            if stt is None:
                logger.error("No STT connector available for chunk %d", chunk_id)
                with self._typing_lock:
                    self._pending_results[chunk_id] = ""
                    self._flush_pending_typing()
                return
            text = stt.transcribe(wav_bytes, previous_text=self._previous_text)

            if text:
                logger.info(f"Chunk {chunk_id}: '{text}'")
                with self._typing_lock:
                    self._pending_results[chunk_id] = text
                    self._flush_pending_typing()
            else:
                logger.debug(f"Chunk {chunk_id}: no text (filtered/empty)")
                with self._typing_lock:
                    # Mark as empty so ordering still works
                    self._pending_results[chunk_id] = ""
                    self._flush_pending_typing()

        except Exception as e:
            logger.error(f"Error processing chunk {chunk_id}: {e}")
            with self._typing_lock:
                self._pending_results[chunk_id] = ""
                self._flush_pending_typing()

    def _flush_pending_typing(self) -> None:
        """Type all consecutive pending results in order."""
        while self._next_type_id in self._pending_results:
            text = self._pending_results.pop(self._next_type_id)
            self._next_type_id += 1

            if text:
                with self._session_lock:
                    self._session_text.append(text)

                # Don't type raw text — wait for normalization to type final text
                self._previous_text = text

    def _wait_for_pending_transcriptions(self, timeout: float = 10.0) -> None:
        """Wait for all submitted chunks to be processed."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._typing_lock:
                if self._next_type_id >= self._next_chunk_id:
                    return
            time.sleep(0.1)
        logger.warning("Timed out waiting for pending transcriptions")

    def _on_normalization_ready(self, normalized_text: str) -> None:
        """Called when normalization completes."""
        logger.info(f"Normalization complete: {len(normalized_text)} chars")

        try:
            self._set_state(DictationState.TYPING)
            # Suppress PTT during typing (SendInput keys would trigger hook)
            if self._suppress_ptt_callback:
                self._suppress_ptt_callback(True)
            self._injector.replace_draft(normalized_text)
            # Store for feedback learning (double-tap)
            self._last_normalized_text = normalized_text
            self._last_typed_len = len(normalized_text)
            # Unsuppress PTT
            if self._suppress_ptt_callback:
                self._suppress_ptt_callback(False)
            # Learn from this session (raw vs normalized diff)
            raw = getattr(self, "_session_raw_text", "")
            if raw and self._profile:
                try:
                    self._profile.record_session(raw, normalized_text)
                    self._profile.add_history(raw, normalized_text)
                    self._maybe_optimize_prompt()
                except Exception as e:
                    logger.warning(f"Profile update failed: {e}")
            # Telemetry
            duration = time.monotonic() - self._recording_start_time if hasattr(self, "_recording_start_time") else 0
            self._telemetry.record_session(
                audio_duration_s=duration,
                latency_ms=(time.monotonic() - self._recording_start_time) * 1000 if hasattr(self, "_recording_start_time") else 0,
                stt_model=self._config.groq.stt_model,
                llm_model=self._config.groq.llm_model,
                char_count=len(normalized_text),
            )
            # Close mic stream (opens on demand at next key press)
            if self._audio.is_running:
                try:
                    self._audio.stop()
                    logger.info("Mic closed after normalization")
                except Exception:
                    pass
            self._set_state(DictationState.IDLE)
        except Exception as e:
            logger.error(f"Error during text replacement: {e}")
            self._cleanup()
            self._set_state(DictationState.ERROR)
            if self._error_callback:
                self._error_callback(f"Text replacement failed: {e}")

    def _capture_feedback(self, original: str = "") -> None:
        """Capture user-edited text and learn corrections from manual edits.

        Called on double-tap hotkey. Reads the text the user may have edited
        and diffs it against what we originally typed.
        """
        if not original:
            return

        char_count = getattr(self, "_last_typed_len", 0)
        logger.info("Feedback capture: reading %d chars of user-edited text...", char_count)
        # Flash icon to show feedback activated
        self._flash_icon("processing")

        # Suppress PTT hook during text grab (we send synthetic keys)
        if self._suppress_ptt_callback:
            self._suppress_ptt_callback(True)

        try:
            edited = self._injector.grab_typed_text(char_count=char_count)
            if not edited:
                logger.info("Feedback: could not grab text (empty)")
                self._flash_icon("error")
                return

            if edited.strip() == original.strip():
                logger.info("Feedback: text unchanged, no corrections to learn")
                self._flash_icon("unchanged")
                self._last_normalized_text = ""
                return

            # User edited the text — learn from their corrections
            logger.info(
                "Feedback: learning from user edits (original %d chars → edited %d chars)",
                len(original), len(edited),
            )
            if self._profile:
                self._profile.record_session(original, edited, from_feedback=True)
                self._profile.update_history_edited(edited)
                logger.info("Feedback corrections recorded to profile")
                self._maybe_optimize_prompt()

            self._telemetry.record_feedback(corrections_count=1)
            self._telemetry.send_profile_triads()
            self._flash_icon("success")

        except Exception as e:
            logger.error(f"Feedback capture failed: {e}")
            self._flash_icon("error")
        finally:
            # Always unsuppress PTT
            if self._suppress_ptt_callback:
                self._suppress_ptt_callback(False)

    def _flash_icon(self, result: str) -> None:
        """Flash the tray icon to visually confirm feedback result.

        Flashes icon colors directly without changing engine state,
        so PTT events are not blocked during the flash.

        Args:
            result: "processing", "success", "unchanged", "error"
        """
        cb = self._state_callback
        if not cb:
            return

        def _do_flash():
            patterns = {
                "processing": [(DictationState.PROCESSING, 0.15)] * 2,
                "success":    [(DictationState.TYPING, 0.15), (DictationState.IDLE, 0.1)] * 3,
                "unchanged":  [(DictationState.IDLE, 0.15), (DictationState.PROCESSING, 0.15)] * 2,
                "error":      [(DictationState.ERROR, 0.2)] * 3,
            }
            for state, duration in patterns.get(result, []):
                try:
                    cb(state)  # update icon only, not engine state
                except Exception:
                    pass
                time.sleep(duration)
            try:
                cb(DictationState.IDLE)
            except Exception:
                pass

        threading.Thread(target=_do_flash, name="IconFlash", daemon=True).start()

    def _maybe_optimize_prompt(self) -> None:
        """Recompile prompt from profile facts (instant, no LLM calls)."""
        if not self._profile or not self._profile.needs_recompile:
            return
        self._profile.compile_prompt()
        logger.info("Prompt recompiled from facts")

    def _reset(self) -> None:
        """Reset engine to IDLE state."""
        logger.info("Resetting engine")
        self._cleanup()
        self._set_state(DictationState.IDLE)

    def _cleanup(self) -> None:
        """Clean up recording resources and close mic stream."""
        try:
            self._overlay.hide()
        except Exception:
            pass
        if self._viz_queue:
            try:
                self._audio.remove_listener_queue(self._viz_queue)
            except Exception:
                pass
            self._viz_queue = None
        if self._chunker:
            try:
                self._chunker.stop()
            except Exception:
                pass
            self._chunker = None
        # Close mic stream (opens on demand at next key press)
        if self._audio.is_running:
            try:
                self._audio.stop()
                logger.info("Mic stream closed after session")
            except Exception:
                pass

    def get_provider_manager(self) -> ProviderManager:
        """Access ProviderManager for Settings UI and tray."""
        return self._providers

    def shutdown(self) -> None:
        """Graceful shutdown — close everything."""
        logger.info("Shutting down engine")
        self._cleanup()
        try:
            self._audio.stop()
        except Exception:
            pass
        self._executor.shutdown(wait=False)
        self._providers.shutdown()
        if self._profile:
            try:
                self._profile.save(force=True)
            except Exception:
                pass

    @staticmethod
    def _play_beep(frequency: int = 800, duration: int = 100) -> None:
        """Play a beep sound for audio feedback."""
        try:
            import winsound
            winsound.Beep(frequency, duration)
        except Exception:
            pass

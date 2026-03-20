"""VAD-based audio chunking manager.

Consumes raw PCM frames from a queue, runs WebRTC VAD to detect speech
pauses, and emits complete utterance chunks as in-memory WAV files.

Key design: ALL audio is kept from the start of recording. VAD is used
only to detect pauses for chunk splitting, never to discard audio.
"""

from __future__ import annotations

import collections
import io
import logging
import queue
import threading
import wave
from typing import Callable

import webrtcvad

from .config import AudioConfig

logger = logging.getLogger(__name__)

WavCallback = Callable[[bytes], None]

# How many consecutive silence frames to split a chunk
# (separate from ring buffer — simpler counter approach)
_SILENCE_FRAMES_DEFAULT = 50  # will be computed from config


class ChunkManager:
    """Voice-activity-driven audio chunker.

    Keeps ALL audio from recording start. Uses VAD to detect pauses
    (silence gaps) and splits chunks at those points.
    """

    def __init__(self, audio_queue: queue.Queue[bytes], config: AudioConfig | None = None) -> None:
        self._queue = audio_queue
        self._cfg = config or AudioConfig()

        # Derived constants
        self._frame_bytes = 2 * self._cfg.sample_rate * self._cfg.frame_duration_ms // 1000
        self._min_frames = self._cfg.min_chunk_duration_ms // self._cfg.frame_duration_ms
        self._max_frames = (self._cfg.max_chunk_duration_s * 1000) // self._cfg.frame_duration_ms
        self._silence_frames = self._cfg.silence_threshold_ms // self._cfg.frame_duration_ms

        # VAD instance
        self._vad = webrtcvad.Vad(self._cfg.vad_aggressiveness)

        # State
        self._callback: WavCallback | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Audio buffer — keeps ALL frames since last chunk emission
        self._frames: list[bytes] = []
        self._consecutive_silence: int = 0
        self._has_speech: bool = False  # at least one speech frame detected

        # Skip first ~150ms to avoid key click / mic warmup noise
        self._warmup_skip = 5  # frames to discard at start (5 × 30ms = 150ms)

        logger.info(
            "ChunkManager: frame=%d ms, silence=%d frames (%d ms), "
            "min=%d frames, max=%d frames",
            self._cfg.frame_duration_ms,
            self._silence_frames, self._cfg.silence_threshold_ms,
            self._min_frames, self._max_frames,
        )

    def start(self, callback: WavCallback) -> None:
        """Start the processing thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._callback = callback
        self._stop_event.clear()
        self._reset_state()

        self._thread = threading.Thread(
            target=self._run, name="ChunkManager", daemon=True,
        )
        self._thread.start()
        logger.info("ChunkManager started")

    def stop(self) -> None:
        """Stop the processing thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("ChunkManager stopped")

    def flush(self) -> bytes | None:
        """Force-emit any accumulated frames. Called when user stops dictation."""
        with self._lock:
            if not self._frames:
                return None
            # Emit everything we have, even if short
            if len(self._frames) < 3:
                # Less than ~100ms, not useful
                self._frames.clear()
                return None
            wav_bytes = self._pack_wav(self._frames)
            logger.info("Flush: %d frames (%d ms), %d bytes WAV",
                        len(self._frames),
                        len(self._frames) * self._cfg.frame_duration_ms,
                        len(wav_bytes))
            self._frames.clear()
            return wav_bytes

    def _reset_state(self) -> None:
        self._frames.clear()
        self._consecutive_silence = 0
        self._has_speech = False

    def _run(self) -> None:
        """Worker loop."""
        while not self._stop_event.is_set():
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if len(frame) != self._frame_bytes:
                continue

            # Skip warmup frames (key click / mic noise)
            if self._warmup_skip > 0:
                self._warmup_skip -= 1
                continue

            is_speech = self._vad.is_speech(frame, self._cfg.sample_rate)

            with self._lock:
                self._process_frame(frame, is_speech)

    def _process_frame(self, frame: bytes, is_speech: bool) -> None:
        """Process a single frame. Must be called under self._lock."""
        self._frames.append(frame)

        if is_speech:
            self._has_speech = True
            self._consecutive_silence = 0
        else:
            self._consecutive_silence += 1

        # Check max duration — force split
        if len(self._frames) >= self._max_frames:
            logger.info("Max chunk duration reached (%d frames), splitting",
                        len(self._frames))
            self._emit_and_reset()
            return

        # Check if we have a pause after speech
        if (self._has_speech
                and self._consecutive_silence >= self._silence_frames
                and len(self._frames) >= self._min_frames):
            # Trim trailing silence (keep a small tail for natural sound)
            tail_keep = min(5, self._consecutive_silence)
            trim_count = self._consecutive_silence - tail_keep
            if trim_count > 0:
                emit_frames = self._frames[:-trim_count]
            else:
                emit_frames = self._frames[:]

            duration_ms = len(emit_frames) * self._cfg.frame_duration_ms
            logger.info("Pause detected: emitting %d frames (%d ms)",
                        len(emit_frames), duration_ms)
            self._emit_chunk(emit_frames)
            self._frames.clear()
            self._consecutive_silence = 0
            self._has_speech = False

    def _emit_and_reset(self) -> None:
        """Emit current buffer and reset."""
        if self._frames:
            self._emit_chunk(self._frames[:])
        self._frames.clear()
        self._consecutive_silence = 0
        self._has_speech = False

    def _emit_chunk(self, frames: list[bytes]) -> None:
        """Package frames as WAV and deliver via callback."""
        wav_bytes = self._pack_wav(frames)
        duration_ms = len(frames) * self._cfg.frame_duration_ms
        logger.info("Emitting chunk: %d frames, %d ms, %d bytes",
                     len(frames), duration_ms, len(wav_bytes))
        if self._callback:
            try:
                self._callback(wav_bytes)
            except Exception:
                logger.exception("Error in chunk callback")

    @staticmethod
    def _pack_wav(frames: list[bytes]) -> bytes:
        """Encode raw PCM frames into an in-memory WAV file."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"".join(frames))
        return buf.getvalue()

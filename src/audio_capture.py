"""Audio capture from microphone using PyAudio in callback (non-blocking) mode.

Delivers raw PCM frames (16 kHz, mono, 16-bit) to a thread-safe queue
for downstream consumption by ChunkManager / VAD pipeline.
"""

from __future__ import annotations

import logging
import queue
import struct
import threading
from dataclasses import dataclass
from typing import Callable

import pyaudio

from .config import AudioConfig
from .utils import compute_rms

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

SAMPLE_FORMAT = pyaudio.paInt16
SAMPLE_WIDTH = 2  # bytes per sample (16-bit)
CHANNELS = 1

# Duration (seconds) to probe each mic when auto-selecting the loudest one.
_PROBE_DURATION_S = 0.3


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AudioDevice:
    """Description of a host audio input device."""

    index: int
    name: str
    channels: int
    default_sample_rate: float


# ── Helpers ─────────────────────────────────────────────────────────────────


def _apply_gain(data: bytes, gain: float) -> bytes:
    """Amplify 16-bit PCM audio by a gain factor, with clipping protection."""
    n_samples = len(data) // SAMPLE_WIDTH
    samples = struct.unpack(f"<{n_samples}h", data[:n_samples * SAMPLE_WIDTH])
    amplified = []
    for s in samples:
        v = int(s * gain)
        # Clip to 16-bit range
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        amplified.append(v)
    return struct.pack(f"<{n_samples}h", *amplified)


# ── Main class ──────────────────────────────────────────────────────────────


class AudioCapture:
    """Non-blocking microphone capture backed by PyAudio callback mode.

    Parameters
    ----------
    config:
        Audio parameters (sample rate, frame duration, device index, ...).
    on_error:
        Optional callback invoked with an exception when the stream encounters
        an error (e.g. mic disconnection).  Called from the PyAudio callback
        thread — keep it lightweight (e.g. set an event or log).
    """

    def __init__(
        self,
        config: AudioConfig,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._config = config
        self._on_error = on_error

        # Derived sizes
        self._frame_samples: int = int(
            config.sample_rate * config.frame_duration_ms / 1000
        )
        self._frame_bytes: int = self._frame_samples * SAMPLE_WIDTH

        self._pa: pyaudio.PyAudio | None = None
        self._pa_lock = threading.RLock()  # protect ALL PyAudio operations (reentrant)
        self._devices_cache: list[AudioDevice] | None = None
        self._stream: pyaudio.Stream | None = None
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._extra_queues: list[queue.Queue[bytes]] = []
        self._device_index: int | None = config.mic_device_index
        self._running: bool = False
        self._gain: float = config.gain  # 0 = auto-gain
        self._auto_gain: float = 4.0  # default until calibrated
        self._gain_calibrated: bool = False
        self._active_device_name: str = ""

    # ── Public API ──────────────────────────────────────────────────────

    def get_frame_queue(self) -> queue.Queue[bytes]:
        """Return the thread-safe queue that receives raw PCM frames."""
        return self._queue

    def add_listener_queue(self) -> queue.Queue[bytes]:
        """Create and return an extra queue that also receives frames (for visualization)."""
        q: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._extra_queues.append(q)
        return q

    def remove_listener_queue(self, q: queue.Queue[bytes]) -> None:
        """Remove a listener queue."""
        try:
            self._extra_queues.remove(q)
        except ValueError:
            pass

    def refresh_devices(self) -> None:
        """Mark device cache as stale so next list_devices() rescans."""
        self._devices_cache = None

    def list_devices(self) -> list[AudioDevice]:
        """Enumerate real input audio devices (filtered, no duplicates).

        Prefers MME devices (hostApi=0), but also includes WASAPI/WDM-KS
        devices (Bluetooth headsets) that have no MME counterpart.
        Skips virtual/system entries.

        Uses shared _pa with lock (no terminate/reinit — prevents segfaults).
        Results are cached; call refresh_devices() to invalidate.
        """
        if self._devices_cache is not None:
            return list(self._devices_cache)

        with self._pa_lock:
            pa = self._ensure_pa()

            skip_substrings = [
                "sound mapper",
                "primary sound",
                "stereo mix",
                "pc speaker",
            ]

            mme_devices: list[AudioDevice] = []
            other_devices: list[AudioDevice] = []

            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                max_input_ch = int(info.get("maxInputChannels", 0))
                if max_input_ch < 1:
                    continue
                name = str(info["name"])
                name_lower = name.lower()
                if any(s in name_lower for s in skip_substrings):
                    continue

                device = AudioDevice(
                    index=i,
                    name=name,
                    channels=max_input_ch,
                    default_sample_rate=float(info["defaultSampleRate"]),
                )

                host_api = int(info.get("hostApi", -1))
                if host_api == 0:  # MME
                    mme_devices.append(device)
                else:
                    other_devices.append(device)

            devices = list(mme_devices)
            mme_names = {d.name.lower()[:20] for d in mme_devices}

            for d in other_devices:
                short_name = d.name.lower()[:20]
                if short_name not in mme_names:
                    devices.append(d)
                    mme_names.add(short_name)

            self._devices_cache = devices
            return list(devices)

    def select_device(self, index: int | None) -> AudioDevice | None:
        """Select a specific input device by index.

        Parameters
        ----------
        index:
            PyAudio device index.  Pass ``None`` to auto-select the loudest
            microphone (see :meth:`_auto_select_loudest`).

        Returns
        -------
        AudioDevice | None
            The selected device, or ``None`` if auto-selection found nothing.
        """
        if index is None:
            device = self._auto_select_loudest()
            if device is not None:
                self._device_index = device.index
                logger.info(
                    "Auto-selected device %d (%s)", device.index, device.name
                )
            else:
                logger.warning("Auto-select found no usable input device")
                self._device_index = None
            return device

        with self._pa_lock:
            pa = self._ensure_pa()
            info = pa.get_device_info_by_index(index)
        if int(info.get("maxInputChannels", 0)) < 1:
            raise ValueError(f"Device {index} ({info['name']}) has no input channels")
        self._device_index = index
        device = AudioDevice(
            index=index,
            name=str(info["name"]),
            channels=int(info["maxInputChannels"]),
            default_sample_rate=float(info["defaultSampleRate"]),
        )
        logger.info("Selected device %d (%s)", device.index, device.name)
        return device

    def start(self) -> None:
        """Open audio stream(s) and begin capturing frames.

        If mic_device_index is set — uses single device.
        If mic_device_index is None — opens ALL mics, picks loudest frame in real-time.
        """
        if self._running:
            raise RuntimeError("AudioCapture is already running")

        # Drain stale frames
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        with self._pa_lock:
            pa = self._ensure_pa()

            if self._device_index is not None:
                # Single device mode
                self._start_single(pa, self._device_index)
            else:
                # Multi-mic mode: open all, pick loudest
                self._start_multi(pa)

        self._running = True
        logger.info("Audio capture started")

    def _start_single(self, pa: pyaudio.PyAudio, device_index: int) -> None:
        """Open a single mic stream."""
        logger.info("Opening single stream: device=%d, rate=%d", device_index, self._config.sample_rate)

        # Auto-gain: use default 4x, calibrate in background for next time
        if self._gain == 0 and not self._gain_calibrated:
            logger.info("Using default gain 4.0x (calibrating in background)")
            import threading as _th
            def _bg_calibrate(pa_ref=pa, dev=device_index):
                try:
                    g = self._calibrate_gain(pa_ref)
                    self._auto_gain = g
                    self._gain_calibrated = True
                    logger.info("Background gain calibrated: %.1fx", g)
                except Exception:
                    pass
            _th.Thread(target=_bg_calibrate, daemon=True).start()

        self._stream = pa.open(
            format=SAMPLE_FORMAT, channels=CHANNELS,
            rate=self._config.sample_rate, input=True,
            input_device_index=device_index,
            frames_per_buffer=self._frame_samples,
            stream_callback=self._stream_callback,
        )
        self._stream.start_stream()
        self._active_device_name = self.get_active_device_name()

    def _start_multi(self, pa: pyaudio.PyAudio) -> None:
        """Open ALL microphones, selector picks loudest per frame."""
        devices = self.list_devices()
        if not devices:
            raise RuntimeError("No usable input device found")

        self._multi_streams: list[tuple[pyaudio.Stream, AudioDevice, queue.Queue]] = []
        self._multi_stop = threading.Event()

        for dev in devices:
            dev_queue: queue.Queue[bytes] = queue.Queue(maxsize=50)
            try:
                def make_cb(q):
                    def cb(in_data, frame_count, time_info, status):
                        if in_data:
                            try:
                                q.put_nowait(in_data)
                            except queue.Full:
                                pass
                        return (None, pyaudio.paContinue)
                    return cb

                stream = pa.open(
                    format=SAMPLE_FORMAT, channels=CHANNELS,
                    rate=self._config.sample_rate, input=True,
                    input_device_index=dev.index,
                    frames_per_buffer=self._frame_samples,
                    stream_callback=make_cb(dev_queue),
                )
                stream.start_stream()
                self._multi_streams.append((stream, dev, dev_queue))
                logger.info("Opened mic: [%d] %s", dev.index, dev.name)
            except Exception as e:
                logger.warning("Cannot open device %d (%s): %s", dev.index, dev.name, e)

        if not self._multi_streams:
            raise RuntimeError("Could not open any microphone")

        logger.info("Multi-mic mode: %d devices active", len(self._multi_streams))
        self._active_device_name = "Multi (auto)"

        # Selector thread: reads from all queues, picks loudest, forwards to main queue
        self._selector_thread = threading.Thread(
            target=self._multi_selector, name="MicSelector", daemon=True,
        )
        self._selector_thread.start()

    def _multi_selector(self) -> None:
        """Read frames from all mic queues, pick the loudest, forward to main queue."""
        while not self._multi_stop.is_set():
            best_data = None
            best_rms = -1.0
            best_name = ""

            for stream, dev, dev_queue in self._multi_streams:
                try:
                    data = dev_queue.get(timeout=0.05)
                    rms = compute_rms(data)
                    if rms > best_rms:
                        best_rms = rms
                        best_data = data
                        best_name = dev.name
                except queue.Empty:
                    continue

            if best_data is not None:
                # Apply gain
                gain = self._auto_gain if self._gain == 0 else self._gain
                if gain != 1.0:
                    best_data = _apply_gain(best_data, gain)

                self._queue.put_nowait(best_data)
                for eq in self._extra_queues:
                    try:
                        eq.put_nowait(best_data)
                    except queue.Full:
                        pass

                # Update active device name (for overlay)
                self._active_device_name = best_name

    def stop(self) -> None:
        """Stop capturing and close all audio streams."""
        if not self._running:
            return
        self._running = False

        # Stop multi-mic
        if hasattr(self, '_multi_stop'):
            self._multi_stop.set()
            for stream, dev, _ in getattr(self, '_multi_streams', []):
                try:
                    if stream.is_active():
                        stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            self._multi_streams = []

        # Stop single stream
        if self._stream is not None:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
            except Exception:
                logger.exception("Error closing audio stream")
            finally:
                self._stream = None

        logger.info("Audio capture stopped")

    @property
    def is_running(self) -> bool:
        """Whether the capture stream is currently active."""
        return self._running

    def get_active_device_name(self) -> str:
        """Return the name of the currently active input device."""
        if hasattr(self, '_active_device_name') and self._active_device_name:
            return self._active_device_name
        if self._device_index is None:
            return "Auto (all mics)"
        try:
            with self._pa_lock:
                pa = self._ensure_pa()
                info = pa.get_device_info_by_index(self._device_index)
            return str(info.get("name", f"Device {self._device_index}"))
        except Exception:
            return f"Device {self._device_index}"

    def detect_new_headset(self, known_device_names: set[str]) -> AudioDevice | None:
        """Check if a new external mic appeared that wasn't in known_device_names.

        Returns the new external device, or None.
        """
        try:
            self.refresh_devices()  # invalidate cache before scanning
            devices = self.list_devices()
            for dev in devices:
                if dev.name not in known_device_names and self._is_external_mic(dev):
                    return dev
        except Exception:
            pass
        return None

    def get_known_device_names(self) -> set[str]:
        """Return names of all currently visible input devices."""
        try:
            return {dev.name for dev in self.list_devices()}
        except Exception:
            return set()

    def terminate(self) -> None:
        """Release all PyAudio resources.

        Call this once at application shutdown.  After termination the
        instance must not be reused.
        """
        self.stop()
        with self._pa_lock:
            if self._pa is not None:
                try:
                    self._pa.terminate()
                except Exception:
                    logger.exception("Error terminating PyAudio")
                finally:
                    self._pa = None

    # ── Private helpers ─────────────────────────────────────────────────

    def _ensure_pa(self) -> pyaudio.PyAudio:
        """Lazily initialise the PyAudio instance (thread-safe)."""
        with self._pa_lock:
            if self._pa is None:
                self._pa = pyaudio.PyAudio()
            return self._pa

    def _calibrate_gain(self, pa: pyaudio.PyAudio) -> float:
        """Probe mic briefly to calculate auto-gain. Target RMS ~3000."""
        TARGET_RMS = 3000.0
        MIN_GAIN = 1.0
        MAX_GAIN = 10.0

        try:
            with self._pa_lock:
                stream = pa.open(
                    format=SAMPLE_FORMAT, channels=CHANNELS,
                    rate=self._config.sample_rate, input=True,
                    input_device_index=self._device_index,
                    frames_per_buffer=self._frame_samples,
                )
                # Read 0.5 second of audio
                n_frames = max(1, int(self._config.sample_rate * 0.5 / self._frame_samples))
                total_rms = 0.0
                peak = 0
                for _ in range(n_frames):
                    data = stream.read(self._frame_samples, exception_on_overflow=False)
                    rms = compute_rms(data)
                    total_rms += rms
                    # Track peak
                    n_samples = len(data) // SAMPLE_WIDTH
                    samples = struct.unpack(f"<{n_samples}h", data[:n_samples * SAMPLE_WIDTH])
                    p = max(abs(s) for s in samples) if samples else 0
                    if p > peak:
                        peak = p

                stream.stop_stream()
                stream.close()

            avg_rms = total_rms / n_frames if n_frames > 0 else 0
            logger.debug("Calibration: avg_rms=%.0f peak=%d", avg_rms, peak)

            if avg_rms < 10:
                # Silence — use moderate gain
                return 4.0

            # Compute gain to reach target, but limit by peak headroom
            gain_by_rms = TARGET_RMS / avg_rms
            # Don't clip: ensure peak * gain < 30000
            max_safe_gain = 30000.0 / peak if peak > 0 else MAX_GAIN
            gain = min(gain_by_rms, max_safe_gain, MAX_GAIN)
            return max(gain, MIN_GAIN)

        except Exception as e:
            logger.warning("Gain calibration failed: %s, using 4x", e)
            return 4.0

    def _stream_callback(
        self,
        in_data: bytes | None,
        frame_count: int,
        time_info: dict,
        status_flags: int,
    ) -> tuple[None, int]:
        """PyAudio callback — runs on a dedicated audio thread.

        Puts raw PCM data onto the queue and signals any errors via
        the ``on_error`` callback.
        """
        try:
            if status_flags:
                logger.warning("PyAudio status flags: %s", status_flags)

            if in_data is not None:
                # Apply gain amplification
                gain = self._auto_gain if self._gain == 0 else self._gain
                if gain != 1.0:
                    in_data = _apply_gain(in_data, gain)

                self._queue.put_nowait(in_data)
                for eq in self._extra_queues:
                    try:
                        eq.put_nowait(in_data)
                    except queue.Full:
                        pass  # Drop frames for visualization, not critical
        except Exception as exc:
            logger.error("Error in audio callback: %s", exc)
            if self._on_error is not None:
                try:
                    self._on_error(exc)
                except Exception:
                    pass  # Never let the error callback crash the audio thread

        return (None, pyaudio.paContinue)

    def _auto_select_loudest(self) -> AudioDevice | None:
        """Select the best input device using priority-based logic.

        Priority order:
          1. Headset / Bluetooth / USB microphones (external devices)
          2. Built-in microphone arrays (fallback)

        Within each priority group, picks the device with highest RMS.

        Returns
        -------
        AudioDevice | None
            The best device, or ``None`` if no device could be probed.
        """
        pa = self._ensure_pa()
        devices = self.list_devices()
        if not devices:
            return None

        probe_frames = max(
            1,
            int(self._config.sample_rate * _PROBE_DURATION_S / self._frame_samples),
        )

        # Classify devices into priority groups
        external: list[tuple[AudioDevice, float]] = []
        builtin: list[tuple[AudioDevice, float]] = []

        for dev in devices:
            rms = self._probe_device_rms(pa, dev, probe_frames)
            if rms is None:
                continue
            logger.info("Device %d (%s): RMS=%.1f, type=%s",
                        dev.index, dev.name, rms,
                        "external" if self._is_external_mic(dev) else "builtin")
            if self._is_external_mic(dev):
                external.append((dev, rms))
            else:
                builtin.append((dev, rms))

        # Prefer external devices; within group pick loudest
        for group in (external, builtin):
            if group:
                group.sort(key=lambda x: x[1], reverse=True)
                return group[0][0]

        return None

    @staticmethod
    def _is_external_mic(dev: AudioDevice) -> bool:
        """Check if a device is an external mic (headset, bluetooth, USB)."""
        name_lower = dev.name.lower()
        external_keywords = [
            "headset", "bluetooth", "usb", "airpods", "buds",
            "jabra", "plantronics", "corsair", "hyperx", "razer",
            "steelseries", "logitech",
        ]
        builtin_keywords = [
            "microphone array", "realtek", "internal", "built-in",
            "pc speaker",
        ]
        if any(kw in name_lower for kw in external_keywords):
            return True
        if any(kw in name_lower for kw in builtin_keywords):
            return False
        # Unknown device — treat as external (safer default)
        return True

    def _probe_device_rms(
        self,
        pa: pyaudio.PyAudio,
        device: AudioDevice,
        num_frames: int,
    ) -> float | None:
        """Open *device* in blocking mode, read *num_frames* and return mean RMS.

        Returns ``None`` if the device cannot be opened or read.
        """
        with self._pa_lock:
            stream: pyaudio.Stream | None = None
            try:
                stream = pa.open(
                    format=SAMPLE_FORMAT,
                    channels=CHANNELS,
                    rate=self._config.sample_rate,
                    input=True,
                    input_device_index=device.index,
                    frames_per_buffer=self._frame_samples,
                )

                total_rms = 0.0
                read_count = 0
                for _ in range(num_frames):
                    data = stream.read(self._frame_samples, exception_on_overflow=False)
                    total_rms += compute_rms(data)
                    read_count += 1

                return total_rms / read_count if read_count > 0 else 0.0

            except Exception as exc:
                logger.debug(
                    "Cannot probe device %d (%s): %s", device.index, device.name, exc
                )
                return None

            finally:
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass

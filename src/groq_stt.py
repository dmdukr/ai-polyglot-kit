"""Groq Whisper API client for speech-to-text transcription.

Sends WAV audio chunks to Groq's Whisper endpoint, filters hallucinations
and low-confidence segments, and returns clean transcribed text.

Uses raw httpx instead of the groq SDK to avoid pydantic-core dependency
(segfaults on Python 3.13).
"""

from __future__ import annotations

import io
import logging
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from typing import Callable

import httpx

from .config import GroqConfig

logger = logging.getLogger(__name__)

# ── Hallucination blocklist ──────────────────────────────────────────────
# Whisper commonly hallucinates these phrases on silence or noise.
HALLUCINATION_BLOCKLIST: set[str] = {
    "thank you for watching",
    "thanks for watching",
    "subscribe",
    "like and subscribe",
    "please subscribe",
    "mbc news",
    "mbc뉴스",
    "подписывайтесь",
    "спасибо за просмотр",
    "дякую за перегляд",
    "подпишитесь на канал",
    "ставьте лайки",
    "продовження наступне",
    "редактор субтитрів",
    "переклад субтитрів",
    "субтитри зроблено",
    "субтитры сделаны",
    "субтитры создавал",
    "редактор субтитров",
    "корректор",
    "you",
    "thank you",
    "thanks",
    "bye",
}

# ── Retry settings ───────────────────────────────────────────────────────
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 2.0  # 2s, 4s, 8s


class GroqSTT:
    """Groq Whisper speech-to-text client with filtering and retry logic."""

    # Warning thresholds in seconds
    WARN_THRESHOLDS = [1800, 600, 300]  # 30 min, 10 min, 5 min

    def __init__(
        self,
        config: GroqConfig,
        executor: Executor | None = None,
        on_quota_warning: Callable[[int, int], None] | None = None,
    ) -> None:
        if not config.api_key:
            raise ValueError(
                "Groq API key is required. "
                "Set GROQ_API_KEY env var, .env file, or config.yaml"
            )

        self._config = config
        self._on_quota_warning = on_quota_warning  # callback(remaining_sec, limit_sec)
        self._quota_limit: int = 0
        self._quota_remaining: int = 0
        self._warned_thresholds: set[int] = set()
        self._http = httpx.Client(
            base_url="https://api.groq.com/openai/v1",
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=30.0,
        )
        self._executor = executor
        self._owns_executor = False

        logger.info(
            "GroqSTT initialised  model=%s  language=%s  temperature=%.1f",
            config.stt_model,
            config.stt_language or "auto",
            config.stt_temperature,
        )

    # ── Public API ───────────────────────────────────────────────────────

    def transcribe(
        self,
        wav_bytes: bytes,
        previous_text: str = "",
    ) -> str | None:
        """Send WAV audio to Groq Whisper and return filtered text or None.

        Args:
            wav_bytes: Raw WAV file content (16 kHz, mono, 16-bit PCM).
            previous_text: Recent transcription context for chunk continuity.

        Returns:
            Transcribed text string, or None when the audio is silent,
            a hallucination, or a repeat of previous_text.
        """
        from .hallucination_filter import check_audio_has_speech, check_text_quality

        # Layer 1: Check audio has actual sound
        if not check_audio_has_speech(wav_bytes):
            logger.debug("Audio rejected: no speech detected (RMS too low)")
            return None

        # Estimate audio duration for length ratio check
        pcm_size = len(wav_bytes) - 44  # subtract WAV header
        audio_duration_s = pcm_size / (16000 * 2)  # 16kHz, 16-bit

        # Build prompt
        prompt_parts = []
        if previous_text:
            prompt_parts.append(previous_text[-100:].strip())

        # Language handling
        kwargs: dict = {}
        lang = self._config.stt_language or ""

        if "," in lang:
            # Multiple languages selected
            lang_codes = [lc.strip() for lc in lang.split(",") if lc.strip()]
            # Map codes to language names for Whisper prompt
            lang_names = {
                "uk": "Українська", "ru": "Русский", "en": "English",
                "de": "Deutsch", "fr": "Français", "es": "Español",
                "pl": "Polski", "it": "Italiano", "pt": "Português",
                "nl": "Nederlands", "tr": "Türkçe", "cs": "Čeština",
                "ja": "日本語", "zh": "中文", "ko": "한국어",
            }
            # Set primary language for API — uk preferred if in list
            # (Whisper with uk still transcribes Russian and English fine)
            if "uk" in lang_codes:
                kwargs["language"] = "uk"
            else:
                kwargs["language"] = lang_codes[0]
            # Add all language names as prompt context
            names = [lang_names.get(c, c) for c in lang_codes]
            prompt_parts.append(", ".join(names) + ".")
        elif lang and lang != "auto":
            # Single language — pass directly to API
            kwargs["language"] = lang
        else:
            # Auto-detect — add generic prompt
            prompt_parts.append("Говоріть будь ласка.")

        prompt = " ".join(prompt_parts)

        response = self._call_api_with_retry(wav_bytes, prompt, kwargs)
        if response is None:
            return None

        text = self._filter_response(response, previous_text, audio_duration_s)
        return text

    def transcribe_async(
        self,
        wav_bytes: bytes,
        callback: Callable[[str | None], None],
        previous_text: str = "",
    ) -> Future:
        """Submit transcription to a background thread.

        Args:
            wav_bytes: Raw WAV file content.
            callback: Called with the result (str or None) when done.
            previous_text: Recent transcription context.

        Returns:
            A Future representing the pending result.
        """
        executor = self._get_executor()

        def _task() -> str | None:
            result = self.transcribe(wav_bytes, previous_text)
            try:
                callback(result)
            except Exception:
                logger.exception("Error in transcribe_async callback")
            return result

        return executor.submit(_task)

    def close(self) -> None:
        """Shut down the HTTP client and internal executor if we own it."""
        self._http.close()
        if self._owns_executor and self._executor is not None:
            self._executor.shutdown(wait=False)
            logger.debug("Internal executor shut down")

    @property
    def quota_remaining_sec(self) -> int:
        return self._quota_remaining

    @property
    def quota_limit_sec(self) -> int:
        return self._quota_limit

    def _update_quota(self, headers) -> None:
        """Parse rate limit headers and fire warnings."""
        try:
            limit = int(headers.get("x-ratelimit-limit-audio-seconds", 0))
            remaining = int(float(headers.get("x-ratelimit-remaining-audio-seconds", 0)))
            if limit > 0:
                self._quota_limit = limit
                self._quota_remaining = remaining
                remaining_min = remaining // 60
                logger.debug("Quota: %d/%d sec remaining (%d min)", remaining, limit, remaining_min)

                # Check warning thresholds
                for threshold in self.WARN_THRESHOLDS:
                    if remaining <= threshold and threshold not in self._warned_thresholds:
                        self._warned_thresholds.add(threshold)
                        logger.warning("Quota warning: %d min remaining!", remaining_min)
                        if self._on_quota_warning:
                            self._on_quota_warning(remaining, limit)
                        break
        except Exception as e:
            logger.debug("Failed to parse quota headers: %s", e)

    # ── Private helpers ──────────────────────────────────────────────────

    def _get_executor(self) -> Executor:
        """Return the executor, creating an internal one if needed."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="groq-stt",
            )
            self._owns_executor = True
            logger.debug("Created internal ThreadPoolExecutor")
        return self._executor

    def _call_api_with_retry(
        self,
        wav_bytes: bytes,
        prompt: str,
        extra_kwargs: dict,
    ) -> dict | None:
        """Call the Groq transcription API with exponential backoff on rate limits.

        Returns the parsed JSON response dict, or None if all attempts fail.
        """
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                audio_file = io.BytesIO(wav_bytes)

                data: dict = {
                    "model": self._config.stt_model,
                    "response_format": "verbose_json",
                    "temperature": str(self._config.stt_temperature),
                }
                if prompt:
                    data["prompt"] = prompt
                for k, v in extra_kwargs.items():
                    data[k] = v

                resp = self._http.post(
                    "/audio/transcriptions",
                    files={"file": ("audio.wav", audio_file, "audio/wav")},
                    data=data,
                )

                # Track quota from headers
                self._update_quota(resp.headers)

                # Handle error status codes
                if resp.status_code == 429:
                    wait = _BACKOFF_BASE_S * (2 ** attempt)
                    logger.warning(
                        "Rate limited (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, _MAX_RETRIES, wait, resp.text[:200],
                    )
                    last_error = Exception(f"Rate limited: {resp.status_code}")
                    time.sleep(wait)
                    continue

                if resp.status_code == 401:
                    logger.error("Authentication failed — check GROQ_API_KEY: %s", resp.text[:200])
                    return None

                if resp.status_code >= 400:
                    logger.error(
                        "Groq API error %d: %s", resp.status_code, resp.text[:200]
                    )
                    return None

                return resp.json()

            except httpx.TimeoutException as exc:
                wait = _BACKOFF_BASE_S * (2 ** attempt)
                logger.warning("API request timed out (attempt %d/%d): %s",
                               attempt + 1, _MAX_RETRIES, exc)
                last_error = exc
                time.sleep(wait)

            except httpx.ConnectError as exc:
                logger.error("Cannot connect to Groq API: %s", exc)
                return None

            except Exception:
                logger.exception("Unexpected error calling Groq API")
                return None

        logger.error(
            "All %d retry attempts exhausted: %s", _MAX_RETRIES, last_error
        )
        return None

    def _filter_response(
        self,
        response: dict,
        previous_text: str,
        audio_duration_s: float = 0,
    ) -> str | None:
        """Apply multi-layer hallucination filtering.

        Uses hallucination_filter module for segment and text level checks.
        """
        from .hallucination_filter import filter_segments, check_text_quality

        # Layer 2-3: Segment-level filtering
        segments = response.get("segments")
        if segments is not None and len(segments) > 0:
            accepted = filter_segments(segments, audio_duration_s)
            text = " ".join(accepted).strip()
        else:
            text = response.get("text", "").strip()

        if not text:
            logger.debug("No text after segment filtering")
            return None

        # Layers 3-6: Text-level quality checks
        result = check_text_quality(text, previous_text, audio_duration_s)
        if result:
            logger.debug("Transcription accepted: %r", result[:80])
        return result

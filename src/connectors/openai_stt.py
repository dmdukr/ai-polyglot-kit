"""OpenAI-compatible STT connector — works with Groq and OpenAI Whisper endpoints.

Sends WAV audio to POST /audio/transcriptions, applies hallucination filtering,
tracks quota from rate-limit headers.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Callable

import httpx

from .base import STTConnector

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE_S = 2.0

# Map language codes to display names (for Whisper prompt)
_LANG_NAMES = {
    "uk": "Українська", "ru": "Русский", "en": "English",
    "de": "Deutsch", "fr": "Français", "es": "Español",
    "pl": "Polski", "it": "Italiano", "pt": "Português",
    "nl": "Nederlands", "tr": "Türkçe", "cs": "Čeština",
    "ja": "日本語", "zh": "中文", "ko": "한국어",
}


class OpenAICompatibleSTT(STTConnector):
    """STT via OpenAI-compatible /audio/transcriptions endpoint (Groq, OpenAI)."""

    WARN_THRESHOLDS = [1800, 600, 300]

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "whisper-large-v3-turbo",
        language: str = "",
        temperature: float = 0.0,
        on_quota_warning: Callable[[int, int], None] | None = None,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._language = language
        self._temperature = temperature
        self._on_quota_warning = on_quota_warning
        self._quota_limit = 0
        self._quota_remaining = 0
        self._warned_thresholds: set[int] = set()
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        logger.info("OpenAICompatibleSTT: base=%s model=%s lang=%s",
                     base_url, model, language or "auto")

    def transcribe(self, wav_bytes, language="", previous_text=""):
        from ..hallucination_filter import check_audio_has_speech, check_text_quality, filter_segments

        if not check_audio_has_speech(wav_bytes):
            logger.debug("Audio rejected: no speech (RMS too low)")
            return None

        pcm_size = len(wav_bytes) - 44
        audio_duration_s = pcm_size / (16000 * 2)

        lang = language or self._language or ""
        prompt_parts = []
        kwargs: dict = {}

        if previous_text:
            prompt_parts.append(previous_text[-100:].strip())

        if "," in lang:
            lang_codes = [lc.strip() for lc in lang.split(",") if lc.strip()]
            if "uk" in lang_codes:
                kwargs["language"] = "uk"
            else:
                kwargs["language"] = lang_codes[0]
            names = [_LANG_NAMES.get(c, c) for c in lang_codes]
            prompt_parts.append(", ".join(names) + ".")
        elif lang and lang != "auto":
            kwargs["language"] = lang
        else:
            prompt_parts.append("Говоріть будь ласка.")

        prompt = " ".join(prompt_parts)
        response = self._call_api(wav_bytes, prompt, kwargs)
        if response is None:
            return None

        return self._filter_response(response, previous_text, audio_duration_s)

    def get_usage(self):
        return (self._quota_limit - self._quota_remaining, self._quota_limit)

    def close(self):
        self._http.close()

    # ── Private ──────────────────────────────────────────────────────

    def _call_api(self, wav_bytes, prompt, extra_kwargs):
        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                data = {
                    "model": self._model,
                    "response_format": "verbose_json",
                    "temperature": str(self._temperature),
                }
                if prompt:
                    data["prompt"] = prompt
                data.update(extra_kwargs)

                resp = self._http.post(
                    "/audio/transcriptions",
                    files={"file": ("audio.wav", io.BytesIO(wav_bytes), "audio/wav")},
                    data=data,
                )
                self._update_quota(resp.headers)

                if resp.status_code == 429:
                    wait = _BACKOFF_BASE_S * (2 ** attempt)
                    logger.warning("Rate limited (attempt %d/%d), retry in %.1fs",
                                   attempt + 1, _MAX_RETRIES, wait)
                    last_error = Exception(f"Rate limited: {resp.status_code}")
                    time.sleep(wait)
                    continue
                if resp.status_code == 401:
                    logger.error("STT auth failed")
                    return None
                if resp.status_code >= 400:
                    logger.error("STT API error %d: %s", resp.status_code, resp.text[:200])
                    return None
                return resp.json()

            except httpx.TimeoutException as exc:
                wait = _BACKOFF_BASE_S * (2 ** attempt)
                logger.warning("STT timeout (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES, exc)
                last_error = exc
                time.sleep(wait)
            except httpx.ConnectError as exc:
                logger.error("Cannot connect to STT API: %s", exc)
                return None
            except Exception:
                logger.exception("Unexpected STT API error")
                return None

        logger.error("All %d STT retries exhausted: %s", _MAX_RETRIES, last_error)
        return None

    def _update_quota(self, headers):
        try:
            limit = int(headers.get("x-ratelimit-limit-audio-seconds", 0))
            remaining = int(float(headers.get("x-ratelimit-remaining-audio-seconds", 0)))
            if limit > 0:
                self._quota_limit = limit
                self._quota_remaining = remaining
                for threshold in self.WARN_THRESHOLDS:
                    if remaining <= threshold and threshold not in self._warned_thresholds:
                        self._warned_thresholds.add(threshold)
                        logger.warning("STT quota: %d min remaining!", remaining // 60)
                        if self._on_quota_warning:
                            self._on_quota_warning(remaining, limit)
                        break
        except Exception as e:
            logger.debug("Failed to parse quota headers: %s", e)

    def _filter_response(self, response, previous_text, audio_duration_s):
        from ..hallucination_filter import filter_segments, check_text_quality

        segments = response.get("segments")
        if segments and len(segments) > 0:
            accepted = filter_segments(segments, audio_duration_s)
            text = " ".join(accepted).strip()
        else:
            text = response.get("text", "").strip()

        if not text:
            return None
        result = check_text_quality(text, previous_text, audio_duration_s)
        if result:
            logger.debug("Transcription accepted: %r", result[:80])
        return result

"""Gladia STT connector — REST API for pre-recorded transcription.

Sends audio file, polls for result. Uses Solaria-1 model.
"""

from __future__ import annotations

import logging
import time

import httpx

from .base import STTConnector

logger = logging.getLogger(__name__)


class GladiaSTT(STTConnector):
    """Gladia speech-to-text via REST API."""

    def __init__(self, api_key: str, model: str = "solaria-1"):
        self._api_key = api_key
        self._model = model
        self._http = httpx.Client(
            base_url="https://api.gladia.io/v2",
            headers={"x-gladia-key": api_key},
            timeout=30.0,
        )
        self._used_seconds = 0
        self._limit_seconds = 0
        logger.info("GladiaSTT: model=%s", model)

    def transcribe(self, wav_bytes, language="", previous_text=""):
        try:
            # Step 1: Upload and start transcription
            files = {"audio": ("audio.wav", wav_bytes, "audio/wav")}
            data = {}
            if language:
                lang = language.split(",")[0].strip() if "," in language else language
                data["language"] = lang

            resp = self._http.post(
                "/transcription",
                files=files,
                data=data,
            )

            if resp.status_code == 401:
                logger.error("Gladia auth failed")
                return None
            if resp.status_code == 429:
                logger.warning("Gladia rate limited")
                return None
            if resp.status_code >= 400:
                logger.error("Gladia API error %d: %s", resp.status_code, resp.text[:200])
                return None

            result = resp.json()

            # Gladia may return result directly or require polling
            if "result" in result:
                text = result["result"].get("transcription", {}).get("full_transcript", "").strip()
                if text:
                    logger.debug("Gladia transcription: %r", text[:80])
                    return text

            # Poll for result if async
            result_url = result.get("result_url", "")
            if result_url:
                return self._poll_result(result_url)

            return None

        except Exception as e:
            logger.error("Gladia error: %s", e)
            return None

    def _poll_result(self, url: str, timeout: float = 30.0) -> str | None:
        """Poll Gladia result URL until transcription is ready."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = self._http.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", "")
                    if status == "done":
                        text = data.get("result", {}).get("transcription", {}).get("full_transcript", "").strip()
                        if text:
                            logger.debug("Gladia transcription (polled): %r", text[:80])
                            return text
                        return None
                    if status == "error":
                        logger.error("Gladia transcription failed")
                        return None
                time.sleep(1.0)
            except Exception as e:
                logger.warning("Gladia poll error: %s", e)
                time.sleep(1.0)
        logger.warning("Gladia poll timed out")
        return None

    def get_usage(self):
        return (self._used_seconds, self._limit_seconds)

    def close(self):
        self._http.close()

"""Speechmatics STT connector — REST API batch transcription.

POST /v2/jobs with audio + config JSON, poll for result.
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from .base import STTConnector

logger = logging.getLogger(__name__)


class SpeechmaticsSTT(STTConnector):
    """Speechmatics speech-to-text via batch REST API."""

    def __init__(self, api_key: str, model: str = "enhanced"):
        self._api_key = api_key
        self._model = model  # "enhanced" or "standard"
        self._http = httpx.Client(
            base_url="https://asr.api.speechmatics.com/v2",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
        self._used_seconds = 0
        self._limit_seconds = 0
        logger.info("SpeechmaticsSTT: model=%s", model)

    def transcribe(self, wav_bytes, language="", previous_text=""):
        try:
            lang = "uk" if not language else language.split(",")[0].strip()

            config = {
                "type": "transcription",
                "transcription_config": {
                    "operating_point": self._model,
                    "language": lang,
                },
            }

            resp = self._http.post(
                "/jobs",
                files={
                    "data_file": ("audio.wav", wav_bytes, "audio/wav"),
                    "config": (None, json.dumps(config), "application/json"),
                },
            )

            if resp.status_code == 401:
                logger.error("Speechmatics auth failed")
                return None
            if resp.status_code == 429:
                logger.warning("Speechmatics rate limited")
                return None
            if resp.status_code >= 400:
                logger.error("Speechmatics API error %d: %s", resp.status_code, resp.text[:200])
                return None

            job = resp.json()
            job_id = job.get("id", "")
            if not job_id:
                logger.error("Speechmatics: no job ID in response")
                return None

            return self._poll_result(job_id)

        except Exception as e:
            logger.error("Speechmatics error: %s", e)
            return None

    def _poll_result(self, job_id: str, timeout: float = 30.0) -> str | None:
        """Poll job status until complete."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = self._http.get(f"/jobs/{job_id}/transcript", params={"format": "txt"})
                if resp.status_code == 200:
                    text = resp.text.strip()
                    if text:
                        logger.debug("Speechmatics transcription: %r", text[:80])
                        return text
                    return None
                if resp.status_code == 404:
                    # Job not ready yet
                    time.sleep(1.0)
                    continue
                if resp.status_code >= 400:
                    logger.error("Speechmatics poll error %d", resp.status_code)
                    return None
            except Exception as e:
                logger.warning("Speechmatics poll error: %s", e)
            time.sleep(1.0)
        logger.warning("Speechmatics poll timed out for job %s", job_id)
        return None

    def get_usage(self):
        return (self._used_seconds, self._limit_seconds)

    def close(self):
        self._http.close()

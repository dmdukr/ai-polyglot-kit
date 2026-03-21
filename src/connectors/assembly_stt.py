"""AssemblyAI STT connector — REST API with upload + poll.

Upload audio → POST /v2/transcript → poll GET /v2/transcript/{id}.
"""

from __future__ import annotations

import logging
import time

import httpx

from .base import STTConnector

logger = logging.getLogger(__name__)


class AssemblySTT(STTConnector):
    """AssemblyAI speech-to-text via REST API."""

    def __init__(self, api_key: str, model: str = "best"):
        self._api_key = api_key
        self._model = model  # "best" or "nano"
        self._http = httpx.Client(
            base_url="https://api.assemblyai.com",
            headers={"authorization": api_key},
            timeout=30.0,
        )
        self._used_seconds = 0
        self._limit_seconds = 0
        logger.info("AssemblySTT: model=%s", model)

    def transcribe(self, wav_bytes, language="", previous_text=""):
        try:
            # Step 1: Upload audio
            upload_resp = self._http.post(
                "/v2/upload",
                content=wav_bytes,
                headers={
                    "authorization": self._api_key,
                    "content-type": "application/octet-stream",
                },
            )
            if upload_resp.status_code != 200:
                logger.error("AssemblyAI upload failed: %d", upload_resp.status_code)
                return None
            audio_url = upload_resp.json().get("upload_url", "")

            # Step 2: Create transcription
            config = {
                "audio_url": audio_url,
                "speech_model": self._model,
            }
            if language:
                lang = language.split(",")[0].strip() if "," in language else language
                config["language_code"] = lang

            resp = self._http.post("/v2/transcript", json=config)
            if resp.status_code == 401:
                logger.error("AssemblyAI auth failed")
                return None
            if resp.status_code >= 400:
                logger.error("AssemblyAI API error %d: %s", resp.status_code, resp.text[:200])
                return None

            transcript_id = resp.json().get("id", "")
            if not transcript_id:
                return None

            # Step 3: Poll for result
            return self._poll_result(transcript_id)

        except Exception as e:
            logger.error("AssemblyAI error: %s", e)
            return None

    def _poll_result(self, transcript_id: str, timeout: float = 30.0) -> str | None:
        """Poll until transcription completes."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = self._http.get(f"/v2/transcript/{transcript_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", "")
                    if status == "completed":
                        text = data.get("text", "").strip()
                        if text:
                            logger.debug("AssemblyAI transcription: %r", text[:80])
                            return text
                        return None
                    if status == "error":
                        logger.error("AssemblyAI transcription error: %s", data.get("error", ""))
                        return None
                time.sleep(1.0)
            except Exception as e:
                logger.warning("AssemblyAI poll error: %s", e)
                time.sleep(1.0)
        logger.warning("AssemblyAI poll timed out for %s", transcript_id)
        return None

    def get_usage(self):
        return (self._used_seconds, self._limit_seconds)

    def close(self):
        self._http.close()

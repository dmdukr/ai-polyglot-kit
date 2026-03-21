"""OpenAI-compatible LLM connector — works with all providers.

Single implementation for: Groq, Google AI Studio, Cerebras, Mistral,
OpenRouter, OpenAI, xAI, GitHub Models — all use /chat/completions.
"""

from __future__ import annotations

import logging
import time

import httpx

from .base import LLMConnector

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE_S = 2.0


class OpenAICompatibleLLM(LLMConnector):
    """LLM via OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, base_url: str, api_key: str, default_model: str = ""):
        self._base_url = base_url
        self._default_model = default_model
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        self._tokens_used = 0
        self._tokens_limit = 0
        logger.info("OpenAICompatibleLLM: base=%s model=%s", base_url, default_model)

    def chat(self, messages, model="", temperature=0.1, max_tokens=2000):
        model = model or self._default_model
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._http.post("/chat/completions", json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                })

                if resp.status_code == 429:
                    wait = _BACKOFF_BASE_S * (2 ** attempt)
                    logger.warning("LLM rate limited (attempt %d/%d), retry in %.1fs",
                                   attempt + 1, _MAX_RETRIES, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code == 401:
                    logger.error("LLM auth failed")
                    return None
                if resp.status_code >= 400:
                    logger.error("LLM API error %d: %s", resp.status_code, resp.text[:200])
                    return None

                data = resp.json()
                usage = data.get("usage", {})
                self._tokens_used += usage.get("total_tokens", 0)
                return data["choices"][0]["message"]["content"].strip()

            except httpx.TimeoutException:
                wait = _BACKOFF_BASE_S * (2 ** attempt)
                logger.warning("LLM timeout (attempt %d/%d)", attempt + 1, _MAX_RETRIES)
                time.sleep(wait)
            except httpx.ConnectError as exc:
                logger.error("Cannot connect to LLM API: %s", exc)
                return None
            except Exception:
                logger.exception("Unexpected LLM error")
                return None

        logger.error("All %d LLM retries exhausted", _MAX_RETRIES)
        return None

    def get_usage(self):
        return (self._tokens_used, self._tokens_limit)

    def close(self):
        self._http.close()

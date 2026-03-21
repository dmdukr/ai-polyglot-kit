"""Provider manager — 3-slot fallback chains for STT, LLM, Translation."""

from __future__ import annotations

import logging

from .connectors.base import STTConnector, LLMConnector
from .connectors.openai_stt import OpenAICompatibleSTT
from .connectors.openai_llm import OpenAICompatibleLLM
from .providers import detect_provider, STT_PROVIDERS

logger = logging.getLogger(__name__)


def _create_stt_connector(slot: dict, on_quota_warning=None) -> STTConnector | None:
    """Create an STT connector from a provider slot config dict."""
    api_key = slot.get("api_key", "")
    if not api_key:
        return None

    provider = slot.get("provider", "")
    base_url = slot.get("base_url", "")
    model = slot.get("model", "whisper-large-v3-turbo")

    # Non-OpenAI-compatible STT providers
    if provider == "Soniox":
        from .connectors.soniox_stt import SonioxSTT
        return SonioxSTT(api_key=api_key, model=model or "stt-async-v4")
    if provider == "Deepgram":
        from .connectors.deepgram_stt import DeepgramSTT
        return DeepgramSTT(api_key=api_key, model=model or "nova-3")
    if provider == "Gladia":
        from .connectors.gladia_stt import GladiaSTT
        return GladiaSTT(api_key=api_key, model=model or "solaria-1")
    if provider == "Speechmatics":
        from .connectors.speechmatics_stt import SpeechmaticsSTT
        return SpeechmaticsSTT(api_key=api_key, model=model or "enhanced")
    if provider == "AssemblyAI":
        from .connectors.assembly_stt import AssemblySTT
        return AssemblySTT(api_key=api_key, model=model or "best")
    if provider in STT_PROVIDERS:
        logger.warning("STT connector for %s not yet implemented", provider)
        return None

    # OpenAI-compatible (Groq, OpenAI)
    if not base_url:
        info = detect_provider(api_key)
        if info:
            base_url = info.base_url
        else:
            logger.warning("Cannot determine base URL for STT slot")
            return None

    return OpenAICompatibleSTT(
        base_url=base_url,
        api_key=api_key,
        model=model,
        on_quota_warning=on_quota_warning,
    )


def _create_llm_connector(slot: dict) -> LLMConnector | None:
    """Create an LLM connector from a provider slot config dict."""
    api_key = slot.get("api_key", "")
    if not api_key:
        return None

    base_url = slot.get("base_url", "")
    model = slot.get("model", "")

    if not base_url:
        info = detect_provider(api_key)
        if info:
            base_url = info.base_url
        else:
            logger.warning("Cannot determine base URL for LLM slot")
            return None

    return OpenAICompatibleLLM(
        base_url=base_url,
        api_key=api_key,
        default_model=model,
    )


class ProviderManager:
    """Manages 3-slot fallback chains for STT, LLM normalization, and translation."""

    def __init__(self, providers_config, on_quota_warning=None):
        self._config = providers_config
        self._on_quota_warning = on_quota_warning

        # Active connector caches (lazy init)
        self._stt_connectors: list[STTConnector | None] = [None, None, None]
        self._llm_connectors: list[LLMConnector | None] = [None, None, None]
        self._trans_connectors: list[LLMConnector | None] = [None, None, None]

        # Track exhausted slots
        self._stt_exhausted: set[int] = set()
        self._llm_exhausted: set[int] = set()
        self._trans_exhausted: set[int] = set()

    # ── STT ──────────────────────────────────────────────────────────

    def get_stt(self) -> STTConnector | None:
        """Get first available STT connector (skip exhausted slots)."""
        for i in range(3):
            if i in self._stt_exhausted:
                continue
            conn = self._get_or_create_stt(i)
            if conn:
                return conn
        # All exhausted — try first non-empty again
        self._stt_exhausted.clear()
        for i in range(3):
            conn = self._get_or_create_stt(i)
            if conn:
                return conn
        return None

    def mark_stt_exhausted(self, connector: STTConnector) -> None:
        """Mark an STT connector's slot as exhausted."""
        for i, c in enumerate(self._stt_connectors):
            if c is connector:
                self._stt_exhausted.add(i)
                logger.info("STT slot #%d marked exhausted, trying next", i + 1)
                break

    def _get_or_create_stt(self, idx: int) -> STTConnector | None:
        if self._stt_connectors[idx]:
            return self._stt_connectors[idx]
        slot = self._config.stt[idx] if idx < len(self._config.stt) else {}
        conn = _create_stt_connector(slot, self._on_quota_warning)
        self._stt_connectors[idx] = conn
        return conn

    # ── LLM (normalization) ──────────────────────────────────────────

    def get_llm(self) -> LLMConnector | None:
        """Get first available LLM connector for normalization."""
        for i in range(3):
            if i in self._llm_exhausted:
                continue
            conn = self._get_or_create_llm(i)
            if conn:
                return conn
        self._llm_exhausted.clear()
        for i in range(3):
            conn = self._get_or_create_llm(i)
            if conn:
                return conn
        return None

    def mark_llm_exhausted(self, connector: LLMConnector) -> None:
        for i, c in enumerate(self._llm_connectors):
            if c is connector:
                self._llm_exhausted.add(i)
                logger.info("LLM slot #%d marked exhausted", i + 1)
                break

    def _get_or_create_llm(self, idx: int) -> LLMConnector | None:
        if self._llm_connectors[idx]:
            return self._llm_connectors[idx]
        slot = self._config.llm[idx] if idx < len(self._config.llm) else {}
        conn = _create_llm_connector(slot)
        self._llm_connectors[idx] = conn
        return conn

    # ── Translation LLM ──────────────────────────────────────────────

    def get_translation_llm(self) -> LLMConnector | None:
        """Get first available LLM connector for translation."""
        for i in range(3):
            if i in self._trans_exhausted:
                continue
            conn = self._get_or_create_trans(i)
            if conn:
                return conn
        self._trans_exhausted.clear()
        for i in range(3):
            conn = self._get_or_create_trans(i)
            if conn:
                return conn
        return None

    def _get_or_create_trans(self, idx: int) -> LLMConnector | None:
        if self._trans_connectors[idx]:
            return self._trans_connectors[idx]
        slot = self._config.translation[idx] if idx < len(self._config.translation) else {}
        conn = _create_llm_connector(slot)
        self._trans_connectors[idx] = conn
        return conn

    # ── Usage info ───────────────────────────────────────────────────

    def get_stt_usage(self) -> list[tuple[str, int, int]]:
        """Return [(provider_name, used, limit), ...] for all STT slots."""
        result = []
        for i in range(3):
            slot = self._config.stt[i] if i < len(self._config.stt) else {}
            name = slot.get("provider", "")
            conn = self._stt_connectors[i]
            if conn:
                used, limit = conn.get_usage()
                result.append((name, used, limit))
            elif name:
                result.append((name, 0, 0))
        return result

    # ── Validation ───────────────────────────────────────────────────

    @staticmethod
    def check_duplicate_keys(slots: list[dict]) -> list[str]:
        """Check for duplicate API keys across slots. Returns warning messages."""
        seen: dict[str, int] = {}
        warnings = []
        for i, slot in enumerate(slots):
            key = slot.get("api_key", "").strip()
            if not key:
                continue
            if key in seen:
                warnings.append(f"Слот #{i + 1} має той самий ключ що й #{seen[key] + 1}")
            else:
                seen[key] = i
        return warnings

    # ── Cleanup ──────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Close all active connectors."""
        for connectors in (self._stt_connectors, self._llm_connectors, self._trans_connectors):
            for conn in connectors:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

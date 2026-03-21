"""Abstract base classes for STT and LLM connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod


class STTConnector(ABC):
    """Interface for speech-to-text providers."""

    @abstractmethod
    def transcribe(self, wav_bytes: bytes, language: str = "",
                   previous_text: str = "") -> str | None:
        """Transcribe WAV audio to text.

        Args:
            wav_bytes: Raw WAV file (16 kHz, mono, 16-bit PCM).
            language: Language hint (ISO code, comma-separated, or empty for auto).
            previous_text: Recent transcription for context continuity.

        Returns:
            Transcribed text, or None on failure/silence/hallucination.
        """

    @abstractmethod
    def get_usage(self) -> tuple[int, int]:
        """Return (used, limit) for quota display. Units vary by provider."""

    @abstractmethod
    def close(self) -> None:
        """Release resources (HTTP clients, sockets)."""


class LLMConnector(ABC):
    """Interface for LLM chat providers (normalization, translation)."""

    @abstractmethod
    def chat(self, messages: list[dict], model: str = "",
             temperature: float = 0.1, max_tokens: int = 2000) -> str | None:
        """Send chat completion. Returns response text or None on failure."""

    @abstractmethod
    def get_usage(self) -> tuple[int, int]:
        """Return (used_tokens, limit_tokens) for quota display."""

    @abstractmethod
    def close(self) -> None:
        """Release resources."""

"""Provider registry — maps API key prefixes to service metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata for a known provider."""

    name: str
    base_url: str
    supports_stt: bool = False
    supports_llm: bool = True


# ── Key-prefix registry (OpenAI-compatible providers) ────────────────────

PROVIDER_REGISTRY: list[tuple[str, ProviderInfo]] = [
    # Longer prefixes first — order matters for matching
    ("sk-or-", ProviderInfo("OpenRouter", "https://openrouter.ai/api/v1")),
    ("sk-proj-", ProviderInfo("OpenAI", "https://api.openai.com/v1", supports_stt=True)),
    ("sk-", ProviderInfo("OpenAI", "https://api.openai.com/v1", supports_stt=True)),
    ("gsk_", ProviderInfo("Groq", "https://api.groq.com/openai/v1", supports_stt=True)),
    ("AIzaSy", ProviderInfo("Google AI Studio", "https://generativelanguage.googleapis.com/v1beta/openai")),
    ("csk-", ProviderInfo("Cerebras", "https://api.cerebras.ai/v1")),
    ("xai-", ProviderInfo("xAI", "https://api.x.ai/v1")),
    ("ghp_", ProviderInfo("GitHub Models", "https://models.inference.ai.azure.com")),
    ("github_pat_", ProviderInfo("GitHub Models", "https://models.inference.ai.azure.com")),
]

# ── Non-OpenAI-compatible STT providers (need specific connectors) ───────

STT_PROVIDERS: dict[str, ProviderInfo] = {
    "Soniox": ProviderInfo("Soniox", "https://stt-rt.soniox.com", supports_stt=True, supports_llm=False),
    "Deepgram": ProviderInfo("Deepgram", "https://api.deepgram.com/v1", supports_stt=True, supports_llm=False),
    "Gladia": ProviderInfo("Gladia", "https://api.gladia.io/v2", supports_stt=True, supports_llm=False),
    "Speechmatics": ProviderInfo("Speechmatics", "https://asr.api.speechmatics.com/v2", supports_stt=True, supports_llm=False),
    "AssemblyAI": ProviderInfo("AssemblyAI", "https://api.assemblyai.com/v2", supports_stt=True, supports_llm=False),
}

# All known provider names (for UI dropdowns)
ALL_STT_PROVIDERS = ["Groq", "OpenAI", "Soniox", "Deepgram", "Gladia", "Speechmatics", "AssemblyAI"]
ALL_LLM_PROVIDERS = ["Groq", "Google AI Studio", "OpenAI", "Cerebras", "OpenRouter", "xAI", "GitHub Models"]
ALL_TRANSLATION_PROVIDERS = ["DeepL", "Groq", "Google AI Studio", "OpenAI", "Cerebras", "OpenRouter", "xAI", "GitHub Models"]


def detect_provider(api_key: str) -> ProviderInfo | None:
    """Detect provider from API key prefix. Returns None if unknown."""
    if not api_key:
        return None
    for prefix, info in PROVIDER_REGISTRY:
        if api_key.startswith(prefix):
            return info
    # DeepL: UUID format with optional :fx suffix
    if api_key.endswith(":fx") or _is_deepl_key(api_key):
        return ProviderInfo("DeepL", "https://api-free.deepl.com/v2", supports_stt=False, supports_llm=False)
    return None


def _is_deepl_key(key: str) -> bool:
    """Check if key looks like a DeepL API key (UUID format)."""
    import re
    # DeepL keys: UUID with optional :fx suffix
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(:[a-z]+)?$', key))


def get_provider_base_url(provider_name: str) -> str:
    """Get base URL for a known provider by name."""
    for _, info in PROVIDER_REGISTRY:
        if info.name == provider_name:
            return info.base_url
    if provider_name in STT_PROVIDERS:
        return STT_PROVIDERS[provider_name].base_url
    return ""


def fetch_models(base_url: str, api_key: str, stt: bool = False) -> list[str]:
    """Fetch available model IDs from provider's GET /models endpoint.

    Args:
        base_url: Provider's OpenAI-compatible base URL.
        api_key: API key for authentication.
        stt: If True, filter for audio/whisper models only.
             If False, filter out audio/embedding models.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code != 200:
                logger.warning("Failed to fetch models from %s: %d", base_url, resp.status_code)
                return []
            data = resp.json()
            models = []
            for m in data.get("data", []):
                model_id = m.get("id", "")
                if not model_id:
                    continue
                if stt:
                    if "whisper" in model_id.lower() or "transcri" in model_id.lower():
                        models.append(model_id)
                else:
                    skip = ("whisper", "embed", "tts", "dall", "guard", "orpheus")
                    if not any(x in model_id.lower() for x in skip):
                        models.append(model_id)
            return sorted(models)
    except Exception as e:
        logger.warning("Cannot fetch models from %s: %s", base_url, e)
        return []

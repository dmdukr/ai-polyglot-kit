"""Translation engine — DeepL (key rotation) -> LLM -> Groq legacy fallback.

Extracted from translate_overlay so both the GUI overlay and the HTTP server
can share the same translation logic.
"""

from __future__ import annotations

import logging

import httpx

from .config import GroqConfig
from .provider_manager import ProviderManager
from .utils import load_deepl_keys

logger = logging.getLogger(__name__)

# ── Languages ─────────────────────────────────────────────────────────

LANGUAGES = [
    ("English", "en"),
    ("Ukrainian", "uk"),
    ("Russian", "ru"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Polish", "pl"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Japanese", "ja"),
    ("Chinese", "zh"),
    ("Korean", "ko"),
    ("Turkish", "tr"),
    ("Arabic", "ar"),
]

TRANSLATE_PROMPT = """\
Translate the following text to {language}.
Return ONLY the translation, no explanations or commentary.
Preserve formatting, line breaks, and punctuation style."""

# DeepL language code mapping (codes that differ from our short codes)
_DEEPL_LANG_MAP = {"EN": "EN-US", "PT": "PT-BR", "ZH": "ZH-HANS"}


class TranslateEngine:
    """Stateless-ish translation engine with DeepL key rotation + LLM fallback."""

    def __init__(
        self,
        provider_manager: ProviderManager | None = None,
        groq_config: GroqConfig | None = None,
    ):
        self._provider_manager = provider_manager
        self._groq = groq_config
        self._deepl_rotation_idx = 0

    # ── public API ────────────────────────────────────────────────────

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> tuple[str, str]:
        """Translate *text* to *target_lang*.

        *target_lang* may be a language name (``"English"``) or a two-letter
        code (``"en"``).  Returns ``(translated_text, engine_name)``.
        """
        lang_code = self._resolve_lang_code(target_lang)
        lang_name = self._resolve_lang_name(target_lang)

        # 1. Try DeepL with key rotation
        keys = load_deepl_keys()
        if keys:
            for attempt in range(len(keys)):
                key = self._next_deepl_key(keys)
                try:
                    result = self._translate_deepl(text, lang_code, key, source_lang=source_lang)
                    key_num = (self._deepl_rotation_idx - 1) % len(keys) + 1
                    logger.info("DeepL OK (key #%d)", key_num)
                    return result, f"DeepL #{key_num}"
                except ValueError as e:
                    if "quota exceeded" in str(e).lower():
                        logger.warning("DeepL key quota exceeded, trying next")
                        continue
                    raise
                except Exception as e:
                    logger.warning("DeepL failed: %s", e)
                    continue

            logger.warning("All DeepL keys exhausted, falling back to LLM")

        # 2. Fallback to translation LLM via ProviderManager
        if self._provider_manager:
            llm = self._provider_manager.get_translation_llm()
            if llm:
                try:
                    result = llm.chat(
                        [
                            {"role": "system", "content": TRANSLATE_PROMPT.format(language=lang_name)},
                            {"role": "user", "content": text},
                        ],
                        temperature=0.3,
                    )
                    return result, "LLM"
                except Exception as e:
                    logger.warning("Translation LLM failed: %s", e)

        # 3. Legacy fallback to groq.api_key
        if self._groq and self._groq.api_key:
            result = self._translate_groq(text, lang_name)
            return result, "Groq LLM"

        raise ValueError(
            "Не налаштовано жодного сервісу перекладу. "
            "Додайте API ключ у Налаштування \u2192 Переклад"
        )

    def translate_batch(
        self,
        texts: list[str],
        target_lang: str,
        source_lang: str = "auto",
    ) -> tuple[list[str], str]:
        """Translate a list of texts to *target_lang*.

        DeepL supports native batch via multiple ``text`` form params.
        LLM/Groq fall back to one-by-one calls.

        Returns ``(list_of_translated, engine_name)``.
        """
        if not texts:
            return [], ""

        lang_code = self._resolve_lang_code(target_lang)

        # 1. Try DeepL batch
        keys = load_deepl_keys()
        if keys:
            for attempt in range(len(keys)):
                key = self._next_deepl_key(keys)
                try:
                    results = self._translate_deepl_batch(texts, lang_code, key, source_lang=source_lang)
                    key_num = (self._deepl_rotation_idx - 1) % len(keys) + 1
                    logger.info("DeepL batch OK (key #%d, %d texts)", key_num, len(texts))
                    return results, f"DeepL #{key_num}"
                except ValueError as e:
                    if "quota exceeded" in str(e).lower():
                        logger.warning("DeepL key quota exceeded, trying next")
                        continue
                    raise
                except Exception as e:
                    logger.warning("DeepL batch failed: %s", e)
                    continue

            logger.warning("All DeepL keys exhausted for batch, falling back to LLM")

        # 2/3. LLM / Groq — one-by-one fallback
        results = []
        engine = ""
        for text in texts:
            translated, engine = self.translate(text, target_lang, source_lang)
            results.append(translated)
        return results, engine

    # ── internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _resolve_lang_code(target_lang: str) -> str:
        """Convert a language name or code to the two-letter code."""
        for name, code in LANGUAGES:
            if name == target_lang or code == target_lang:
                return code
        return target_lang.lower()[:2] if target_lang else "en"

    @staticmethod
    def _resolve_lang_name(target_lang: str) -> str:
        """Convert a language code or name to the display name."""
        for name, code in LANGUAGES:
            if name == target_lang or code == target_lang:
                return name
        return target_lang

    def _next_deepl_key(self, keys: list[str]) -> str:
        if not keys:
            return ""
        idx = self._deepl_rotation_idx % len(keys)
        self._deepl_rotation_idx += 1
        return keys[idx]

    @staticmethod
    def _deepl_target_lang(lang_code: str) -> str:
        """Map our short code to DeepL's expected target_lang value."""
        deepl_lang = lang_code.upper()
        return _DEEPL_LANG_MAP.get(deepl_lang, deepl_lang)

    def _translate_deepl(
        self,
        text: str,
        target_lang: str,
        api_key: str,
        *,
        source_lang: str = "auto",
    ) -> str:
        base_url = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
        deepl_lang = self._deepl_target_lang(target_lang)

        data: dict = {"text": text, "target_lang": deepl_lang}
        if source_lang != "auto":
            data["source_lang"] = source_lang.upper()

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{base_url}/v2/translate",
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                data=data,
            )
            if resp.status_code == 456:
                raise ValueError("DeepL quota exceeded for this key")
            resp.raise_for_status()
            body = resp.json()
            translations = body.get("translations", [])
            if translations:
                return translations[0].get("text", "")
            raise ValueError("No translations in DeepL response")

    def _translate_deepl_batch(
        self,
        texts: list[str],
        target_lang: str,
        api_key: str,
        *,
        source_lang: str = "auto",
    ) -> list[str]:
        """Translate multiple texts in one DeepL API call (multiple ``text`` params)."""
        base_url = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
        deepl_lang = self._deepl_target_lang(target_lang)

        # httpx supports list values for form data via list of tuples
        form_data: list[tuple[str, str]] = [("text", t) for t in texts]
        form_data.append(("target_lang", deepl_lang))
        if source_lang != "auto":
            form_data.append(("source_lang", source_lang.upper()))

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{base_url}/v2/translate",
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                data=form_data,
            )
            if resp.status_code == 456:
                raise ValueError("DeepL quota exceeded for this key")
            resp.raise_for_status()
            body = resp.json()
            translations = body.get("translations", [])
            return [tr.get("text", "") for tr in translations]

    def _translate_groq(self, text: str, target_language: str) -> str:
        with httpx.Client(
            base_url="https://api.groq.com/openai/v1",
            headers={"Authorization": f"Bearer {self._groq.api_key}"},
            timeout=30.0,
        ) as client:
            resp = client.post(
                "/chat/completions",
                json={
                    "model": self._groq.llm_model,
                    "messages": [
                        {"role": "system", "content": TRANSLATE_PROMPT.format(language=target_language)},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

"""Text normalization via Groq LLM — session-based architecture.

Instead of sending a fresh prompt with every dictation, maintains a persistent
conversation session with the LLM.  The system prompt (corrections, terms,
rules) is sent ONCE.  Each dictation is a new user message in the same
conversation, so the LLM remembers context and makes smarter term decisions.

Session lifecycle:
  1. First dictation → open session (system prompt sent once)
  2. Subsequent dictations → append to conversation
  3. At 80% context window → handoff:
     a. Ask OLD session to summarize context
     b. Collect golden texts (edited || normalized) from triads
     c. Open NEW session with prompt + summary + golden texts
  4. 30 min inactivity → reset session
"""

import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .config import NormalizationConfig
from .connectors.base import LLMConnector

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

# llama-3.3-70b context window
MAX_CONTEXT_TOKENS = 128_000
HANDOFF_THRESHOLD = 0.80  # 80% → trigger handoff
INACTIVITY_TIMEOUT_S = 30 * 60  # 30 min

SYSTEM_PROMPT = """\
You are a speech-to-text post-processor running inside a dictation app.
You receive raw voice transcriptions one at a time and return ONLY the corrected text.

RULES:
1. Remove filler words: ну, эм, ээ, типа, как бы, значит, короче, like, uh, um, so.
2. Fix misrecognized words. Whisper confuses similar syllables (е/и, а/о, в/б, пре/при/вы).
   Use context, common phrases, idioms, well-known quotes to determine the correct word.
3. Fix punctuation, capitalization, number formatting ("двадцять третє" → "23-тє").
4. NEVER translate between languages — keep English as English, Ukrainian as Ukrainian, Russian as Russian.
5. NEVER add text that wasn't in the original.
6. Return ONLY the corrected text, no explanations or commentary.

You will receive multiple dictations during this session.
Use conversation context to make smarter decisions about ambiguous terms.

{profile_section}"""

HANDOFF_SUMMARY_PROMPT = """\
Summarize this conversation in 2-3 sentences for context handoff to a new session.
Focus on: what topics were discussed, which domain terms appeared, what language mix was used.
Be concise — this summary will be injected as context for the next session."""


class Normalizer:
    """Session-based normalizer — maintains LLM conversation state."""

    def __init__(self, llm: LLMConnector | None, norm_config: NormalizationConfig,
                 profile=None):
        self._llm = llm
        self._norm_config = norm_config
        self._profile = profile

        # Session state
        self._messages: list[dict] = []
        self._session_tokens: int = 0
        self._last_activity: float = 0
        self._session_active: bool = False
        self._lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────────────

    def normalize(self, raw_text: str, context: str = "") -> str:
        """Normalize raw transcription using session-based LLM conversation.

        Args:
            raw_text: Raw transcription from Whisper.
            context: Text from active window (paragraph before cursor).
        """
        if not raw_text.strip():
            return raw_text

        if not self._norm_config.enabled:
            return raw_text

        with self._lock:
            # Check inactivity timeout
            if (self._session_active
                    and self._last_activity > 0
                    and time.monotonic() - self._last_activity > INACTIVITY_TIMEOUT_S):
                logger.info("Session expired (inactivity %ds)", INACTIVITY_TIMEOUT_S)
                self._reset_session()

            # Check context window threshold
            if (self._session_active
                    and self._session_tokens > MAX_CONTEXT_TOKENS * HANDOFF_THRESHOLD):
                logger.info(
                    "Session at %d/%d tokens (%.0f%%) — triggering handoff",
                    self._session_tokens, MAX_CONTEXT_TOKENS,
                    self._session_tokens / MAX_CONTEXT_TOKENS * 100,
                )
                self._do_handoff()

            # Start new session if needed
            if not self._session_active:
                self._start_session()

            self._last_activity = time.monotonic()

        # Build user message
        lang_instruction = self._detect_language_instruction(raw_text)
        user_msg = raw_text
        if lang_instruction:
            user_msg = f"[{lang_instruction}]\n{raw_text}"
        if context.strip():
            user_msg = f"[Context in document: {context.strip()[:200]}]\n{user_msg}"

        # Send to LLM
        result = self._send_message(user_msg)
        if not result:
            return raw_text

        logger.info("Normalized: %d → %d chars", len(raw_text), len(result))
        return result

    def normalize_async(
        self,
        raw_text: str,
        callback: Callable[[str], None],
        executor: ThreadPoolExecutor | None = None,
        context: str = "",
    ) -> None:
        """Submit normalization to thread pool."""
        if executor:
            future = executor.submit(self.normalize, raw_text, context)
            future.add_done_callback(
                lambda f: callback(f.result() if not f.exception() else raw_text)
            )
        else:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.normalize, raw_text, context)
                callback(future.result())

    def get_session_info(self) -> dict:
        """Return session diagnostics."""
        with self._lock:
            return {
                "active": self._session_active,
                "tokens": self._session_tokens,
                "tokens_pct": round(self._session_tokens / MAX_CONTEXT_TOKENS * 100, 1) if self._session_tokens else 0,
                "messages": len(self._messages),
                "threshold": HANDOFF_THRESHOLD,
            }

    # ── Session Management ──────────────────────────────────────────────

    def _start_session(self, handoff_context: str = "") -> None:
        """Initialize a new LLM session with system prompt."""
        # Build profile section
        profile_section = ""
        if self._profile:
            profile_ctx = self._profile.get_prompt_context()
            if profile_ctx:
                profile_section = f"\n{profile_ctx}"
                logger.info("Profile injected into session (%d chars)", len(profile_ctx))

        system_content = SYSTEM_PROMPT.format(profile_section=profile_section)

        # Add handoff context if this is a continuation
        if handoff_context:
            system_content += f"\n\nPREVIOUS SESSION CONTEXT:\n{handoff_context}"
            logger.info("Handoff context injected (%d chars)", len(handoff_context))

        self._messages = [{"role": "system", "content": system_content}]
        self._session_tokens = len(system_content) // 3  # rough estimate until first API call
        self._session_active = True
        self._last_activity = time.monotonic()
        logger.info(
            "Session started (est. %d tokens, %d chars system prompt)",
            self._session_tokens, len(system_content),
        )

    def _reset_session(self) -> None:
        """Close session without handoff."""
        self._messages.clear()
        self._session_tokens = 0
        self._session_active = False
        logger.info("Session reset")

    def _do_handoff(self) -> None:
        """Perform session handoff: summarize old → start new."""
        # Step 1: Ask old session for context summary
        summary = self._get_session_summary()

        # Step 2: Collect golden texts from profile triads
        golden_texts = self._collect_golden_texts()

        # Step 3: Build handoff context
        parts = []
        if summary:
            parts.append(f"Summary: {summary}")
        if golden_texts:
            parts.append(f"Recent dictations (user-approved text):\n{golden_texts}")

        handoff_context = "\n\n".join(parts) if parts else ""

        # Step 4: Reset and start new session
        self._messages.clear()
        self._session_tokens = 0
        self._session_active = False
        self._start_session(handoff_context)

        logger.info("Handoff complete: summary=%d chars, golden=%d chars",
                     len(summary), len(golden_texts))

    def _get_session_summary(self) -> str:
        """Ask current session to summarize conversation context."""
        if not self._llm or len(self._messages) < 3:
            return ""

        try:
            messages = self._messages + [
                {"role": "user", "content": HANDOFF_SUMMARY_PROMPT}
            ]
            summary = self._llm.chat(messages, temperature=0.3, max_tokens=300)
            if summary:
                logger.info("Session summary: %s", summary[:100])
            return summary or ""

        except Exception as e:
            logger.warning("Failed to get session summary: %s", e)
            return ""

    def _collect_golden_texts(self) -> str:
        """Collect best version of each dictation from profile history."""
        if not self._profile:
            return ""

        try:
            with self._profile._lock:
                history = self._profile._data.get("history", [])

            if not history:
                return ""

            lines = []
            # Last 20 entries to keep it manageable
            for h in history[-20:]:
                edited = h.get("edited", "").strip()
                normalized = h.get("normalized", "").strip()
                best = edited if edited else normalized
                if best:
                    lines.append(f"- {best}")

            return "\n".join(lines) if lines else ""

        except Exception as e:
            logger.warning("Failed to collect golden texts: %s", e)
            return ""

    # ── LLM Communication ───────────────────────────────────────────────

    def _send_message(self, user_content: str) -> str | None:
        """Send a message in the current session and get response."""
        if not self._llm:
            logger.warning("No LLM connector available for normalization")
            return None

        with self._lock:
            self._messages.append({"role": "user", "content": user_content})

        try:
            result = self._llm.chat(
                messages=self._messages,
                temperature=self._norm_config.temperature,
                max_tokens=2000,
            )

            if result is None:
                with self._lock:
                    self._messages.pop()
                return None

            # Estimate token usage (LLM connector tracks internally)
            with self._lock:
                self._session_tokens += len(user_content) // 3 + len(result) // 3
                self._messages.append({"role": "assistant", "content": result})

            logger.info("LLM response (%d tokens est.): '%s'",
                        self._session_tokens, result[:100])
            return result

        except Exception as e:
            logger.error("LLM error: %s", e)
            with self._lock:
                self._messages.pop()
            return None

    # ── Utilities ────────────────────────────────────────────────────────

    @staticmethod
    def _detect_language_instruction(text: str) -> str:
        """Detect dominant language by character analysis."""
        uk_chars = set("іїєґІЇЄҐ")
        ru_chars = set("ёъыЁЪЫэЭ")
        latin_count = sum(1 for c in text if c.isalpha() and c.isascii())
        cyrillic_count = sum(1 for c in text if c.isalpha() and not c.isascii())
        uk_count = sum(1 for c in text if c in uk_chars)
        ru_count = sum(1 for c in text if c in ru_chars)

        total = latin_count + cyrillic_count
        if total == 0:
            return ""

        if cyrillic_count > latin_count:
            if uk_count > 0 and ru_count == 0:
                return "Language: Ukrainian"
            elif ru_count > 0 and uk_count == 0:
                return "Language: Russian"
            elif uk_count > ru_count:
                return "Language: Ukrainian (primary)"
            elif ru_count > uk_count:
                return "Language: Russian (primary)"
            else:
                return "Language: Cyrillic (preserve original)"
        elif latin_count > cyrillic_count:
            return "Language: English"
        else:
            return "Language: Mixed (preserve each word's language)"

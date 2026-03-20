"""User Profile — structured MD-based learning system for normalization.

Architecture:
  1. Storage (user_profile.md) — human-readable/editable facts
  2. Rule compiler — detects patterns from corrections → generates rules
  3. Prompt generator — builds normalization context from rules + facts
  4. Conflict resolver — newer data overrides older contradictions

Sections in profile MD:
  - Meta: session stats, language mix
  - Rules: auto-generated or user-edited behavioral rules
  - Corrections: word-level pairs (whisper→correct)
  - Vocabulary: frequent domain terms
  - Proper Nouns: capitalized terms
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import APP_DIR

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

PROFILE_PATH = APP_DIR / "user_profile.md"
PROFILE_JSON_PATH = APP_DIR / "user_profile.json"  # legacy, for migration

MAX_CORRECTIONS = 200
MAX_VOCABULARY = 500
MAX_PROPER_NOUNS = 100
MIN_CORRECTION_COUNT = 2    # auto-corrections need 2+ hits; feedback = instant
DECAY_DAYS = 90
SAVE_DEBOUNCE_S = 10

# ── Stopwords ────────────────────────────────────────────────────────────

STOPWORDS: set[str] = {
    # Russian
    "и", "в", "на", "с", "не", "что", "это", "как", "а", "но", "да", "нет",
    "он", "она", "они", "мы", "вы", "я", "мне", "его", "её", "их", "то",
    "за", "по", "из", "от", "до", "для", "при", "без", "так", "же", "ещё",
    "уже", "ну", "вот", "тут", "там", "где", "когда", "если", "чтобы",
    "который", "которая", "которые", "был", "была", "было", "были",
    "быть", "есть", "будет", "можно", "нужно", "надо", "очень",
    "или", "ты", "тебе", "тебя", "себя", "себе", "свой", "свою", "своё",
    "этот", "эта", "эти", "тот", "та", "те", "все", "всё", "весь",
    # Ukrainian
    "і", "й", "та", "на", "з", "не", "що", "це", "як", "але", "так",
    "він", "вона", "вони", "ми", "ви", "мені", "його", "її", "їх",
    "із", "від", "до", "для", "при", "без", "ще", "вже",
    "ось", "де", "коли", "якщо", "щоб", "який", "яка", "які",
    "був", "була", "було", "були", "бути", "є", "буде", "можна", "треба",
    "цей", "ця", "ці", "той", "та", "ті", "все", "увесь",
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "must", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "and", "but", "or", "not", "no", "so", "if", "then", "than", "that",
    "this", "it", "its", "i", "you", "he", "she", "we", "they", "me",
    "him", "her", "us", "them", "my", "your", "his", "our", "their",
    "just", "also", "very", "too", "here", "there", "when", "where",
    "how", "what", "which", "who", "whom", "why", "all", "each",
}

# ── Helpers ──────────────────────────────────────────────────────────────


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _extract_corrections(raw: str, normalized: str) -> list[tuple[str, str]]:
    """Extract word-level corrections by diffing raw vs normalized text."""
    raw_words = raw.strip().split()
    norm_words = normalized.strip().split()

    if not raw_words or not norm_words:
        return []

    matcher = difflib.SequenceMatcher(None,
                                      [w.lower().strip(".,!?;:\"'()") for w in raw_words],
                                      [w.lower().strip(".,!?;:\"'()") for w in norm_words])
    corrections = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace":
            raw_phrase = " ".join(w.strip(".,!?;:\"'()") for w in raw_words[i1:i2]).lower()
            norm_phrase = " ".join(w.strip(".,!?;:\"'()") for w in norm_words[j1:j2])
            # Skip trivial / empty
            if not raw_phrase.strip() or not norm_phrase.strip():
                continue
            if raw_phrase == norm_phrase.lower():
                continue
            # Only 1-2 word replacements (not reformulations)
            if len(raw_phrase.split()) > 2 or len(norm_phrase.split()) > 2:
                continue
            corrections.append((raw_phrase, norm_phrase))

    return corrections


def _extract_vocabulary(text: str) -> list[str]:
    """Extract meaningful words from text, excluding stopwords."""
    words = re.findall(r"[\w']+", text.lower())
    return [w for w in words if len(w) >= 3 and w not in STOPWORDS and not w.isdigit()]


def _extract_proper_nouns(text: str) -> list[str]:
    """Extract words that appear capitalized mid-sentence."""
    sentences = re.split(r"[.!?]\s+", text)
    nouns = []
    for sent in sentences:
        words = sent.split()
        for w in words[1:]:
            if len(w) >= 2 and w[0].isupper() and not w.isupper():
                clean = w.strip(".,!?;:\"'()")
                if clean and len(clean) >= 2:
                    nouns.append(clean)
    return nouns


# ── MD Parser / Writer ───────────────────────────────────────────────────


def _parse_profile_md(text: str) -> dict:
    """Parse user_profile.md into structured data."""
    data = {
        "meta": {"sessions": 0, "cyrillic": 0.5, "latin": 0.5},
        "rules": [],
        "corrections": {},
        "vocabulary": {},
        "proper_nouns": {},
        "compiled_prompt": "",
        "history": [],  # list of {"ts", "raw", "normalized", "edited"}
    }

    current_section = None
    for line in text.splitlines():
        line_stripped = line.strip()

        # Section headers
        if line_stripped.startswith("## "):
            header = line_stripped[3:].strip().lower()
            if "meta" in header:
                current_section = "meta"
            elif "rule" in header:
                current_section = "rules"
            elif "correction" in header:
                current_section = "corrections"
            elif "vocab" in header:
                current_section = "vocabulary"
            elif "noun" in header or "proper" in header:
                current_section = "proper_nouns"
            elif "compiled" in header or "prompt" in header:
                current_section = "compiled_prompt"
            elif "histor" in header:
                current_section = "history"
            else:
                current_section = None
            continue

        if not line_stripped or line_stripped.startswith("<!--") or line_stripped.startswith("#"):
            continue

        # Parse by section
        if current_section == "meta":
            if "sessions:" in line_stripped.lower():
                m = re.search(r"(\d+)", line_stripped)
                if m:
                    data["meta"]["sessions"] = int(m.group(1))
            elif "language" in line_stripped.lower() or "cyrillic" in line_stripped.lower():
                m = re.search(r"(\d+)%?\s*/\s*(\d+)%?", line_stripped)
                if m:
                    cyr = int(m.group(1)) / 100
                    lat = int(m.group(2)) / 100
                    data["meta"]["cyrillic"] = cyr
                    data["meta"]["latin"] = lat

        elif current_section == "rules":
            if line_stripped.startswith("- "):
                data["rules"].append(line_stripped[2:].strip())

        elif current_section == "corrections":
            # Format: | wrong | right | count | source | date |
            if line_stripped.startswith("|") and "---" not in line_stripped:
                parts = [p.strip() for p in line_stripped.split("|")[1:-1]]
                if len(parts) >= 3:
                    wrong, right, count_str = parts[0], parts[1], parts[2]
                    if wrong and right and count_str.isdigit():
                        source = parts[3] if len(parts) > 3 else "auto"
                        date = parts[4] if len(parts) > 4 else _today()
                        key = f"{wrong}|{right}"
                        data["corrections"][key] = {
                            "count": int(count_str),
                            "source": source,
                            "last_seen": date,
                        }

        elif current_section == "vocabulary":
            # Format: term (count)
            m = re.match(r"[-*]\s*`?(\S+?)`?\s*\((\d+)\)", line_stripped)
            if m:
                data["vocabulary"][m.group(1)] = {
                    "count": int(m.group(2)),
                    "last_seen": _today(),
                }

        elif current_section == "proper_nouns":
            m = re.match(r"[-*]\s*(\S+)", line_stripped)
            if m:
                data["proper_nouns"][m.group(1)] = {
                    "count": 1,
                    "last_seen": _today(),
                }

        elif current_section == "compiled_prompt":
            # Accumulate all lines as the compiled prompt
            existing = data.get("compiled_prompt", "")
            data["compiled_prompt"] = (existing + "\n" + line_stripped).strip()

        elif current_section == "history":
            # Format: | timestamp | raw | normalized | edited |
            if line_stripped.startswith("|") and "---" not in line_stripped:
                parts = [p.strip() for p in line_stripped.split("|")[1:-1]]
                if len(parts) >= 3 and parts[0] and parts[0][0].isdigit():
                    entry = {
                        "ts": parts[0],
                        "raw": parts[1],
                        "normalized": parts[2],
                        "edited": parts[3] if len(parts) > 3 else "",
                    }
                    data.setdefault("history", []).append(entry)

    return data


def _render_profile_md(data: dict) -> str:
    """Render structured data to user_profile.md format."""
    lines = ["# User Profile", ""]

    # Meta
    meta = data.get("meta", {})
    lines.append("## Meta")
    lines.append(f"- Sessions: {meta.get('sessions', 0)}")
    cyr = int(meta.get("cyrillic", 0.5) * 100)
    lat = int(meta.get("latin", 0.5) * 100)
    lines.append(f"- Languages: cyrillic {cyr}% / latin {lat}%")
    lines.append(f"- Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # Rules
    rules = data.get("rules", [])
    lines.append("## Rules")
    lines.append("<!-- Auto-generated from patterns. You can edit/add/remove rules. -->")
    if rules:
        for rule in rules:
            lines.append(f"- {rule}")
    else:
        lines.append("- *(no rules yet — they will be auto-generated from your corrections)*")
    lines.append("")

    # Corrections
    corrections = data.get("corrections", {})
    lines.append("## Corrections")
    lines.append("<!-- Format: wrong → right. Edit freely — your changes are respected. -->")
    if corrections:
        lines.append("| Wrong | Right | Count | Source | Date |")
        lines.append("|-------|-------|-------|--------|------|")
        # Sort: feedback first, then by count
        sorted_corr = sorted(
            corrections.items(),
            key=lambda x: (0 if x[1].get("source") == "feedback" else 1, -x[1].get("count", 0)),
        )
        for key, entry in sorted_corr:
            parts = key.split("|", 1)
            if len(parts) == 2:
                lines.append(
                    f"| {parts[0]} | {parts[1]} | {entry.get('count', 0)} "
                    f"| {entry.get('source', 'auto')} | {entry.get('last_seen', '')} |"
                )
    else:
        lines.append("*(no corrections yet)*")
    lines.append("")

    # Vocabulary
    vocab = data.get("vocabulary", {})
    lines.append("## Vocabulary")
    lines.append("<!-- Your frequent terms — preferred spellings. -->")
    if vocab:
        sorted_vocab = sorted(vocab.items(), key=lambda x: -x[1].get("count", 0))
        for word, entry in sorted_vocab[:50]:
            lines.append(f"- `{word}` ({entry.get('count', 0)})")
    else:
        lines.append("*(no vocabulary yet)*")
    lines.append("")

    # Proper nouns
    nouns = data.get("proper_nouns", {})
    lines.append("## Proper Nouns")
    if nouns:
        for noun in sorted(nouns.keys()):
            lines.append(f"- {noun}")
    else:
        lines.append("*(none yet)*")
    lines.append("")

    # History
    history = data.get("history", [])
    lines.append("## History")
    lines.append("<!-- Last 50 sessions: raw → normalized → edited (after user feedback). -->")
    if history:
        lines.append("| Time | Raw | Normalized | Edited |")
        lines.append("|------|-----|------------|--------|")
        for entry in history[-50:]:  # last 50
            ts = entry.get("ts", "")
            raw = entry.get("raw", "").replace("|", "\\|")
            norm = entry.get("normalized", "").replace("|", "\\|")
            edited = entry.get("edited", "").replace("|", "\\|")
            lines.append(f"| {ts} | {raw} | {norm} | {edited} |")
    else:
        lines.append("*(no history yet)*")
    lines.append("")

    # Compiled prompt
    compiled = data.get("compiled_prompt", "")
    lines.append("## Compiled Prompt")
    lines.append("<!-- Auto-generated by prompt optimizer. Do not edit manually. -->")
    if compiled:
        lines.append(compiled)
    else:
        lines.append("*(not yet compiled — will be generated after enough sessions)*")
    lines.append("")

    return "\n".join(lines)


# ── Rule Compiler ────────────────────────────────────────────────────────


def _compile_rules(data: dict) -> list[str]:
    """Auto-generate rules from correction patterns.

    Detects:
      - English→translated pairs → "Keep English terms as-is"
      - Phonetic error patterns → specific phonetic rules
      - Feedback corrections → explicit user preferences
    """
    corrections = data.get("corrections", {})
    existing_rules = set(data.get("rules", []))
    new_rules: list[str] = list(existing_rules)

    # Pattern 1: English words being translated
    en_translated = 0
    en_kept = 0
    for key, entry in corrections.items():
        parts = key.split("|", 1)
        if len(parts) != 2:
            continue
        wrong, right = parts
        # Check if correction reverses a translation (right side is English)
        if re.match(r"^[a-zA-Z\s]+$", right.strip()) and entry.get("source") == "feedback":
            en_kept += 1
        elif re.match(r"^[a-zA-Z\s]+$", wrong.strip()):
            en_translated += 1

    rule_keep_en = "NEVER translate English words to Russian/Ukrainian — keep them as-is"
    if en_kept >= 1 and rule_keep_en not in existing_rules:
        new_rules.append(rule_keep_en)

    # Pattern 2: Phonetic corrections (Cyrillic → Cyrillic)
    phonetic_count = 0
    for key, entry in corrections.items():
        parts = key.split("|", 1)
        if len(parts) != 2:
            continue
        wrong, right = parts
        if (any("\u0400" <= c <= "\u04ff" for c in wrong)
                and any("\u0400" <= c <= "\u04ff" for c in right)
                and entry.get("count", 0) >= 2):
            phonetic_count += 1

    rule_phonetic = "Fix phonetic Whisper errors (е↔а, и↔ы, в↔б, пре↔при↔вы)"
    if phonetic_count >= 2 and rule_phonetic not in existing_rules:
        new_rules.append(rule_phonetic)

    return new_rules


# ── Main class ───────────────────────────────────────────────────────────


class UserProfile:
    """Learns and stores user-specific speech patterns in MD format."""

    def __init__(self, enabled: bool = True, min_correction_count: int = MIN_CORRECTION_COUNT,
                 max_prompt_tokens: int = 300, decay_days: int = DECAY_DAYS):
        self._enabled = enabled
        self._min_correction_count = min_correction_count
        self._max_prompt_tokens = max_prompt_tokens
        self._decay_days = decay_days

        self._data: dict = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._last_save_time = 0.0
        self._needs_recompile = False
        self._optimize_sessions_interval = 5  # recompile every N sessions

    @property
    def profile_path(self) -> Path:
        """Return path to the profile file for display in settings."""
        return PROFILE_PATH

    @property
    def needs_recompile(self) -> bool:
        """True if compiled prompt needs refresh (feedback added or N sessions passed)."""
        if self._needs_recompile:
            return True
        sessions = self._data.get("meta", {}).get("sessions", 0)
        return sessions > 0 and sessions % self._optimize_sessions_interval == 0

    # ── Load / Save ──────────────────────────────────────────────────

    def load(self) -> None:
        """Load profile from MD file. Migrate from JSON if needed."""
        if PROFILE_PATH.exists():
            try:
                text = PROFILE_PATH.read_text(encoding="utf-8")
                self._data = _parse_profile_md(text)
                meta = self._data.get("meta", {})
                logger.info(
                    "User profile loaded: %d corrections, %d vocab, %d nouns, %d sessions",
                    len(self._data.get("corrections", {})),
                    len(self._data.get("vocabulary", {})),
                    len(self._data.get("proper_nouns", {})),
                    meta.get("sessions", 0),
                )
                return
            except Exception as e:
                logger.warning("Cannot parse profile MD (%s), starting fresh", e)

        # Migrate from JSON if exists
        if PROFILE_JSON_PATH.exists():
            try:
                self._migrate_from_json()
                logger.info("Migrated profile from JSON to MD")
                self.save(force=True)
                return
            except Exception as e:
                logger.warning("Cannot migrate JSON profile: %s", e)

        self._data = self._empty_profile()
        logger.info("User profile: starting fresh")

    def _migrate_from_json(self) -> None:
        """Migrate legacy JSON profile to new MD structure."""
        import json
        with open(PROFILE_JSON_PATH, "r", encoding="utf-8") as f:
            old = json.load(f)

        self._data = self._empty_profile()

        # Stats
        stats = old.get("stats", {})
        self._data["meta"]["sessions"] = stats.get("total_sessions", 0)
        mix = stats.get("language_mix", {})
        self._data["meta"]["cyrillic"] = mix.get("cyrillic", 0.5)
        self._data["meta"]["latin"] = mix.get("latin", 0.5)

        # Corrections — clean up garbage during migration
        for key, entry in old.get("corrections", {}).items():
            parts = key.split("|", 1)
            if len(parts) != 2:
                continue
            wrong, right = parts[0].strip(".,!?;:\"'() "), parts[1].strip(".,!?;:\"'() ")
            if not wrong or not right or wrong == right.lower():
                continue
            # Skip multi-word pairs (likely reformulations)
            if len(wrong.split()) > 2 or len(right.split()) > 2:
                continue
            clean_key = f"{wrong.lower()}|{right}"
            self._data["corrections"][clean_key] = {
                "count": entry.get("count", 1),
                "source": entry.get("source", "auto"),
                "last_seen": entry.get("last_seen", _today()),
            }

        # Vocabulary
        for word, entry in old.get("vocabulary", {}).items():
            self._data["vocabulary"][word] = {
                "count": entry.get("count", 1),
                "last_seen": entry.get("last_seen", _today()),
            }

        # Proper nouns
        for noun, entry in old.get("proper_nouns", {}).items():
            self._data["proper_nouns"][noun] = {
                "count": entry.get("count", 1),
                "last_seen": entry.get("last_seen", _today()),
            }

        # Compile rules from migrated data
        self._data["rules"] = _compile_rules(self._data)

    def save(self, force: bool = False) -> None:
        """Save profile to MD file (debounced unless force=True)."""
        if not self._dirty and not force:
            return
        now = time.monotonic()
        if not force and (now - self._last_save_time) < SAVE_DEBOUNCE_S:
            return

        with self._lock:
            try:
                md_text = _render_profile_md(self._data)
                tmp = PROFILE_PATH.with_suffix(".tmp")
                tmp.write_text(md_text, encoding="utf-8")
                os.replace(tmp, PROFILE_PATH)
                self._dirty = False
                self._last_save_time = now
                logger.debug("User profile saved to %s", PROFILE_PATH)
            except Exception as e:
                logger.error("Failed to save profile: %s", e)

    # ── Recording ────────────────────────────────────────────────────

    def record_session(self, raw_text: str, normalized_text: str,
                       from_feedback: bool = False) -> None:
        """Learn from a completed dictation session or user feedback."""
        if not self._enabled or not raw_text.strip() or not normalized_text.strip():
            return

        with self._lock:
            today = _today()
            meta = self._data.setdefault("meta", {})

            if not from_feedback:
                meta["sessions"] = meta.get("sessions", 0) + 1

                # Language mix (rolling average)
                cyrillic = sum(1 for c in raw_text if "\u0400" <= c <= "\u04ff")
                latin = sum(1 for c in raw_text if c.isascii() and c.isalpha())
                total = cyrillic + latin
                if total > 0:
                    n = meta["sessions"]
                    meta["cyrillic"] = round(
                        meta.get("cyrillic", 0.5) * (n - 1) / n + (cyrillic / total) / n, 3
                    )
                    meta["latin"] = round(
                        meta.get("latin", 0.5) * (n - 1) / n + (latin / total) / n, 3
                    )

            # Corrections
            corrections = self._data.setdefault("corrections", {})
            for raw_w, norm_w in _extract_corrections(raw_text, normalized_text):
                key = f"{raw_w}|{norm_w}"

                # Conflict resolution: feedback overrides auto-corrections
                if from_feedback:
                    reverse_key_lower = f"{norm_w.lower()}|{raw_w.lower()}"
                    to_remove = [
                        k for k in corrections
                        if k.lower() == reverse_key_lower
                    ]
                    for k in to_remove:
                        logger.info("Feedback overrides: removed '%s'", k)
                        del corrections[k]

                entry = corrections.setdefault(key, {"count": 0, "source": "auto"})
                entry["count"] += 3 if from_feedback else 1
                entry["last_seen"] = today
                if from_feedback:
                    entry["source"] = "feedback"
                    logger.info("Feedback: '%s' → '%s' (count=%d)", raw_w, norm_w, entry["count"])

                    # Also boost corrected terms in vocabulary (user-confirmed terms)
                    vocab_fb = self._data.setdefault("vocabulary", {})
                    for term in _extract_vocabulary(norm_w):
                        v_entry = vocab_fb.setdefault(term, {"count": 0})
                        v_entry["count"] = max(v_entry.get("count", 0), 10)  # high priority
                        v_entry["last_seen"] = today
                        v_entry["source"] = "feedback"
                        logger.info("Term learned from feedback: '%s'", term)

            # Vocabulary
            vocab = self._data.setdefault("vocabulary", {})
            for word in _extract_vocabulary(normalized_text):
                entry = vocab.setdefault(word, {"count": 0})
                entry["count"] += 1
                entry["last_seen"] = today

            # Proper nouns
            nouns = self._data.setdefault("proper_nouns", {})
            for noun in _extract_proper_nouns(normalized_text):
                entry = nouns.setdefault(noun, {"count": 0})
                entry["count"] += 1
                entry["last_seen"] = today

            # Re-compile rules after new data
            self._data["rules"] = _compile_rules(self._data)

            # Mark that compiled prompt needs refresh
            if from_feedback:
                self._needs_recompile = True

            self._dirty = True

        self._compact_if_needed()
        self.save()

    # ── History ───────────────────────────────────────────────────────

    def add_history(self, raw: str, normalized: str) -> None:
        """Add a session record: raw transcription + normalized result."""
        if not self._enabled:
            return
        with self._lock:
            history = self._data.setdefault("history", [])
            history.append({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "raw": raw.strip(),
                "normalized": normalized.strip(),
                "edited": "",
            })
            # Keep last 50
            if len(history) > 50:
                self._data["history"] = history[-50:]
            self._dirty = True
        self.save()

    def update_history_edited(self, edited: str) -> None:
        """Update the last history entry with user's edited text."""
        if not self._enabled:
            return
        with self._lock:
            history = self._data.get("history", [])
            if history:
                history[-1]["edited"] = edited.strip()
                self._dirty = True
        self.save()

    # ── Prompt Generation ────────────────────────────────────────────

    def get_prompt_context(self) -> str:
        """Build prompt context from profile facts. Max ~500 chars for fast LLM processing."""
        if not self._enabled:
            return ""
        return self._build_facts_summary()

    def compile_prompt(self) -> None:
        """Recompile prompt from facts (no LLM needed). Called after each profile update."""
        # Just rebuild from facts — deterministic, instant, no API calls
        self._needs_recompile = False
        self.save()

    def _build_facts_summary(self, max_chars: int = 500) -> str:
        """Build compact prompt from profile facts, fitting within max_chars budget."""
        budget = max_chars
        parts = []

        with self._lock:
            # 1. User preferences (highest priority — from feedback)
            corrections = self._data.get("corrections", {})
            user_prefs = []
            auto_fixes = []
            for key, entry in corrections.items():
                count = entry.get("count", 0)
                source = entry.get("source", "auto")
                kv = key.split("|", 1)
                if len(kv) != 2:
                    continue
                if source == "feedback":
                    user_prefs.append(f'"{kv[0]}"→"{kv[1]}"')
                elif count >= self._min_correction_count:
                    auto_fixes.append(f'"{kv[0]}"→"{kv[1]}"')

            # Add user prefs first (highest priority), fitting within budget
            if user_prefs:
                section = "USER FIXES: "
                items = []
                for p in user_prefs:
                    candidate = section + ", ".join(items + [p])
                    if len(candidate) > budget:
                        break
                    items.append(p)
                if items:
                    line = section + ", ".join(items)
                    parts.append(line)
                    budget -= len(line) + 1

            # Add whisper fixes within remaining budget
            if auto_fixes and budget > 30:
                section = "WHISPER FIXES: "
                items = []
                for p in auto_fixes:
                    candidate = section + ", ".join(items + [p])
                    if len(candidate) > budget:
                        break
                    items.append(p)
                if items:
                    line = section + ", ".join(items)
                    parts.append(line)
                    budget -= len(line) + 1

            # 2. Rules within remaining budget
            rules = self._data.get("rules", [])
            if rules and budget > 20:
                section = "RULES: "
                items = []
                for r in rules:
                    candidate = section + "; ".join(items + [r])
                    if len(candidate) > budget:
                        break
                    items.append(r)
                if items:
                    line = section + "; ".join(items)
                    parts.append(line)
                    budget -= len(line) + 1

            # 3. User-confirmed domain terms (from feedback) — highest term priority
            if budget > 20:
                vocab = self._data.get("vocabulary", {})
                nouns = self._data.get("proper_nouns", {})

                # Split: feedback terms vs auto-detected
                feedback_terms = []
                auto_terms = []
                for w, e in vocab.items():
                    if e.get("source") == "feedback":
                        feedback_terms.append((w, e.get("count", 0)))
                    else:
                        auto_terms.append((w, e.get("count", 0)))
                auto_terms += [(n, e.get("count", 0)) for n, e in nouns.items()]

                feedback_terms.sort(key=lambda x: x[1], reverse=True)
                auto_terms.sort(key=lambda x: x[1], reverse=True)

                seen: set[str] = set()

                # Feedback terms first — these are user-confirmed, must be preserved
                if feedback_terms:
                    section = "DOMAIN TERMS (always use exactly): "
                    items = []
                    for term, _ in feedback_terms:
                        if term.lower() in seen:
                            continue
                        seen.add(term.lower())
                        candidate = section + ", ".join(items + [term])
                        if len(candidate) > budget:
                            break
                        items.append(term)
                    if items:
                        line = section + ", ".join(items)
                        parts.append(line)
                        budget -= len(line) + 1

                # Auto terms in remaining budget
                if auto_terms and budget > 20:
                    section = "TERMS: "
                    items = []
                    for term, _ in auto_terms:
                        if term.lower() in seen:
                            continue
                        seen.add(term.lower())
                        candidate = section + ", ".join(items + [term])
                        if len(candidate) > budget:
                            break
                        items.append(term)
                    if items:
                        parts.append(section + ", ".join(items))

        return "\n".join(parts)

    # ── Prompt Optimizer (Tournament) ────────────────────────────────

    def _build_triads_summary(self) -> str:
        """Build summary from history triads: raw → normalized → edited."""
        with self._lock:
            history = self._data.get("history", [])

        if not history:
            return ""

        lines = []
        # Only include sessions where user made edits (edited != "" and edited != normalized)
        edited_sessions = [
            h for h in history
            if h.get("edited") and h["edited"].strip() != h.get("normalized", "").strip()
        ]
        # Also include last few unedited sessions for context
        recent = history[-10:]

        if edited_sessions:
            lines.append("SESSIONS WHERE USER CORRECTED THE OUTPUT (most important):")
            for h in edited_sessions[-15:]:
                lines.append(f"  Whisper heard: {h['raw']}")
                lines.append(f"  LLM produced:  {h['normalized']}")
                lines.append(f"  User wanted:   {h['edited']}")
                lines.append("")

        if recent:
            lines.append("RECENT SESSIONS (for context):")
            for h in recent:
                edited_mark = ""
                if h.get("edited") and h["edited"].strip() != h.get("normalized", "").strip():
                    edited_mark = f" → user corrected to: {h['edited']}"
                lines.append(f"  {h['raw']} → {h['normalized']}{edited_mark}")

        return "\n".join(lines)

    def optimize_prompt(self, http_client) -> None:
        """Run prompt tournament: 3 candidates → judge picks best.

        Uses triads (raw → normalized → edited) as primary input,
        plus facts summary for rules and vocabulary.

        Args:
            http_client: httpx.Client configured for Groq API.
        """
        facts = self._build_facts_summary()
        triads = self._build_triads_summary()

        if not facts.strip() and not triads.strip():
            logger.info("Prompt optimizer: no data yet, skipping")
            return

        logger.info("Prompt optimizer: starting tournament...")

        # Combine triads + facts
        input_data = ""
        if triads:
            input_data += f"SESSION HISTORY (raw → normalized → user-corrected):\n\n{triads}\n\n"
        if facts:
            input_data += f"EXTRACTED RULES AND PATTERNS:\n\n{facts}\n\n"

        strategies = [
            # Strategy A: concise rules
            (
                "You are an expert at writing system prompts for LLMs. "
                "Analyze the session history showing what Whisper heard, what the LLM produced, "
                "and what the user actually wanted. Identify PATTERNS in the user's corrections. "
                "Write a CONCISE system prompt (max 200 words) that prevents these errors. "
                "Focus on clear, actionable rules."
            ),
            # Strategy B: example-driven
            (
                "You are an expert at writing system prompts for LLMs. "
                "Analyze the session history (raw → normalized → user-corrected). "
                "Write a system prompt with SPECIFIC before→after examples from the history. "
                "Show the LLM exactly what kind of corrections to make and what NOT to do. "
                "Max 250 words."
            ),
            # Strategy C: structured with priorities
            (
                "You are an expert at writing system prompts for LLMs. "
                "Analyze the session history and user corrections. "
                "Write a STRUCTURED system prompt organized by priority: "
                "1) explicit user preferences (from corrections), "
                "2) language handling rules, "
                "3) phonetic error patterns, "
                "4) vocabulary and domain terms. Max 250 words."
            ),
        ]

        user_msg = (
            f"{input_data}"
            "Based on the above data, write a system prompt for a speech-to-text error corrector LLM.\n"
            "The corrector receives raw Whisper transcription and must output corrected text.\n\n"
            "The prompt MUST:\n"
            "- Learn from the user's corrections: if the user changed LLM output, the prompt must prevent that mistake\n"
            "- Include ALL user preferences (non-negotiable)\n"
            "- End with 'Output ONLY the corrected text.'\n"
            "- NOT contradict itself\n\n"
            "Output ONLY the system prompt text, nothing else."
        )

        candidates: list[str] = []
        for i, strategy in enumerate(strategies):
            try:
                resp = http_client.post(
                    "/chat/completions",
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": strategy},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.7 + i * 0.1,  # 0.7, 0.8, 0.9
                        "max_tokens": 500,
                    },
                )
                resp.raise_for_status()
                result = resp.json()["choices"][0]["message"]["content"].strip()
                if result:
                    candidates.append(result)
                    logger.info("Candidate %d: %d chars", i + 1, len(result))
            except Exception as e:
                logger.warning("Candidate %d failed: %s", i + 1, e)

        if len(candidates) < 2:
            logger.warning("Prompt optimizer: not enough candidates (%d)", len(candidates))
            if candidates:
                # Use the one we got
                with self._lock:
                    self._data["compiled_prompt"] = candidates[0]
                    self._dirty = True
                self.save(force=True)
                logger.info("Prompt optimizer: used single candidate (%d chars)", len(candidates[0]))
            return

        # Judge: pick the best
        judge_prompt = (
            "You are evaluating 3 candidate system prompts for a speech-to-text error corrector.\n\n"
            f"USER FACTS (ground truth):\n{facts}\n\n"
        )
        for i, c in enumerate(candidates):
            judge_prompt += f"--- CANDIDATE {i+1} ---\n{c}\n\n"

        judge_prompt += (
            "Evaluate each candidate on:\n"
            "1. Coverage: does it include ALL user preferences and known errors?\n"
            "2. Clarity: is it clear and actionable for the LLM?\n"
            "3. Consistency: does it NOT contradict itself?\n"
            "4. Conciseness: is it compact without losing information?\n\n"
            "Reply with ONLY the number of the best candidate (1, 2, or 3)."
        )

        try:
            resp = http_client.post(
                "/chat/completions",
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "You are a fair judge. Pick the best option."},
                        {"role": "user", "content": judge_prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 10,
                },
            )
            resp.raise_for_status()
            verdict = resp.json()["choices"][0]["message"]["content"].strip()
            # Extract number
            m = re.search(r"[123]", verdict)
            winner_idx = int(m.group()) - 1 if m else 0
            winner_idx = min(winner_idx, len(candidates) - 1)
        except Exception as e:
            logger.warning("Judge failed (%s), using candidate 1", e)
            winner_idx = 0

        winner = candidates[winner_idx]
        logger.info("Prompt optimizer: winner = candidate %d (%d chars)", winner_idx + 1, len(winner))

        with self._lock:
            self._data["compiled_prompt"] = winner
            self._dirty = True
        self.save(force=True)

    # ── Compaction ───────────────────────────────────────────────────

    def _compact_if_needed(self) -> None:
        """Prune old entries and enforce size limits."""
        with self._lock:
            corrections = self._data.get("corrections", {})
            vocab = self._data.get("vocabulary", {})
            nouns = self._data.get("proper_nouns", {})

            if (len(corrections) <= MAX_CORRECTIONS
                    and len(vocab) <= MAX_VOCABULARY
                    and len(nouns) <= MAX_PROPER_NOUNS):
                return

            cutoff = (datetime.now() - timedelta(days=self._decay_days)).strftime("%Y-%m-%d")

            for store in (corrections, vocab, nouns):
                expired = [k for k, v in store.items() if v.get("last_seen", "") < cutoff]
                for k in expired:
                    del store[k]

            self._data["corrections"] = self._trim(corrections, MAX_CORRECTIONS)
            self._data["vocabulary"] = self._trim(vocab, MAX_VOCABULARY)
            self._data["proper_nouns"] = self._trim(nouns, MAX_PROPER_NOUNS)

            logger.info(
                "Profile compacted: %d corrections, %d vocab, %d nouns",
                len(self._data["corrections"]),
                len(self._data["vocabulary"]),
                len(self._data["proper_nouns"]),
            )

    @staticmethod
    def _trim(store: dict, limit: int) -> dict:
        if len(store) <= limit:
            return store
        sorted_items = sorted(store.items(), key=lambda x: x[1].get("count", 0), reverse=True)
        return dict(sorted_items[:limit])

    @staticmethod
    def _empty_profile() -> dict:
        return {
            "meta": {
                "sessions": 0,
                "cyrillic": 0.5,
                "latin": 0.5,
            },
            "rules": [],
            "corrections": {},
            "vocabulary": {},
            "proper_nouns": {},
            "compiled_prompt": "",
            "history": [],
        }

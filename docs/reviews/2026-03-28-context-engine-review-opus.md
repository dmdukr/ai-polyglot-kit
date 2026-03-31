# Context Engine Architecture Review

**Spec reviewed:** `docs/superpowers/specs/2026-03-28-context-engine-architecture.md`
**Reviewer:** Claude Opus 4.6 (systems architect role)
**Date:** 2026-03-28
**Verdict:** Strong foundation with several correctness issues and missing edge cases that need addressing before implementation.

---

## Strengths (what's well designed)

### 1. The four-level resolution cascade is elegant and well-motivated

The progression from self-context (0 tokens) through thread context, fingerprints, and finally LLM fallback is a textbook example of a cost-aware decision hierarchy. Each level has clearly defined entry/exit criteria and a concrete example. The token budget analysis in Section 9.2 (~160-245 tokens per request) is realistic and demonstrates genuine cost awareness.

### 2. Content-based thread identification solves a real problem

Section 5.3's "Two Sasha Problem" is the strongest part of the spec. Defining threads by content cluster rather than window title is a genuinely novel design decision for a dictation tool. The weighted cross-app scoring (Section 5.4, `find_active_thread`) with same-app=2x, cross-app=1x multipliers is a pragmatic middle ground that avoids both false positives and false negatives.

### 3. The co-occurrence graph with temporal decay is well-conceived

Section 6.4's decay formula `weight * (1.0 / (julianday('now') - julianday(last_used) + 1))` ensures the system naturally forgets stale associations. The visualization in Section 6.5 (cross-cluster term "zamok" with decayed IT weight vs fresh household weight) makes the benefit immediately tangible.

### 4. No external dependencies is the right call

Section 2, Goal 6: "No external dependencies (no vector DB, no ONNX embeddings, no graph DB -- pure SQLite)" is a strong constraint for a desktop app distributed via PyInstaller. Every extra dependency is a potential packaging/compatibility nightmare on Windows.

### 5. The learning loop from corrections (Section 10) is well-integrated

The triad storage (raw/normalized/corrected), automatic error source classification (STT vs LLM), co-occurrence graph update, and auto-promotion to exact dictionary after 3 repeated corrections form a complete feedback loop. This is rare in specs -- most hand-wave the learning part.

### 6. Profile export/import handles the DPAPI portability problem correctly

Section 13.3 acknowledges the Windows SID-bound DPAPI limitation and provides a concrete DPAPI-to-AES-to-DPAPI re-encryption flow with PBKDF2 at 600K iterations. This is a detail most specs would omit entirely.

---

## Weaknesses (specific problems with examples)

### W1. No lemmatization -- keyword extraction will miss morphological variants (Section 11)

The keyword extractor (Section 11.1) uses raw lowercased words with a minimum length of 3 characters:

```python
words = [w for w in re.findall(r'\b\w{3,}\b', text.lower())
         if w not in STOP_WORDS]
```

Ukrainian is a highly inflected language. The same concept produces different surface forms:

| Concept | Forms in natural speech |
|---------|------------------------|
| deploy | деплой, деплою, деплоїв, деплоїти, деплоєм |
| lock | замок, замку, замком, замки, замків |
| door | двері, дверей, дверях, дверима, дверям |

Without lemmatization, "замок" and "замку" are treated as different keywords. This means:
- Co-occurrence edges are split across surface forms, weakening the graph
- Thread matching fails when the same concept appears in different cases
- Fingerprint matching misses conversations where the same word was used in a different grammatical form

**Impact:** This could halve the effective accuracy of Levels 1-3, forcing far more LLM fallbacks than the 5-10% projected in Section 4 (Level 4).

**Available tools:** [pymorphy3](https://github.com/no-plagiarism/pymorphy3) provides Ukrainian lemmatization and is pure Python (no binary dependencies). [tree_stem](https://github.com/amakukha/stemmers_ukrainian) is a fast ML-based Ukrainian stemmer that outperforms lemmatizers by ERRT at 24x the speed. Even simple stemming (chopping last 2-3 characters of Ukrainian words) would help.

### W2. Cluster identity is fragile -- string-based, no stable IDs (Sections 6, 12)

Clusters are stored as free-form TEXT strings in `term_cooccurrence.cluster`. The naming function (Section 12.2) generates names from top terms:

```python
return " / ".join(t.term_a for t in top_terms)
# e.g., "git / deploy / PR"
```

But this name changes as the graph evolves. If "deploy" drops out of the top 3 due to temporal decay, the cluster name changes from "git / deploy / PR" to "git / PR / branch". Now:

- All existing co-occurrence rows with `cluster = "git / deploy / PR"` are orphaned
- All fingerprints referencing the old name are broken
- Thread cluster assignments become stale

The spec conflates display name with identity. Clusters need stable, auto-generated IDs (e.g., `cluster_001`) with a separate display name. Section 12.2 says "Used only for UI display" but the same string is used as the primary key in `term_cooccurrence` and `conversation_fingerprints`.

### W3. Co-occurrence graph stores both directions, doubling storage (Section 6.3)

The `update_cooccurrence` function (Section 6.3) explicitly inserts both `(term_a, term_b, cluster)` and `(term_b, term_a, cluster)` with the comment "Also insert reverse direction." This doubles the number of rows, the INSERT time, and the pruning work.

The lookup query in Section 6.4 searches `WHERE term_a = ? AND term_b IN (?, ?, ?)` -- it only checks one direction. If you always store pairs in canonical order (e.g., `term_a < term_b` lexicographically), you cut storage in half and queries still work with a simple `WHERE (term_a = ? AND term_b IN (...)) OR (term_b = ? AND term_a IN (...))`. The OR can be avoided entirely with a UNION on the same index.

At 100K+ edges (3-year projection, Section 13.1), this means 200K rows instead of 100K, with cascading effects on VACUUM time, backup size, and maintenance queries.

### W4. `cold_start_cluster` (Section 7.4) has an app-filter bias that contradicts the cross-app philosophy

The fingerprint search (Section 7.4) first searches with `AND cf.app = ?`, then falls back to searching without the app filter:

```python
results = db.query(f"""
    SELECT cf.cluster, COUNT(DISTINCT cf.id) as hits ...
    WHERE fk.keyword IN ({placeholders})
      AND cf.app = ?
    ...
""", [*kws, app])

if not results:
    # Fallback: search without app filter
    ...
```

This is a hard binary -- either exact app match or no app consideration at all. But Section 5.4 demonstrates that app should be a weighted signal, not a filter. A user starting a coding discussion in Telegram should still benefit from VS Code fingerprints, just with reduced weight. The function should mirror the `find_active_thread` pattern: app match = 2x weight, non-match = 1x.

### W5. Confidence formula for Level 3 is statistically unsound (Section 4)

The fingerprint confidence formula is:

```
confidence = hits / total_fingerprints
```

Where `total = sum(r.hits for r in results)`. This is the proportion of matching fingerprints in the top cluster versus all matching fingerprints. Consider:

- 2 fingerprints match HOUSEHOLD cluster, 1 matches IT cluster
- Confidence = 2/3 = 0.67 (passes the 0.6 threshold)

But 3 total fingerprints is an extremely small sample. The system would confidently resolve "zamok" = "door lock" based on 2 prior conversations. This invites brittle early decisions. The formula should incorporate the absolute hit count, not just the ratio. For example: `confidence = (hits / total) * min(total / 5.0, 1.0)` -- require at least 5 matching fingerprints for full confidence.

### W6. The `learn_from_correction` function uses LIKE for auto-promotion (Section 10.2)

```python
similar = db.query("""
    SELECT COUNT(*) FROM corrections
    WHERE raw_text LIKE ? AND corrected_text LIKE ?
""", [f"%{old_token}%", f"%{new_token}%"])
```

This is problematic:
1. **SQL injection via pattern characters:** If `old_token` contains `%` or `_`, the LIKE pattern becomes unpredictable. The function `compute_token_diffs` could produce tokens containing these characters (e.g., C++ code, regex).
2. **False positives:** `LIKE '%lock%'` matches "clock", "blockchain", "locksmith" -- the 3-occurrence threshold could trigger on unrelated corrections.
3. **Performance:** LIKE with leading `%` cannot use the index on `corrections(raw_text, corrected_text)` -- it forces a full table scan. At 36K corrections/year (Section 13.1), this becomes noticeable.

The spec should use exact token matching via a normalized corrections_tokens join table or at minimum use `instr()` with boundary checks.

### W7. Thread expiry is checked "periodically" but never specified (Section 5.2)

```
THREAD EXPIRY (checked periodically):
    last_message > 15 minutes ago → mark is_active = 0
```

How periodically? If checked every 60 seconds, there is a 60-second window where a new dictation could match a thread that should already be expired. If checked on every dictation, it adds latency to every operation. If checked on app startup, threads from previous sessions are never expired until restart.

The spec needs to define the check frequency and whether expiry is lazy (checked when queried) or active (background timer). Lazy expiry is simpler and likely sufficient -- just add `AND ct.last_message > datetime('now', '-15 minutes')` to every query (which Section 5.4 already does in `find_active_thread` but not consistently elsewhere).

### W8. VACUUM blocks all writes for the entire database (Section 13.2)

Section 13.2 runs `VACUUM` weekly:

```python
if days_since_last_vacuum() >= 7:
    db.execute("VACUUM")
```

SQLite VACUUM creates a complete copy of the database and requires an exclusive lock for the entire duration. At ~40 MB (pruned steady state), this takes 100-500ms depending on disk speed. During this time, no dictation can be processed -- the pipeline is blocked.

For a real-time dictation app, even 100ms of blocked writes during an active dictation session is unacceptable. Alternatives:
- Use `PRAGMA auto_vacuum = INCREMENTAL` and `PRAGMA incremental_vacuum(N)` to reclaim N pages at a time during idle periods
- Only VACUUM when the app starts and no dictation is in progress
- Use WAL mode (which the spec never mentions but should) and checkpoint during idle time

---

## Missing Edge Cases (scenarios not covered)

### E1. Language switching mid-dictation

The spec handles Ukrainian and English as if they are separate. But the target user mixes them constantly: "зроби pull request в main branch." The keyword extractor treats "pull" and "request" as separate English words, but "pull request" is a single concept. The bigram extraction (Section 11.1) catches this, but the stop word list only has English and Ukrainian words -- no handling of transliteration patterns or code-switched phrases like "задеплоїти на прод" (Ukrainian verb prefix + English loanword + Ukrainian preposition + English loanword).

### E2. Rapid app switching

User dictates to Slack, then immediately (within 5 seconds) switches to VS Code. The first dictation creates Thread #X in Slack. The second dictation goes to VS Code, but it is about the exact same topic. The spec's cross-app matching (Section 5.4) would work here IF the keywords overlap sufficiently. But if the VS Code dictation is just "// fix the thing Sasha mentioned" with no technical keywords, it gets a new thread with cluster=unknown, losing all context from the Slack conversation.

### E3. Multiple simultaneous active threads per app

The spec implicitly assumes one active thread per app (the `LIMIT 1` in `assign_to_thread` for keyword-less messages). But a user could be alternating between two Telegram chats rapidly (< 15 min gap). Both threads remain active. A keyword-less message "ok" is assigned to the most recent active thread in that app -- which may be the wrong conversation. The spec acknowledges this limitation for keyword-less messages but does not discuss it as a design risk.

### E4. Offensive/sensitive content in unencrypted fields

Section 17, question 4 mentions that "Thread summaries and keywords are stored unencrypted." But consider: a user dictates a medical conversation. Keywords like specific diagnoses, medication names, or personal health information are stored in plaintext in `thread_keywords`, `term_cooccurrence`, and `fingerprint_keywords`. If the machine is compromised or shared, this is a privacy leak.

The spec's "paranoid mode" suggestion is all-or-nothing. A better approach: encrypt sensitive clusters (user-tagged) while leaving general clusters unencrypted.

### E5. Dictionary conflicts between exact and context terms

Section 8 defines exact terms (always applied) and context terms (disambiguation needed). But what if "zamok" is added as an exact term (zamok -> lock) AND exists as a context term in the co-occurrence graph? The spec says exact terms are applied in Stage 6 (post-LLM), so the LLM might output "door lock" and then Stage 6 replaces "lock" again? The interaction between Stage 4 (context resolution) and Stage 6 (exact replacement) is not fully specified for overlapping terms.

### E6. Clock skew and timezone handling

All temporal calculations use SQLite's `datetime('now', '-15 minutes')`. If the system clock changes (NTP sync, manual adjustment, daylight saving), active threads could be spuriously expired or kept alive. The 15-minute window is relative to `CURRENT_TIMESTAMP` at INSERT time vs `datetime('now')` at query time -- both should be in UTC. The spec never mentions timezone handling.

### E7. Database corruption recovery

The spec has no mention of what happens if the SQLite database is corrupted (power loss during VACUUM, disk error). For a single-file database that accumulates months of learning data, this is a significant risk. At minimum: WAL mode, regular `.backup` to a second file, and integrity checks on startup.

### E8. Cold start is really cold

Section 12.5 projects that the first 50 dictations have "all unknown" clusters and "LLM handles everything." At 100 dictations/day, that is 12 hours of degraded service. But many users might not reach 100/day -- a casual user doing 20 dictations/day faces 2.5 days of zero context intelligence. The spec should consider seeding from a default co-occurrence graph (e.g., common IT terms, common household terms) that the user can opt into.

---

## Architecture Concerns (scalability, reliability)

### A1. Single-threaded SQLite under real-time dictation pressure

The spec targets <5ms for context resolution, but all database operations (context lookup, co-occurrence update, thread update, history INSERT) happen on the same SQLite connection. During a batch co-occurrence INSERT (~2ms per Section 11.2), a concurrent context lookup would be blocked. The spec should specify whether the database uses WAL mode (concurrent reads during writes) or whether a separate reader connection is used.

SQLite in WAL mode supports one writer and multiple readers simultaneously -- this is a critical configuration that the spec never mentions. Without WAL, the system cannot reliably achieve <5ms context resolution while simultaneously updating the co-occurrence graph.

### A2. Bigram explosion in co-occurrence pairs

Section 11.2 shows that 8 keywords produce 15 terms (with bigrams) and 105 co-occurrence pairs. But this is for unigrams+bigrams combined. The co-occurrence of bigrams with other bigrams is questionable -- does `("pull request", "main branch", "IT")` with weight 50 really mean more than `("pull", "main", "IT")` with weight 200? Bigram-to-bigram co-occurrence pollutes the graph with sparse, high-specificity edges that rarely match.

Consider: only store co-occurrences between unigrams, and use bigrams only for keyword matching in thread assignment and fingerprints. This would reduce the co-occurrence pair count from `T*(T-1)/2` to `U*(U-1)/2` where U is the unigram count (roughly half of T).

### A3. The 0.6 confidence threshold is a single global constant

Section 4 defines `confidence >= 0.6` as the accept threshold for all four levels. But the cost of a false positive varies dramatically by level:

- Level 1 (self-context): false positive = wrong term, applied locally with no LLM check. **High cost.**
- Level 2 (thread): false positive = wrong term, applied locally. **High cost.**
- Level 3 (fingerprint): false positive = wrong cluster suggestion to LLM. **Low cost** (LLM can override).
- Level 4 (LLM): always accepted. **Zero local cost.**

Levels 1 and 2 should have a higher threshold (e.g., 0.8) since their errors are silently applied. Level 3 can afford a lower threshold (e.g., 0.5) since it only influences the LLM prompt.

### A4. No observability or debugging hooks

The spec describes a complex multi-level resolution system but provides no way to observe its decisions. When a term is resolved incorrectly, how does the developer (or user) understand why? There is no mention of:
- Decision logging (which level resolved, with what confidence)
- Debug mode showing co-occurrence weights for a given term
- Statistics dashboard (resolution rate by level, accuracy over time)

Section 10 describes learning from corrections but not understanding why the error happened. Adding a `resolution_log` table (term, level, confidence, chosen_meaning, was_correct) would make the system debuggable and provide data for tuning thresholds.

### A5. Index on `corrections(raw_text, corrected_text)` is useless for LIKE queries

Section 15 defines:
```sql
CREATE INDEX idx_corrections_pattern ON corrections(raw_text, corrected_text);
```

But Section 10.2 queries this table with `WHERE raw_text LIKE '%token%'`. B-tree indexes cannot accelerate LIKE patterns with leading wildcards. This index wastes space and gives false confidence that the query is fast. Either change the query (use exact matching or FTS5) or remove the index.

---

## Research Findings (what I found online that confirms or contradicts the approach)

### R1. The co-occurrence graph approach for WSD is validated by literature

A [2018 study on co-occurrence graphs for word sense disambiguation in the biomedical domain](https://pubmed.ncbi.nlm.nih.gov/29573845/) showed that co-occurrence graph systems outperformed state-of-the-art knowledge-based systems by more than 10% accuracy in some cases, while requiring minimal external resources. This directly validates the spec's approach. The spec's referenced [2024 WSD survey](https://link.springer.com/chapter/10.1007/978-3-031-57624-9_10) also confirms that knowledge graph + context approaches remain competitive with neural methods for domain-specific WSD.

However, these studies used lemmatized text -- reinforcing that the lack of lemmatization in Section 11 is a significant gap.

### R2. Industry DST in 2025-2026 favors hybrid LLM + structured state

A [comprehensive guide to dialogue state tracking for 2025](https://www.shadecoder.com/topics/dialogue-state-tracking-a-comprehensive-guide-for-2025) notes that "Industry trends in 2025 emphasize hybrid designs: combining neural intent/slot extraction with a structured DST layer to maintain reliability and interpretability." The spec's approach -- local structured graph + LLM fallback -- aligns perfectly with this trend.

Recent research on [Noetic State Representation Graphs](https://www.sciencedirect.com/science/article/abs/pii/S0031320325005023) proposes dynamic graph representations that synchronize with multi-turn dialogues, similar to the spec's thread-based approach. The [2025 paper on Joint Speech and Text Training for LLM-Based Spoken Dialogue State Tracking](https://arxiv.org/abs/2511.22503) also validates the approach of jointly considering speech and text modalities.

### R3. Competing products have solved context-aware dictation differently

Several commercial products now offer context-aware voice dictation:

- **[Wispr Flow](https://wisprflow.ai/)**: Adapts formatting to the active app (casual for Slack, formal for email). Cloud-based, processes over 500 language patterns/second, 95%+ accuracy. SOC 2 Type II and HIPAA compliant. Uses proprietary cloud AI -- the opposite architectural choice from this spec's local-first approach.
- **[Monologue](https://moge.ai/product/monologue)**: Context-aware voice dictation adapting to writing style, vocabulary, and multilingual needs across 100+ languages. Focuses on writing style adaptation rather than term disambiguation.
- **[Willow Voice](https://willowvoice.com/)**: "Context-aware AI looks at what you're working on to get technical terms right automatically."

**Key difference:** All these competitors use cloud-based LLMs for context resolution. None appear to use local co-occurrence graphs. This spec's local-first approach is genuinely differentiated -- if it works, it offers a unique privacy advantage. But it also means there is no proven prior art to validate the specific local graph architecture.

### R4. SQLite at 100K edges is fine -- but VACUUM is the bottleneck

[SQLite performance benchmarks](https://phiresky.github.io/blog/2020/sqlite-performance-tuning/) show that with WAL mode and proper indexing, SQLite can handle 100K+ SELECT queries per second even on multi-GB databases. The co-occurrence graph at 100K edges (~5MB of data) is trivially small for SQLite's capabilities.

The real concern is VACUUM. [SQLite documentation](https://sqlite.org/lang_vacuum.html) confirms VACUUM requires an exclusive lock and creates a full database copy. For a ~40MB database, this blocks all writes for 100-500ms. [PowerSync's optimization guide](https://www.powersync.com/blog/sqlite-optimizations-for-ultra-high-performance) recommends `PRAGMA auto_vacuum = INCREMENTAL` as the alternative for real-time applications.

### R5. DPAPI has known security limitations

Research from [Sygnia](https://www.sygnia.co/blog/the-downfall-of-dpapis-top-secret-weapon/) and [SpecterOps](https://specterops.io/blog/2025/07/28/dpapi-backup-key-compromise-pt-1-some-forests-must-burn/) documents significant DPAPI vulnerabilities: master keys stored unencrypted in LSASS, domain backup keys that can decrypt any master key, and the impossibility of re-encrypting existing DPAPI blobs after key compromise. For a local desktop app, DPAPI is still the best available option (it is what Chrome, Edge, and Windows Credential Manager use), but the spec should acknowledge these limitations and not present DPAPI as a strong security boundary. The unencrypted keyword and co-occurrence data (W1 in this section, E4 above) is arguably the bigger privacy risk.

### R6. Ukrainian NLP lacks mature lemmatization -- but options exist

The [awesome-ukrainian-nlp](https://github.com/osyvokon/awesome-ukrainian-nlp) repository and [CLARIN Ukrainian NLP centre](https://www.clarin.eu/blog/introduction-clarin-knowledge-centre-ukrainian-nlp-and-corpora-ukrnlp-corpora) list available tools. [pymorphy3](https://github.com/no-plagiarism/pymorphy3) (pure Python, supports Ukrainian) and the faster [tree_stem](https://github.com/amakukha/stemmers_ukrainian) (ML-based Ukrainian stemmer, 24x faster than lemmatizers) are the most practical options. [spaCy's Ukrainian model](https://spacy.io/models/uk) exists but has a known issue where the [UkrainianLemmatizer falls back to RussianLemmatizer](https://github.com/explosion/spaCy/issues/7124), which may produce incorrect results. For this spec's performance requirements (<1ms), tree_stem is the best fit.

### R7. GDPR considerations for local storage

[GDPR guidance on encryption](https://gdpr-info.eu/issues/encryption/) confirms that locally stored personal data must be protected with "appropriate technical measures." The [ICO guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/security/a-guide-to-data-security/encryption/) notes that the loss of a properly encrypted storage medium is not necessarily a reportable data breach. The spec's approach of encrypting history but leaving keywords unencrypted creates a gap: the keywords themselves (medical terms, personal names, financial terms) are personal data under GDPR. The spec should at minimum document this as a known limitation and offer users the choice to encrypt keyword data at the cost of reduced performance.

---

## Recommendations (concrete actionable improvements)

### R1. Add lightweight lemmatization/stemming to keyword extraction [HIGH PRIORITY]

Add `tree_stem` or `pymorphy3.parse(word)[0].normal_form` to the keyword extraction pipeline. This is the single highest-impact improvement. Even a simple stemming function that handles the most common Ukrainian suffixes (-ів, -ом, -ку, -ки, -ти, -ють) would significantly improve graph density and matching accuracy.

```python
# Minimal change to Section 11.1
from pymorphy3 import MorphAnalyzer
morph = MorphAnalyzer(lang='uk')

def normalize_keyword(word: str) -> str:
    parsed = morph.parse(word)
    if parsed and parsed[0].score > 0.3:
        return parsed[0].normal_form
    return word.lower()
```

### R2. Introduce stable cluster IDs [HIGH PRIORITY]

Replace free-form cluster names with auto-incremented integer IDs. Store display names in a separate `clusters` table:

```sql
CREATE TABLE clusters (
    id INTEGER PRIMARY KEY,
    display_name TEXT,        -- auto-generated from top terms
    created_at DATETIME,
    term_count INTEGER
);
```

Update `term_cooccurrence.cluster` to reference `clusters.id`. Regenerate display names periodically without breaking references.

### R3. Canonicalize co-occurrence pair ordering [MEDIUM PRIORITY]

Store pairs with `term_a < term_b` (lexicographic order). Remove the reverse INSERT. Adjust queries to check both directions. This halves storage, halves write amplification, and simplifies pruning.

### R4. Use WAL mode and document concurrency model [HIGH PRIORITY]

Add to the schema initialization:
```sql
PRAGMA journal_mode = WAL;
PRAGMA wal_autocheckpoint = 1000;
```

Document that the Context Engine uses two connections: a read-only connection for context resolution (non-blocking, <5ms) and a read-write connection for updates (co-occurrence, thread, history INSERTs).

### R5. Replace weekly VACUUM with incremental auto-vacuum [MEDIUM PRIORITY]

```sql
PRAGMA auto_vacuum = INCREMENTAL;
```

Then during idle periods (no dictation for 30+ seconds):
```python
db.execute("PRAGMA incremental_vacuum(100)")  # reclaim 100 pages
```

### R6. Add per-level confidence thresholds [MEDIUM PRIORITY]

```python
CONFIDENCE_THRESHOLDS = {
    "self_context": 0.8,    # high bar: silent local application
    "active_thread": 0.75,  # high bar: silent local application
    "fingerprint": 0.5,     # low bar: only influences LLM prompt
}
```

### R7. Add a resolution log for observability [MEDIUM PRIORITY]

```sql
CREATE TABLE resolution_log (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    term TEXT NOT NULL,
    level INTEGER NOT NULL,          -- 1-4
    confidence REAL,
    chosen_meaning TEXT,
    thread_id INTEGER,
    cluster TEXT,
    was_overridden BOOLEAN DEFAULT 0  -- set to 1 if user corrected
);
```

This enables accuracy tracking, threshold tuning, and debugging.

### R8. Fix the LIKE-based correction matching [HIGH PRIORITY]

Replace the LIKE query in Section 10.2 with a normalized token table or exact match:

```python
# Instead of LIKE matching, store correction pairs separately
db.execute("""
    INSERT INTO correction_pairs (old_token, new_token) VALUES (?, ?)
    ON CONFLICT DO UPDATE SET count = count + 1
""", [old_token, new_token])

# Check for auto-promotion
count = db.query("""
    SELECT count FROM correction_pairs WHERE old_token = ? AND new_token = ?
""", [old_token, new_token])
```

### R9. Define thread expiry as lazy evaluation [LOW PRIORITY]

Remove "checked periodically" and instead rely on the `WHERE last_message > datetime('now', '-15 minutes')` clause that already exists in `find_active_thread`. Add a daily cleanup job (already in Section 13.2) to mark stale threads as inactive for UI purposes. Document this decision explicitly.

### R10. Consider optional seed clusters for cold start [LOW PRIORITY]

Offer an optional "Quick Start" during first run:
- "What do you mainly use voice dictation for?" with checkboxes (IT/development, household, medicine, business)
- Pre-load a small seed co-occurrence graph (~500 edges per domain) to bootstrap the system
- User can skip this ("I prefer to start fresh")

This reduces the cold-start period from ~50 dictations to ~10 for common domains.

### R11. Answer the open questions (Section 17)

The spec lists 5 open questions. My recommendations:

1. **Cluster naming:** Use stable IDs (R2 above). Auto-generated display names are fine for UI.
2. **Thread merging:** Do NOT merge. The complexity is not worth the benefit. Two threads with similar content will naturally share co-occurrence edges. Merging risks corrupting the graph if the merge was wrong.
3. **Cross-app context:** Already solved by the weighted scoring in Section 5.4. The spec just needs to consistently apply this pattern to fingerprints too (W4 above).
4. **Privacy/paranoid mode:** Offer per-cluster encryption for sensitive topics (E4 above). Full paranoid mode (encrypt everything) should exist but be a last resort.
5. **Graph pruning:** Already well-handled in Section 13.2. The only addition: use incremental vacuum instead of full VACUUM (R5 above).

---

## Summary

The spec is well above average in thoroughness and demonstrates genuine understanding of the problem domain. The four-level resolution cascade, content-based threading, and correction learning loop are strong design choices backed by relevant research. The main risks are:

1. **Lemmatization gap (W1):** The single biggest threat to the system's accuracy. Without it, the co-occurrence graph will be sparse and fragmented for Ukrainian text.
2. **Cluster identity fragility (W2):** Will cause silent data corruption as the system evolves.
3. **No WAL mode (A1):** Will cause intermittent blocked reads under real-time dictation load.
4. **LIKE-based correction matching (W6):** SQL injection risk and false positive promotions.

Fix these four issues before implementation and the architecture is sound.

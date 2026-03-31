# Context Engine Architecture — Technical Review

**Date:** 2026-03-28
**Reviewer:** Claude Sonnet 4.6 (Senior Systems Architect)
**Spec reviewed:** `docs/superpowers/specs/2026-03-28-context-engine-architecture.md`
**Status:** Draft review — pending author response

---

## Strengths (what's well designed)

### S1. The 4-level cascade with clear stop conditions
The fallback chain (self-context → active thread → fingerprint → LLM) is architecturally clean. Each level has an explicit confidence threshold (0.6), a defined cost, and a single reason it fails. This is not a vague "try things until something works" approach — each level has a documented failure mode. This cascade matches the hybrid LLM + structured DST design that industry trends (Decagon, 2025) identify as the dominant pattern for reliable dialogue systems.

### S2. App-as-weight, not app-as-filter (Section 5.4)
The weighted cross-app scoring in `find_active_thread` is a genuinely smart design. Using `CASE WHEN ct.app = ? THEN 2.0 ELSE 1.0 END` as a weight multiplier instead of a hard `WHERE app = ?` filter correctly models the real workflow (Slack → VS Code for the same deploy task). The scoring table in Section 5.4 shows the team thought through boundary cases. Most naive implementations would hard-filter by app and miss cross-app continuity entirely.

### S3. Content-based thread separation (Section 5.3)
Solving the "two Саша" problem via keyword co-occurrence instead of window title is the right call. Window titles are unreliable identifiers — this is documented in the spec and the solution is proportionate. The example walkthrough (Sections 5.3) is concrete and verifiable.

### S4. Temporal decay formula is mathematically sound (Section 6.4)
The `1.0 / (julianday('now') - julianday(last_used) + 1)` decay is a simple hyperbolic function. It gives day-0 full weight and day-30 approximately 1/30 weight — this is a reasonable approximation of the Ebbinghaus forgetting curve. Recent NLP research (KVFKT 2025, N-ForGOT ICLR 2025) confirms that incorporating temporal decay into co-occurrence weights significantly improves long-term system accuracy.

### S5. No external dependencies is a defensible choice
"Pure SQLite, no vector DB, no ONNX" is explicitly justified in Section 2 and defended in Section 11.3. For a Windows desktop app targeting non-technical users, the zero-dependency constraint is correct product thinking. SQLite at 100K edges is well within performance bounds — 2025 benchmarks confirm 100K SELECTs/second on multi-GB databases is achievable (phiresky, 2025; andersmurphy, 2025).

### S6. PBKDF2 with 600,000 iterations (Section 13.3)
Using `iterations=600_000` matches the OWASP 2023+ recommendation for PBKDF2-SHA256. Most implementations use 10,000-100,000. This is a correctly hardened export password derivation.

### S7. Research references are current and appropriate (Section 18)
The ICLR 2026 WSD paper and the 2024 knowledge graph + context survey both support the chosen approach. The authors correctly note that the knowledge graph approach "remains competitive with neural methods for domain-specific WSD" — which is precisely the use case here.

---

## Weaknesses (specific problems with examples)

### W1. Confidence formula for Level 3 (fingerprint) is broken
Section 4, "Resolution Confidence" table:

```
Level 3 | Fingerprint match | hits / total_fingerprints — ratio of matching cluster
```

But in `cold_start_cluster` (Section 7.4), the actual confidence calculated is:

```python
confidence = results[0].hits / total   # total = sum(r.hits for r in results)
```

This is the ratio of **matching fingerprints for the winning cluster** over **all fingerprint matches across all clusters** — not `hits / total_fingerprints` as described in the confidence table. These are different numbers. The table says "ratio of matching cluster" (implying: hits for this cluster / total fingerprints in DB), but the code computes hits_winner / hits_all_matching. These diverge significantly. If the DB has 500 fingerprints total but only 3 ever match any keyword, you get confidence = 2/3 = 0.67 from the code, but 2/500 = 0.004 from the table description.

**Fix:** Unify the definition. The code's version (relative dominance among matching fingerprints) is actually the better metric. Update the table description to match.

### W2. `extract_keywords` hardcodes minimum word length at 3 characters
Section 11.1:
```python
words = [w for w in re.findall(r'\b\w{3,}\b', text.lower())
         if w not in STOP_WORDS]
```

This silently drops critical Ukrainian/English short tokens:
- "PR" (2 chars) — a core IT keyword
- "ТЗ" (2 chars, Ukrainian abbrev for tech specification)
- "DB" (2 chars)
- "CI" (2 chars)
- "VM" (2 chars)
- "ОЗ" (2 chars, medical — discharge summary)

In English and Ukrainian technical writing, 2-letter abbreviations carry high semantic density. The regex `\b\w{3,}\b` will correctly extract "pull" and "request" separately (3+ chars each), but miss "PR" in "зроби PR в GitHub" — exactly the IT context you need to detect.

**Fix:** Either lower the minimum to 2 chars with an expanded stopword list, or add an explicit allowlist of important 2-letter abbreviations, or use a pre-tokenization step that joins known abbreviations before the regex runs.

### W3. Co-occurrence pairs are symmetric but stored as bidirectional rows — write amplification is double what's needed
Section 6.3 explicitly inserts `(term_a, term_b)` AND `(term_b, term_a)` as separate rows. This doubles storage and halves write performance for no query benefit, because `find_active_thread` only queries `WHERE term_a IN (...)` — it doesn't need the reverse direction. The PRIMARY KEY is `(term_a, term_b, cluster)`, so a lookup for `замок` finds all edges where `замок` is `term_a`. The reverse row where `замок` is `term_b` is never read in any query shown.

**Evidence:** None of the SELECT queries in the spec use `WHERE term_b = ?` or `term_b IN (...)`. Only `term_a` is ever the lookup key.

**Fix:** Either (a) remove bidirectional INSERT and store only canonical order (normalize: always insert as `(min(a,b), max(a,b), cluster)`), or (b) if bidirectional lookup is genuinely needed, add an index on `term_b` and document which queries use it.

### W4. The `corrections` auto-promote query uses LIKE on unindexed columns
Section 10.2:
```python
similar = db.query("""
    SELECT COUNT(*) FROM corrections
    WHERE raw_text LIKE ? AND corrected_text LIKE ?
""", [f"%{old_token}%", f"%{new_token}%"])
```

The `idx_corrections_pattern` index in Section 15 is `ON corrections(raw_text, corrected_text)`, but SQLite cannot use a B-tree index for a `LIKE '%...%'` query (only prefix-LIKE `'token%'` can use an index). This is a full table scan of `corrections` on every correction event. At 100 corrections/day over 3 years = 100K rows, this becomes a noticeable bottleneck.

**Fix:** Either (a) store extracted tokens separately (a `correction_tokens` join table similar to `thread_keywords`), or (b) run the promotion logic asynchronously via a separate maintenance task, or (c) use a trigger that counts per (old_token, new_token) pair via a pre-aggregated counter table.

### W5. Thread matching returns only `LIMIT 1` but does not break ties deterministically
Section 5.4, `find_active_thread`:
```sql
ORDER BY weighted_score DESC, ct.last_message DESC
LIMIT 1
```

If two threads have identical `weighted_score` and `last_message` (e.g., two IT-cluster conversations about "деплой" both ended 10 minutes ago), the result is non-deterministic because SQLite's ORDER BY with LIMIT 1 has undefined tiebreaking beyond the specified columns. In practice this is unlikely but will produce flaky behavior in tests and edge-case user scenarios.

**Fix:** Add `ct.id DESC` as a final tiebreaker. This is cheap and makes the result deterministic.

### W6. The LLM confidence is hardcoded to 1.0 but LLMs hallucinate
Section 4, Level 4:
```
Level 4 | LLM | Always 1.0 (LLM is the final authority)
```

Setting LLM confidence to a constant 1.0 means the system never learns that the LLM made a wrong call. If the LLM resolves `замок` incorrectly and the user corrects it, the correction is stored (Section 10), but the system has no signal that "LLM was wrong here" to weight against future LLM decisions. Additionally, Section 10.2 classifies `error_source` as either `"stt"` or `"llm"` — so the error classification works, but it feeds back into the co-occurrence graph, not into any LLM-confidence discount.

**This is a design choice, not necessarily a bug**, but it means the system can repeatedly make the same LLM error without degrading confidence in that path. At minimum, track per-cluster LLM error rates from corrections and use them to inform whether LLM fallback is improving accuracy in that domain.

---

## Missing Edge Cases (scenarios not covered)

### E1. What happens when the user speaks about two distinct topics in one dictation?

The entire architecture assumes one dictation = one topic. But users commonly say:
> "Поміняй замок на вхідних, і ще нагадай мені зробити PR до п'ятниці"

`extract_keywords` would return: `[поміняй, замок, вхідних, нагадай, зробити, PR]`

The co-occurrence graph would see ПОБУТ (замок, вхідних) and IT (PR, зробити) terms together in one update. Over time this will pollute both clusters — IT and ПОБУТ terms will start appearing in each other's clusters. The `detect_cluster` function picks ONE winner cluster:

```python
if scores and scores[0].score >= 5:
    return scores[0].cluster
```

The losing cluster's terms get mislabeled in this dictation's co-occurrence update. This is a systematic bias problem if users frequently mix topics (which they do in practice — reminders and task-switching are common patterns in voice dictation).

**Suggested mitigation:** After cluster detection, if two clusters both score above threshold with comparable scores (e.g., score_2 > 0.7 × score_1), treat the dictation as "mixed" and skip the co-occurrence update for this dictation to avoid cross-contamination.

### E2. Cold-start failure for completely new users with no corrections vocabulary

Section 12.5 acknowledges the 0-20 dictation cold start (all unknown, LLM handles everything). But it doesn't specify what the user experience is when the LLM also fails or is offline (fallback providers all down). The pipeline diagram (Section 3.1) shows LLM has 3 providers in fallback order, but doesn't define what happens when ALL three fail. Does Stage 5 return the `replaced_text` unchanged? Does the user get an error? Is there a timeout?

**What's missing:** A defined degraded mode behavior in the spec — "when LLM is unavailable and term is unresolved, return the raw text with no normalization and surface a UI indicator."

### E3. Thread expiry race condition with rapid-fire dictation

The 15-minute expiry is checked "periodically" (Section 5.2: "THREAD EXPIRY (checked periodically)") but the spec doesn't define the check interval. If the user dictates 5 messages rapidly:
1. Thread created at T=0
2. Thread expires at T=15min (background check fires)
3. User dictates at T=15min+1s — no active thread found
4. New thread created — loses continuity with the previous 5 messages

The check could fire between two fast messages and prematurely split what is clearly one conversation. The same issue applies to the fingerprint save trigger: if expiry runs concurrently with a dictation that's updating `thread.last_message`, there's a TOCTOU race.

**Fix:** Thread expiry should not be a background job — it should be a lazy expiry check at read time (`find_active_thread` checks `last_message > datetime('now', '-15 minutes')`). The current SQL in `find_active_thread` already does this! But the spec also says "checked periodically" which implies a separate background job. Clarify: is thread expiry lazy (at query time, which is already implemented) or eager (background job)?

### E4. No handling for STT output that is entirely stop words

The `extract_keywords` function returns an empty list for:
- "ок" → filtered by STOP_WORDS
- "привіт, так, дякую" → all stop words
- "і ще ось" → all filtered by `\b\w{3,}\b` length check

Section 5.2 handles the 0-keywords case correctly:
```python
thread = db.query("SELECT ... WHERE app = ? AND is_active = 1 ... LIMIT 1")
```

But what if there is NO active thread in this app? The code calls `create_new_thread(keywords, current_app)` with an empty `keywords` list. What cluster does this thread get? The `detect_cluster([])` call would return "unknown" (the graph query with an empty IN() list would return zero rows). This is fine for cluster, but `thread_keywords` would have zero entries — and this thread can never be matched by `find_active_thread` with future keywords (since it has no keywords to overlap with). It becomes a dead thread that accumulates `message_count` but never matches anything.

**Fix:** Short/empty dictations (0 keywords) should not create new threads. They should either attach to the most recent app thread (as Section 5.2 describes) or be logged as app-level orphans without creating a thread entry.

### E5. Import collision: no handling for duplicate terms on profile merge

`import_profile` (Section 13.3) does a direct copy of tables with no conflict resolution:
```python
copy_table(import_db, db, table)
```

If the user already has a co-occurrence entry for `(замок, auth, IT, weight=50)` locally and the imported profile also has `(замок, auth, IT, weight=80)`, which wins? The spec doesn't define this. In SQLite, `INSERT` into a table with a PRIMARY KEY conflict will fail unless it's an `INSERT OR REPLACE` or `INSERT OR IGNORE`. The `copy_table` helper is not defined anywhere in the spec — its conflict behavior is unknown.

**Fix:** Define `copy_table` explicitly with a merge strategy. For `term_cooccurrence`, the correct merge is to SUM weights (not replace). For `dictionary`, it's probably REPLACE (newer version wins). This needs to be specified.

### E6. No handling for cluster drift over time

A user who worked in IT for 2 years then switches careers will have a heavily IT-weighted co-occurrence graph. After the switch, IT terms from years ago continue to pollute cluster detection because the temporal decay query (Section 6.4) decays weights but never removes them (pruning only removes `weight = 1` edges). A term pair like `(деплой, сервер, IT, weight=200)` from 2 years ago decays to 200/730 ≈ 0.27 — still visible in cluster detection. The graph never truly forgets a high-weight historical pattern.

**This is the fundamental tradeoff of hyperbolic decay.** The spec acknowledges this implicitly in the "Three Years" storage row (Section 13.1) but doesn't address the accuracy degradation from career/lifestyle changes.

---

## Architecture Concerns (scalability, reliability)

### A1. SQLite write serialization is a bottleneck only if future architecture goes async

Current architecture: single Windows desktop app, single user, single thread writes. SQLite's single-writer constraint is not a problem here — this is explicitly the right tool for this use case (phiresky, 2025 benchmarks confirm 100K SELECTs/sec on GBs of data). The concern would only arise if the architecture ever moves to a multi-process model (e.g., background service + UI process both writing). The spec doesn't mention WAL mode (`PRAGMA journal_mode=WAL`) which would allow concurrent readers during writes — this should be explicitly enabled for better read performance during maintenance.

**Recommendation:** Add `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` to the DB initialization. This is standard for SQLite apps and reduces fsync overhead by ~3x with negligible durability tradeoff for this use case.

### A2. The 5ms performance budget does not account for database cold cache

Section 14.1 claims:
```
Total context resolution: ~5ms
```

But SQLite performance benchmarks typically measure warm-cache queries. On startup (cold cache, OS page cache empty), the first few queries will hit disk — particularly the co-occurrence lookup and fingerprint JOIN. On a typical Windows SSD, a cold cache SQLite query on a 15MB database can take 50-200ms. This would blow the entire 50ms pipeline budget on the first dictation after app launch or after the OS flushes the page cache.

**Recommendation:** Warm the cache explicitly on startup: run a lightweight `SELECT COUNT(*) FROM term_cooccurrence` and `SELECT COUNT(*) FROM conversation_threads` after `daily_maintenance`. This forces the OS to cache the most-used pages and brings subsequent queries to the expected 1-5ms range.

### A3. `daily_maintenance` runs on app startup — can block the first dictation

Section 13.2:
```python
def daily_maintenance():
    """Run at app startup, max once per 24 hours."""
```

The `VACUUM` operation (step 6) on a 40MB database takes 200-500ms on a consumer SSD. If the user opens the app and immediately starts dictating, the first dictation arrives while `VACUUM` is still running. Since SQLite's VACUUM requires exclusive access, any concurrent read/write during VACUUM will either block or fail depending on journal mode.

**Recommendation:** Run `daily_maintenance` in a background thread, and explicitly defer VACUUM to a scheduled idle time (e.g., midnight, or 10 seconds after the last dictation). Track `last_vacuum_timestamp` in a settings table and check it in the idle handler, not at startup.

### A4. `update_cooccurrence` has no upper bound on pair generation

Section 11.2 shows:
```
8 keywords → 15 terms (with bigrams) → 105 co-occurrence pairs per dictation
```

But `extract_keywords` returns up to `max_keywords=12` which with bigrams can produce up to 23 terms (`N + (N-1)` for N=12). That gives `23 × 22 / 2 = 253` co-occurrence pairs per dictation. At 100 dictations/day = 25,300 UPSERT operations/day. In 3 years with no pruning = 27.7 million UPSERTs total. The spec's storage estimate of "100K edges after 3 years" (Section 13.1) seems to assume heavy consolidation — but if the user has a diverse vocabulary, 100K distinct term pairs is easily exceeded in 6-12 months.

**Recommendation:** Add a hard cap: if the co-occurrence table exceeds N edges (e.g., 200K), trigger an emergency prune of all edges with weight < 3 regardless of age, and log a warning. The current pruning in `daily_maintenance` step 5 only runs when a cluster exceeds 5,000 edges — this may be too late.

### A5. Fingerprint-based cold start is inherently brittle for short or high-variance openings

Section 7.4, `cold_start_cluster`:
```python
kws = keywords[:5]  # only use first 5 keywords from opening
```

The fingerprint search takes the first 5 keywords of the new dictation and tries to match them against stored conversation openings. The problem: conversation openings are highly variable ("привіт", "слухай", "так ось", "значить так") and frequently contain social preamble with zero semantic content. The spec's own STOP_WORDS filter will remove these, but the remaining content keywords from a single first message are often 1-2 words — insufficient for reliable fingerprint matching.

The spec acknowledges: "When it fails: Completely new topic never seen before" — but the more frequent failure mode is "familiar topic, unfamiliar opening phrasing," which the current fingerprint approach cannot handle.

---

## Research Findings (what you found online that confirms or contradicts the approach)

### R1. State-of-art DST confirms the hybrid approach (confirms)

Industry trends for 2025-2026 (Decagon, Shadecoder) show the dominant pattern is exactly what this spec implements: LLM handles free-text understanding, a structured state layer maintains the dialogue state. The spec's 4-level cascade is a lightweight implementation of this hybrid. The academic state-of-art (MultiWOZ 2.4 benchmarks) shows LLM-only approaches at 83% JGA — the spec's design correctly identifies that a LLM-only approach at Level 4 (fallback) with local state tracking (Levels 1-3) for high-confidence cases is the right architecture.

**Contradiction:** The spec targets <50ms total pipeline overhead. Academic DST systems typically run at 100-500ms per turn. The spec's aggressive local-first approach (Levels 1-3 at 0 tokens) is what makes the latency target achievable — this is a deliberate and correct tradeoff, not covered in the academic literature which doesn't have the same latency requirements.

### R2. SQLite at 100K+ edges is well within limits (confirms)

Two independent 2025 benchmarks confirm SQLite handles:
- 1 billion rows with 100K TPS (andersmurphy, 2025)
- 100K SELECTs/second on multi-GB databases (phiresky, 2025)

The spec's projected 100K co-occurrence edges with 5ms query time is comfortably within SQLite's capabilities. **The 5ms claim is credible for warm-cache queries.** However, the GROUP BY + ORDER BY aggregation in `detect_cluster` (Section 12.3) does a full scan of `term_cooccurrence WHERE term_a IN (...)` without a cluster-specific index — this query's performance should be validated at 50K+ edges since GROUP BY on a covered index scan can still be expensive.

### R3. Multilingual keyword extraction from short texts is an open problem (contradicts partially)

Research (MAKED 2022, multi_rake) confirms that keyword extraction from short multilingual texts is genuinely hard, and statistical methods (TF-IDF, TextRank) require longer documents to be reliable. The spec's decision to use unigram+bigram extraction with a learned co-occurrence filter as a TF-IDF replacement (Section 11.3) is well-reasoned.

**However:** Ukrainian NLP research (UNLP 2025 shared task, osyvokon/awesome-ukrainian-nlp) highlights that Ukrainian-English code-switching creates specific tokenization problems that pure regex approaches miss:
- Transliterated words: "деплой" (Ukrainian transliteration of "deploy") — the regex handles these, but stopword lists may not cover Ukrainian filler words comprehensively
- Mixed-script tokens: "PR-запит", "CI/CD" — the regex `\b\w{3,}\b` will split "CI/CD" into ["CID", "CD"] or just fail to match depending on how the STT outputs it (Cyrillic vs Latin scripts, slash handling)

**Recommendation:** The stopword list in Section 11.1 shows `...` (truncated) — the spec should fully specify the Ukrainian stopword list since it's critical to keyword quality. A missing filler word becomes a junk keyword that pollutes all co-occurrence pairs it appears in.

### R4. GDPR and local storage — the approach is sound but has gaps (partially confirms)

GDPR research (Picovoice, heydata.eu) confirms:
1. Voice content is personal data under GDPR Article 4(1)
2. Local-only storage with no cloud sync is the most privacy-preserving architecture
3. End-to-end encryption at rest is required if the data includes sensitive personal content

The spec correctly encrypts `raw_text` and `normalized_text` (the actual speech content) with DPAPI. **However:**
- `conversation_threads.topic_summary` (e.g., "ремонт квартири", "деплой на прод") is stored **unencrypted** (Section 5.4, Section 13.3 — it's listed in "unencrypted tables — direct copy")
- `thread_keywords` are stored **unencrypted**
- `conversation_fingerprints` keywords are stored **unencrypted**

These unencrypted tables effectively contain a diary of the user's activities (topics, apps, timing), even without the full transcription. Under GDPR Article 4, this metadata is personal data. If someone gains read access to the SQLite file (e.g., malware, forensics), they can reconstruct a detailed behavioral profile even without the encrypted history texts.

Section 17 (Open Questions) item 4 mentions a "paranoid mode" but treats this as optional. For GDPR compliance in the EU market, this is not optional — it's at minimum a documented known limitation that should be communicated to users.

### R5. Competing products confirm the market, but none have local co-occurrence learning (confirms unique positioning)

Monologue (moge.ai, 2025) supports 100+ languages with context-aware adaptation — but is cloud-based. Willow Voice (willowvoice.com) offers context-aware transcription with 200ms latency — also cloud-based. Soniox handles mid-sentence language switching — API-only.

**None of the found competitors implement local co-occurrence learning for context disambiguation.** This is a genuine differentiator. The closest approach is Monologue's "adapts to your vocabulary" feature, but it's unclear if this is local or cloud-processed.

The privacy angle (all context stored locally, encrypted) is both a differentiator and a challenge — local co-occurrence graphs require a cold-start period that cloud products don't have (they aggregate across users).

---

## Recommendations (concrete actionable improvements)

### REC1. Fix the confidence formula discrepancy (Critical — blocks spec correctness)

In Section 4's confidence table, replace:
> `hits / total_fingerprints — ratio of matching cluster`

With:
> `hits_winner / sum(hits_all_clusters) — dominance ratio among matching fingerprints`

And add a minimum hits threshold: `confidence = 0.0 if results[0].hits < 2 else hits_winner / total`. The current code already checks `results[0].hits >= 2` before accepting, but the confidence formula should reflect this.

### REC2. Fix 2-letter abbreviation blindspot in `extract_keywords` (High)

Replace:
```python
words = [w for w in re.findall(r'\b\w{3,}\b', text.lower())
         if w not in STOP_WORDS]
```

With:
```python
IMPORTANT_SHORT = {"pr", "db", "ci", "vm", "тз", "оз", "ка", "іт", "пр"}
words = []
for w in re.findall(r'\b\w{2,}\b', text.lower()):
    if w in IMPORTANT_SHORT or (len(w) >= 3 and w not in STOP_WORDS):
        words.append(w)
```

Alternatively, tokenize before lowercasing and preserve uppercase 2-letter tokens as high-priority keywords.

### REC3. Normalize co-occurrence direction to eliminate redundant bidirectional rows (High)

In `update_cooccurrence` (Section 6.3), replace the current dual-INSERT with canonical ordering:
```python
def update_cooccurrence(keywords: list[str], cluster: str):
    for i, term_a in enumerate(keywords):
        for term_b in keywords[i+1:]:
            a, b = sorted([term_a, term_b])  # canonical order: alphabetically smaller first
            db.execute("""
                INSERT INTO term_cooccurrence (term_a, term_b, cluster, weight, last_used)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(term_a, term_b, cluster)
                DO UPDATE SET weight = weight + 1, last_used = CURRENT_TIMESTAMP
            """, [a, b, cluster])
```

Then update all lookup queries to use `WHERE (term_a IN (...) OR term_b IN (...))` or add a covering index. This halves table size and halves write amplification.

**Caveat:** This requires auditing all `SELECT` queries that currently only search `term_a`. List them all in the spec.

### REC4. Replace LIKE-based correction pattern matching with a token counter table (High)

Replace the `LIKE '%token%'` auto-promotion logic with:
```sql
CREATE TABLE correction_counts (
    old_token TEXT NOT NULL,
    new_token TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    PRIMARY KEY (old_token, new_token)
);
```

On each correction:
```python
db.execute("""
    INSERT INTO correction_counts (old_token, new_token, count)
    VALUES (?, ?, 1)
    ON CONFLICT(old_token, new_token)
    DO UPDATE SET count = count + 1
""", [old_token, new_token])

count = db.query("SELECT count FROM correction_counts WHERE old_token=? AND new_token=?",
                 [old_token, new_token])[0].count
if count >= 3:
    add_to_dictionary(old_token, new_token, type="exact", origin="correction")
```

This is O(1) per correction instead of a full-table LIKE scan.

### REC5. Enable WAL mode and explicit cache warming (Medium)

Add to DB initialization:
```python
def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB page cache
    conn.execute("PRAGMA temp_store=MEMORY")
    # Warm cache after daily maintenance
    conn.execute("SELECT COUNT(*) FROM term_cooccurrence")
    conn.execute("SELECT COUNT(*) FROM conversation_threads WHERE is_active=1")
    return conn
```

### REC6. Move VACUUM to a background idle task (Medium)

```python
def daily_maintenance():
    # ... steps 1-5 as specified ...
    # Step 6: Schedule VACUUM for idle time, not inline
    schedule_idle_task(vacuum_db, min_idle_seconds=30)

def vacuum_db():
    if days_since_last_vacuum() >= 7:
        db.execute("VACUUM")
        update_last_vacuum_timestamp()
```

### REC7. Resolve the "Open Questions" before implementation (Medium)

Section 17 lists 5 open questions. Three of them have clear answers that should be decided now:

- **Q1 (Cluster naming):** Auto-naming from top terms is the right call. Fixed vocabulary defeats the "works for any profession" design goal. Cluster names are display-only (Section 12.2 confirms this). Decide and close.

- **Q3 (Cross-app context):** The spec already partially answers this with the cross-app weighting in `find_active_thread`. The question is whether to enable cross-app thread continuity beyond keyword overlap. **Recommendation:** Keep the current weighted approach (already implemented), close this question.

- **Q5 (Graph pruning):** Already answered by Section 13.2. The pruning is implemented. Close this question and update Section 17 to mark it resolved.

### REC8. Specify the full Ukrainian stopword list (Medium)

The stopword list in Section 11.1 ends with `...` (ellipsis). This is unacceptable for a spec — the stopword list is a critical parameter that determines keyword quality. Every word that's NOT in the stopword list becomes a potential keyword and co-occurrence pollutant. Specify the complete list (or reference an external file) and document the criteria for inclusion.

**Reference:** The `osyvokon/awesome-ukrainian-nlp` repository contains curated Ukrainian stopword lists suitable as a starting point.

### REC9. Address unencrypted metadata GDPR exposure (Medium — EU market blocker)

Add a section to the spec documenting:
1. What unencrypted data is stored: `thread_keywords`, `fingerprint_keywords`, `topic_summary`
2. The threat model for this data (file-system access required, no network exposure)
3. Either: implement optional encryption for these tables (at the cost of full-table scans instead of indexed lookups), OR document this as a known privacy limitation in the user-facing privacy policy

Option B (documentation) is acceptable for v1 but should be flagged as a v2 target.

### REC10. Define degraded mode behavior for all-LLM-providers-down (Low — but user-facing)

Add to Section 3.1 (pipeline) or Section 9.3:

> **Degraded mode:** When all LLM providers are unavailable (Groq + OpenAI + Anthropic all fail) and at least one normalization toggle is ON:
> - Return `replaced_text` without normalization
> - Apply exact dictionary terms (Stage 6) — these are always local
> - Surface a non-blocking UI notification: "Normalization unavailable — using raw transcription"
> - Log the failure with timestamp for user diagnostics

---

## Summary Assessment

The core architecture is sound and demonstrates careful thinking. The 4-level cascade, content-based thread separation, and local co-occurrence graph are all well-reasoned design choices that hold up against current research. The SQLite-only, zero-dependency constraint is appropriate for the target platform.

The critical issues to address before implementation:

1. **Fix the confidence formula inconsistency** (W1) — it will cause subtle bugs in Level 3 resolution
2. **Fix the 2-letter abbreviation blindspot** (W2) — PR, DB, CI are the most common IT keywords
3. **Fix the LIKE-based promotion query** (W4) — it's a performance timebomb
4. **Fully specify the stopword list** (REC8) — affects all co-occurrence quality
5. **Resolve Section 17 open questions** (REC7) — implementation can't start on undecided architecture

Everything else is optimization or polish that can be addressed in v1.1.

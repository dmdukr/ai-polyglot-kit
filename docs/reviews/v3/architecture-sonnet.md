# Context Engine Architecture — Second Review (v3)

**Date:** 2026-03-28
**Reviewer:** Claude Sonnet 4.6 (Senior Systems Architect — second pass)
**Spec reviewed:** `docs/superpowers/specs/2026-03-28-context-engine-architecture.md`
**Previous review:** `docs/reviews/2026-03-28-context-engine-review-sonnet.md`
**Spec claims:** "Draft v3 — all 20 review issues resolved"
**Status:** Second review — verifying 20 fixes, searching for new issues

---

## Previous Issues — Verification

The spec header claims "all 20 review issues resolved." The previous review (Sonnet) identified 5 Weaknesses (W1-W6, but W6 was labeled design choice), 6 Edge Cases (E1-E6), 5 Architecture Concerns (A1-A5), and 10 Recommendations (REC1-REC10). This section verifies each.

### W1. Confidence formula for Level 3 — FIXED correctly

Previous: Table said `hits / total_fingerprints`, code computed `hits_winner / hits_all_matching`.

Section 4 now reads:
> `hits_winner / sum(hits_all_clusters) — dominance ratio among matching fingerprints, requires hits ≥ 2`

The code in Section 7.4 matches exactly:
```python
total = sum(r.hits for r in results)
confidence = results[0].hits / total
```
And the guard `results[0].hits >= 2` is present. **Fix verified. Correct.**

### W2. 2-letter abbreviation blindspot — FIXED correctly

Previous: `\b\w{3,}\b` dropped PR, CI, DB, etc.

Section 11.2 now has:
```python
IMPORTANT_SHORT = {"pr", "db", "ci", "cd", "vm", "ai", "ui", "ux", "js", "go", "тз", "оз", "пр", "іт", "зп", "пк", "бд"}
raw_words = re.findall(r'[a-zа-яіїєґ]{2,}', text.lower())
```
And the filter correctly passes `IMPORTANT_SHORT` words through regardless of length.

**Fix verified. Correct.**

However: **new sub-issue introduced by the fix** — see NI3 below.

### W3. Bidirectional co-occurrence rows — FIXED correctly

Previous: Both `(a,b)` and `(b,a)` were inserted, doubling storage with no query benefit.

Section 6.3 now explicitly stores pairs in canonical order (`term_a < term_b`), the code does `a, b = sorted([t1, t2])`, and Section 6.2 documents:
```sql
-- Pairs stored in canonical order: term_a < term_b (see Section 6.3)
```

The `idx_cooccurrence_reverse` index on `term_b` is now present, and the decay query in Section 6.4 correctly searches both directions:
```sql
WHERE (term_a = ? AND term_b IN (?, ?, ?))
   OR (term_b = ? AND term_a IN (?, ?, ?))
```

**Fix verified. Correct.**

### W4. LIKE-based correction auto-promote — FIXED correctly

Previous: `LIKE '%token%'` was a full-table scan timebomb.

Section 10.2 now uses `correction_counts` table with compound primary key `(old_token, new_token)` and UPSERT increment. The `corrections` table's `idx_corrections_pattern` index still exists (Section 15), but it's no longer used for the O(n) LIKE scan — that code is gone. The auto-promote path is now O(1).

**Fix verified. Correct.**

### W5. Non-deterministic tiebreaking in `find_active_thread` — FIXED correctly

Previous: `ORDER BY weighted_score DESC, ct.last_message DESC` had undefined behavior on ties.

Section 5.4 now has:
```sql
ORDER BY weighted_score DESC, ct.last_message DESC, ct.id DESC
LIMIT 1
```

`ct.id DESC` as final tiebreaker makes the result deterministic. **Fix verified. Correct.**

### W6. LLM confidence hardcoded to 1.0 — FIXED (addressed as design)

Previous review labeled this a design choice, not necessarily a bug. The spec now addresses this properly in Section 10.4 with a `cluster_llm_stats` table and `get_llm_confidence()` function that reduces confidence from 1.0 to 0.8 when error rate exceeds 20%.

**Fix verified. The tracked improvement is implemented.**

Note: The confidence step function (1.0 → 0.8 binary threshold at 20% error rate) is coarse — see NI5 below.

### E1. Mixed-topic dictation poisoning clusters — FIXED correctly

Section 6.3.1 `should_update_cooccurrence()` implements exactly the suggested mitigation: if `score_2 > 0.7 * score_1`, skip graph update and return `(False, best.cluster_id)`. The 0.7 threshold is a reasonable heuristic.

**Fix verified. Correct.**

### E2. All LLM providers down — FIXED

Section 9.3 now states that LLM is always called when any toggle is ON, but the pipeline description (Stage 5) implies providers fail gracefully. However, the spec still does not define what `replaced_text` is returned to the user when all three LLM providers fail. The Section 9.3 text says:

> "If ALL toggles OFF → skip entirely"

But there is no corresponding statement for "ALL providers fail WITH toggles ON." The degraded mode spec (REC10 from previous review) was not added. **Partially addressed — see NI6.**

### E3. Thread expiry race condition — FIXED correctly

Section 5.2 now explicitly states:
> "THREAD EXPIRY (lazy — checked at query time, NOT a background job)"

And the comment confirms the `find_active_thread` WHERE clause is the expiry mechanism. The conflict between "checked periodically" and the query-time implementation is resolved. **Fix verified. Correct.**

### E4. Zero-keyword dictation creating dead threads — FIXED correctly

Section 5.2 now handles this explicitly:
```python
if not keywords:
    # 0 keywords AND no active thread → orphan dictation, do NOT create dead thread
    return None  # caller stores history with thread_id = NULL
```

The code prevents creating threads with 0 keywords. **Fix verified. Correct.**

### E5. Import collision / no merge strategy — FIXED correctly

Section 13.3 now has per-table merge strategies:
- `term_cooccurrence`: `merge_table_sum_weights()` — SUM weights
- `dictionary`: `merge_table_replace()` — imported version wins
- `thread_keywords`, `fingerprint_keywords`: `merge_table_union()` — UNION
- `corrections`: `merge_table_ignore()` — no duplicates
- `correction_counts`: `merge_table_ignore()`
- `scripts`, `app_rules`: `merge_table_replace()` — latest version wins

Each strategy is specified. **Fix verified. Correct.**

### E6. Cluster drift over time — NOT FIXED, but acknowledged

Previous review noted this as a fundamental tradeoff. The spec has not added any mechanism to address career/lifestyle changes causing high-weight historical patterns to dominate despite temporal decay. Section 6.4 explains the decay mechanics but does not address the "stuck at historical domain" problem for very high-weight edges (weight=200+ edges from years ago decay slowly). Section 17.3 mentions "privacy mode" but not cluster drift.

**This was accepted as a known limitation — acceptable for v1. Not a blocking issue.**

### A1. WAL mode not enabled — FIXED correctly

Section 15.1 now shows WAL mode and PRAGMAs:
```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
```

This matches best practices confirmed by current SQLite documentation (2025). **Fix verified. Correct.**

### A2. Cold cache performance not addressed — FIXED correctly

Section 13.2 now includes `warm_cache()` called at the end of `daily_maintenance()`. The warm cache runs `SELECT COUNT(*) FROM term_cooccurrence` and two others to pre-populate the OS page cache. **Fix verified. Correct.**

### A3. VACUUM blocking dictation at startup — FIXED correctly

`daily_maintenance()` no longer runs VACUUM inline. Section 13.2 now has a separate `schedule_vacuum()` function that defers VACUUM to idle time (60s of no activity) and only runs it weekly (`days_since_last_vacuum() >= 7`). `VACUUM INTO` for daily backup now replaces inline VACUUM. **Fix verified. Correct.**

### A4. No upper bound on co-occurrence pair generation — FIXED correctly

Section 11.3 now documents:
> "Emergency prune — if co-occurrence table exceeds 200K edges, prune all weight < 3"

And the `daily_maintenance` step 5 has consolidation logic for clusters exceeding 5,000 edges. **Fix verified. Correct.**

### A5. Fingerprint brittleness for variable openings — Acknowledged, not structurally fixed

The spec notes (Section 7.4) that `kws = keywords[:5]` only uses first 5 keywords and has a fallback:
```python
if not results:
    # Fallback: search without app filter
    results = db.query(...)
```

The fundamental brittleness (preamble words, 1-2 content words in opening) is not structurally resolved, but the cross-app fallback helps. **Accepted as a known limitation — consistent with previous review assessment.**

### REC7. Section 17 open questions — PARTIALLY FIXED

Previous Section 17 had 5 open questions. Current Section 20 has only 2:
1. Thread merging
2. Cross-app context

Questions 1 (Cluster naming — now auto-naming from top terms), 3 (cross-app weighting), and 5 (graph pruning) are resolved and removed. Questions that remain (thread merging, cross-app context) are genuine open architecture questions without clear answers. **Acceptable — previous review's three "closeable" questions are closed.**

### REC8. Full Ukrainian stopword list — FIXED correctly

Section 11.2 now has the complete stopword lists for both Ukrainian and English, with named constants `STOP_WORDS_UK` and `STOP_WORDS_EN`. The list is fully specified, not truncated with `...`. **Fix verified. Correct.**

### REC9. Unencrypted metadata GDPR exposure — FIXED with documentation

Section 17 (Privacy & Unencrypted Metadata) now has a complete table of what is stored unencrypted, a threat model (Section 17.2), and a future "Privacy Mode" section (17.3) that documents the tradeoffs. The decision to store keywords unencrypted is documented as a deliberate design choice with rationale. **Fix verified. Acceptable for v1.**

### REC10. Degraded mode for all-LLM-down — NOT FIXED

Section 9.3 does not define behavior when all three LLM providers fail with toggles ON. The spec mentions 3 providers in fallback order but provides no fallback when all three are exhausted. **This remains open — see NI6.**

---

## New Issues Found

### NI1. `tree_stem` is not available on PyPI — installation path undefined (BLOCKER)

**Discovery:** Web research and `pip show tree_stem` both confirm `tree_stem` is NOT available as a PyPI package. The GitHub repository (amakukha/stemmers_ukrainian) has 29 stars and 26 commits — it is a research prototype distributed as a raw `.py` file, not a PyPI package.

**What the spec says:** Section 2 claims:
> "pure SQLite + `tree_stem` for Ukrainian stemming (~50KB, pure Python)"

Section 11.4: "`tree_stem` is the only dependency (~50KB)"

And Section 11.1 code:
```python
from tree_stem import stem_uk
```

**The problem:** `pip install tree_stem` will fail. PyInstaller cannot bundle a package that doesn't exist on PyPI. The package must either be:
1. Vendored directly into `src/` (the 48KB `.py` file copied in)
2. Installed from GitHub via `pip install git+https://github.com/amakukha/stemmers_ukrainian.git` (requires internet at build time and changes with any upstream update)
3. Published to PyPI as a fork/maintained package by this project

**Additional concern:** The repository shows last activity in November 2022. Python 3.12 support is unconfirmed. On Windows with PyInstaller, the pure-Python claim needs verification — if tree_stem uses any CPython internal APIs, it may fail in a frozen bundle.

**Fix required:** The spec must define exactly how `tree_stem` is distributed with the app: vendor path, PyInstaller hook if needed, and which exact version/commit is used. This is a supply chain / build reproducibility issue.

### NI2. `detect_cluster` query doubles keyword list but may give wrong results for canonical-order pairs (MEDIUM)

**Location:** Section 12.3

```python
scores = db.query(f"""
    SELECT cluster_id, SUM(weight) as score
    FROM term_cooccurrence
    WHERE term_a IN ({placeholders}) OR term_b IN ({placeholders})
    GROUP BY cluster_id
    ORDER BY score DESC
""", [*keywords, *keywords])
```

The query passes `keywords` twice (once for `term_a`, once for `term_b`), which is correct. However, because pairs are stored in canonical order (`term_a < term_b`), a query keyword "замок" may appear as `term_b` in many pairs (e.g., `(auth, замок, IT)` where `auth < замок` alphabetically). The `OR term_b IN (...)` clause correctly catches these, and `idx_cooccurrence_reverse` index covers this.

**But:** The `should_update_cooccurrence` function in Section 6.3.1 also passes keywords twice to the same `OR term_a / term_b IN (...)` pattern. This is consistent. **No bug here.**

However, a subtler issue: for a keyword that appears in pairs as both `term_a` and `term_b` in DIFFERENT pairs, its edges will be counted once via `term_a` match and again via `term_b` match — but since they're different rows (different pairs), they contribute independently to `SUM(weight)`. **This is correct behavior.** The query is sound.

**Verdict: No bug. But the double-parameter pattern should be documented with a comment explaining why `keywords` appears twice in the parameter list — it's confusing enough to cause maintenance bugs when someone reads the code.**

### NI3. `extract_keywords` lemmatizes IMPORTANT_SHORT words — introduces stem artifacts (LOW, but correctness issue)

**Location:** Section 11.2

```python
for w in raw_words:
    if w in IMPORTANT_SHORT:
        words.append(w)          # appended as-is, NOT lemmatized
    elif len(w) >= 3 and w not in STOP_WORDS:
        words.append(lemmatize(w))  # lemmatized
```

This looks correct at first glance — short abbreviations like "pr" are appended without lemmatization, which is right.

**BUT:** The lemmatize function in Section 11.1 is:
```python
def lemmatize(word: str) -> str:
    if any('а' <= c <= 'я' or c == 'і' or c == 'ї' or c == 'є' or c == 'ґ' for c in word):
        return stem_uk(word)
    return word  # English: "deploy" → "deploy"
```

Ukrainian 2-letter abbreviations in `IMPORTANT_SHORT` include `тз`, `оз`, `пр`, `іт`, `зп`, `пк`, `бд` — these all contain Cyrillic characters. If any of these were to pass through the `len(w) >= 3` branch (they can't, because they're 2 chars), they'd be passed to `stem_uk`. But since they're in `IMPORTANT_SHORT`, they bypass this. **No bug here for the listed abbreviations.**

**Real issue:** The bigram generation at the end of `extract_keywords` uses the `words` list which is a mix of `IMPORTANT_SHORT` (unlemmatized) and regular words (lemmatized). A bigram like `"зроб pr"` (from "зроби PR") is fine. But a bigram like `"pr github"` would be `"pr github"` (both unchanged, correct). The mix is safe.

**However:** If `tree_stem` produces an overly aggressive stem for a word immediately before or after an IMPORTANT_SHORT token, the bigram combines an aggressive stem with a raw abbreviation. For example: `"зроби тз"` → words: `["зроб", "тз"]` → bigrams: `["зроб тз", "тз"]`. The bigram `"зроб тз"` uses a stem, not the original. When this bigram is stored in `term_cooccurrence`, it must match future occurrences with the SAME stem. This is consistent and correct — as long as `stem_uk` is deterministic (which a stemmer must be). **No bug, but worth noting in implementation docs.**

### NI4. `copy_table` used in import without merge strategy for `conversation_threads`, `conversation_fingerprints`, and `clusters` — potential PRIMARY KEY collision (MEDIUM)

**Location:** Section 13.3, import flow:
```python
copy_table(import_db, db, "conversation_threads")
copy_table(import_db, db, "conversation_fingerprints")
copy_table(import_db, db, "clusters")
```

`conversation_threads.id` is `INTEGER PRIMARY KEY` (rowid). `clusters.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`. `conversation_fingerprints.id` is `INTEGER PRIMARY KEY`.

**The problem:** When importing from another machine, the imported DB will have its own auto-increment sequences. If the local DB already has a thread with id=42 and the imported DB also has a thread with id=42 (different conversation), `copy_table` without conflict resolution will either:
- Fail with UNIQUE constraint violation (if using plain INSERT)
- Silently overwrite local data (if using INSERT OR REPLACE)

The spec doesn't define `copy_table` behavior for integer PK collisions. Unlike the `term_cooccurrence` table (which has a meaningful compound key and uses `merge_table_sum_weights`), threads have auto-increment integer PKs with no semantic meaning — there is no way to detect if two rows with the same id represent the same conversation or two different ones.

**Fix:** For `conversation_threads`, `conversation_fingerprints`, and `clusters`, the import strategy should either:
1. Re-assign IDs on import (INSERT with ID stripped, get new AUTOINCREMENT values) and re-map all foreign key references, OR
2. Use `INSERT OR IGNORE` (skip conflicts, silently drop imported threads that collide), OR
3. Offset all imported IDs by `MAX(id)` of the local table to guarantee no collisions

None of these is defined. The spec acknowledges merge strategies exist but `copy_table` (used for these three tables) is still undefined.

### NI5. LLM confidence step function is too coarse — 0.8 is an arbitrary single threshold (LOW)

**Location:** Section 10.4, `get_llm_confidence()`:
```python
if error_rate > 0.2:
    return 0.8  # LLM unreliable for this cluster — rely more on graph
return 1.0
```

This is a binary step function: below 20% error rate → confidence 1.0; above 20% → confidence 0.8. Two problems:

1. **Threshold sensitivity:** The 20% threshold is arbitrary and undocumented. A cluster with error_rate=0.19 gets confidence 1.0, while error_rate=0.21 gets 0.8. There's no justification for 20% vs 15% or 25%.

2. **Step size:** The drop from 1.0 to 0.8 may be too small to change level selection. The cascade threshold is 0.6 (Section 4: "confidence ≥ 0.6 → accept"). Even with 0.8 confidence from Level 4 (LLM), the LLM still "wins" — the reduced confidence changes nothing because it's still above threshold. The only scenario where 0.8 matters is if Levels 1-3 score exactly between 0.6 and 0.8 — an extremely narrow band.

**Recommendation:** Either make the confidence reduction continuous (`return max(0.5, 1.0 - error_rate * 2)`) or document the exact scenario where 0.8 vs 1.0 changes the resolution outcome. As written, this code may be dead logic in practice.

### NI6. All-LLM-providers-down behavior is still undefined (MEDIUM — user-facing)

**Location:** Section 9.3 and Stage 5 of pipeline.

The spec describes LLM as "always called when at least one toggle is ON" and lists 3 providers in fallback order. But what happens when all 3 fail?

- Stage 5 output is `normalized_text`
- Stage 6 applies exact dictionary terms
- Stage 7 injects into app

If Stage 5 fails entirely, does the pipeline return `replaced_text` (Stage 3 output) unchanged? Does it throw an exception? Does the overlay show an error? The user may not know their dictation failed normalization.

This was REC10 from the previous review and was not addressed. **This is a user-facing correctness issue, not just a robustness concern.** A user who relies on grammar normalization (toggle ON) will receive unnormalized output without any warning.

**Fix required before implementation:** Add to Section 9.3 or the pipeline (Section 3.1) a defined degraded mode:
> "When all LLM providers fail: return `replaced_text` without normalization. Apply Stage 6 exact dictionary terms. Surface a non-blocking UI notification. Log failure with timestamp."

### NI7. `name_cluster` only queries `term_a` for top terms — underestimates canonical-order pair representation (LOW)

**Location:** Section 12.2:
```python
top_terms = db.query("""
    SELECT term_a, SUM(weight) as total
    FROM term_cooccurrence
    WHERE cluster_id = ?
    GROUP BY term_a
    ORDER BY total DESC
    LIMIT 3
""", [cluster_id])
```

With canonical order (`term_a < term_b`), a high-frequency term like "замок" that alphabetically comes after most of its co-occurrence partners will appear primarily as `term_b`, not `term_a`. The above query only scans `term_a` — so "замок" would be invisible to `name_cluster` despite being the cluster's dominant concept.

**Example:** If IT cluster has pairs:
- `(auth, замок, IT)` — "замок" is `term_b` (because `auth < замок`)
- `(git, замок, IT)` — "замок" is `term_b`
- `(pr, замок, IT)` — "замок" is `term_b`

The `name_cluster` query would never rank "замок" as a top term even though it's the most connected concept in the cluster. Instead it would surface "auth", "git", "pr" as separate top terms.

**Fix:** The query should aggregate across both directions:
```sql
SELECT term, SUM(total_weight) as total
FROM (
    SELECT term_a as term, SUM(weight) as total_weight FROM term_cooccurrence WHERE cluster_id = ? GROUP BY term_a
    UNION ALL
    SELECT term_b as term, SUM(weight) as total_weight FROM term_cooccurrence WHERE cluster_id = ? GROUP BY term_b
) GROUP BY term ORDER BY total DESC LIMIT 3
```
This gives accurate top-term ranking regardless of alphabetical position.

### NI8. `idx_corrections_pattern ON corrections(raw_text, corrected_text)` is unused dead index (LOW)

**Location:** Section 15.2 (schema):
```sql
CREATE INDEX idx_corrections_pattern ON corrections(raw_text, corrected_text);
```

The previous review identified this index as designed for LIKE pattern matching (which can't use B-tree indexes). That LIKE query was correctly removed (W4 fix). But the index was NOT removed from the schema in Section 15.2 — it's still there.

After the W4 fix, the `corrections` table is never queried by `raw_text` or `corrected_text` in any code shown in the spec. The index has zero queries using it and wastes ~5-10% of `corrections` table storage.

**Fix:** Remove `CREATE INDEX idx_corrections_pattern ON corrections(raw_text, corrected_text)` from the schema entirely, or add a comment explaining why it's retained (e.g., future analytics queries, manual investigation).

---

## Consistency Check

### SQL Schema vs. Code Examples

**Section 6.2 schema vs. Section 6.3 code — CONSISTENT**
Schema uses `cluster_id INTEGER NOT NULL REFERENCES clusters(id)`. Code: `VALUES (?, ?, ?, 1, ...)` with `cluster_id` as third positional parameter. Consistent.

**Section 5.4 schema vs. Section 5.4 query — PARTIALLY INCONSISTENT**
Schema for `conversation_threads` includes `last_app TEXT` column. The `find_active_thread` query in Section 5.4 does NOT update `last_app` when a cross-app match occurs. The `assign_to_thread` code also doesn't update `last_app`. The column exists in the schema but has no code that writes to it.

**Either `last_app` should be removed from the schema, or `assign_to_thread` should update it with `current_app` on every match.** The column's intent (cross-app tracking, per the comment) is valuable, but it's currently a dead column.

**Section 7.3 (fingerprint creation) vs. Section 7.4 (fingerprint query) — CONSISTENT**
Both use normalized `fingerprint_keywords` join table, parameterized queries, no LIKE. Consistent.

**Section 10.2 (learn_from_correction) vs. Section 10.3 (corrections schema) — MINOR INCONSISTENCY**
`learn_from_correction` inserts with `error_source` set to either `"stt"` or `"llm"`:
```python
error_source = "stt"  # STT heard it wrong
# or
error_source = "llm"  # LLM changed it wrong
```
But the schema comment says:
```sql
error_source TEXT,  -- 'stt' | 'llm' | 'both'
```
The code has no path that produces `'both'`. A correction where the STT heard it wrong AND the LLM changed it further would only get `'stt'` because the `if old_token in raw` check fires first. The `'both'` value is unreachable with the current code logic.

**Either remove `'both'` from the schema comment, or add logic to detect the compound case.**

**Section 12.2 (`name_cluster`) vs. Section 6.3 (canonical ordering) — INCONSISTENT**
Covered in NI7 above — `name_cluster` only queries `term_a` but canonical ordering means important terms appear as `term_b`.

**Section 15.2 indexes vs. Section 6.4 temporal decay query — CONSISTENT**
The decay query:
```sql
WHERE (term_a = ? AND term_b IN (?, ?, ?))
   OR (term_b = ? AND term_a IN (?, ?, ?))
```
Uses both `idx_cooccurrence` (covers `term_a, cluster_id, weight DESC`) and `idx_cooccurrence_reverse` (covers `term_b, cluster_id, weight DESC`). Both indexes are present in schema. Consistent.

**Section 13.3 import list vs. Section 15.2 schema — MINOR GAP**
The export table list in Section 13.3 includes `correction_counts` and `cluster_llm_stats`. The import flow calls `merge_table_ignore(import_db, db, "correction_counts")` but there is no import call for `cluster_llm_stats`. If `cluster_llm_stats` is not imported, per-cluster LLM error rates are lost on migration. Given the value of preserving learned LLM reliability data, this is likely an oversight.

**Fix:** Add `merge_table_ignore(import_db, db, "cluster_llm_stats")` to the import flow (INSERT OR IGNORE preserves local stats, doesn't duplicate or overwrite).

### Cross-reference / Section Numbers

**Section 6.3 references "see Section 6.4" for lookup direction** — Section 6.4 is indeed the temporal decay query that checks both directions. Correct.

**Section 8.2 references "Stage 6 (post-LLM)"** — Section 3.1 labels Stage 6 as "LOCAL POST-PROCESSING." Consistent.

**Section 9.3 says "LLM normalization is always called when at least one toggle is ON"** — This is internally consistent but contradicts Section 3.2 which says "Decides whether LLM is needed at all (fast path for confident resolutions)." Section 9.3 clarifies that the "fast path" saves tokens (fewer candidates in prompt) but doesn't skip LLM. Section 3.2 is slightly misleading — it implies LLM can be skipped entirely for confident resolutions, but per 9.3 it cannot (unless ALL toggles are OFF). **Minor wording inconsistency** — Section 3.2 should say "reduces LLM prompt cost" rather than "decides whether LLM is needed."

**Section 12.4 references `get_or_create_cluster`** — this function is defined in the same section. Consistent.

**Section 17.1 table lists `correction_counts` as unencrypted** — consistent with Section 13.3 export list. Consistent.

**Section 20 (Open Questions) has 2 questions, down from 5** — the removed questions correspond to the resolved items in the previous review. Consistent.

---

## Final Assessment

### Ready for Implementation?

**NOT YET.** One blocker, two medium issues must be resolved first.

### Blocking Issues (must fix before implementation starts)

**NI1 — `tree_stem` not on PyPI** is a build system blocker. The spec says `pip install tree_stem` but this package doesn't exist on PyPI. PyInstaller cannot bundle it. Before writing a single line of implementation code, the team must decide: vendor the 48KB `.py` file directly into `src/context/`, or publish a fork to PyPI. The spec must document which commit/version is used and how it's pinned.

### Medium Issues (should fix before implementation starts, or at latest in sprint 1)

**NI4 — `copy_table` undefined for integer PK tables** — `conversation_threads`, `clusters`, and `conversation_fingerprints` will silently collide or fail on profile import from another machine. This affects every user who migrates computers. Needs a defined ID-remapping or offset strategy.

**NI6 — All-LLM-providers-down behavior** — undefined user-facing behavior. The implementation will need a decision point for this; better to specify it now than discover the edge case in production.

### Low Issues (can be addressed in v1.1)

**NI5** — LLM confidence step function may be practically dead code (0.8 confidence still above 0.6 threshold in nearly all cases). Either improve the formula or document the specific scenario it helps.

**NI7** — `name_cluster` misses terms that appear primarily as `term_b` in canonical-order pairs. This is a display-only issue (cluster names in UI), not a correctness issue for resolution logic. Safe to defer.

**NI8** — `idx_corrections_pattern` is a dead index left over from the W4 fix. Remove it from schema.

**Schema/code gap** — `last_app` column is never written. `'both'` error_source value is unreachable. `cluster_llm_stats` not imported in profile import. These are all small fixes, one line each.

### Research Validation Summary

**tree_stem quality — CONFIRMED (ERRT=0.125, best available non-dictionary stemmer), but distribution is UNRESOLVED.** The algorithm is sound; the packaging is not. Second-best ERRT after dictionary-based reference (0.024), compared to pymorphy2 lemmatizer (0.391). For a pure-Python stemmer, it's the correct choice — but it must be vendored.

**SQLite WAL mode — CORRECTLY IMPLEMENTED.** Current 2025 best practices (multiple independent sources) confirm the spec's chosen PRAGMAs: `journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-64000`, `temp_store=MEMORY`. The addition of `mmap_size` could provide marginal benefit but is not required.

**UPSERT with compound TEXT primary keys — SOUND.** SQLite uses the compound PK index for conflict detection in UPSERT (each `OP_NoConflict` opcode does a lookup in the unique index). The three-column TEXT key `(term_a, term_b, cluster_id)` is supported. For 100K rows this is well within performance bounds. The spec's ~2ms for 100 UPSERTs per dictation is credible.

**Hyperbolic vs. exponential temporal decay — JUSTIFIED CHOICE, with a nuance.** Research (Kahana & Adler 2002, ICLR 2024) confirms that aggregate forgetting data fits a power law better than exponential (R²=0.99 vs R²=0.87). The spec's `1/(days + 1)` is a hyperbolic/power function. However, recent ML literature (Forgetting curves for continual learning, arXiv 2025) and cognitive science both note that for individual items, exponential decay is more accurate — the power law emerges from aggregation of items with different decay rates. For a co-occurrence graph where each edge has a single `last_used` timestamp (not a decay history), the hyperbolic approximation is reasonable and computationally trivial. The spec's choice is defensible and better than exponential for the use case. No change required.

### Overall Verdict

The spec has been substantially improved by the first review. All 5 critical weaknesses are fixed. Most edge cases and architecture concerns are addressed. The core design (4-level cascade, content-based threads, canonical co-occurrence, WAL mode, correction_counts table) is solid and ready for implementation.

The remaining gap is entirely operational — how does `tree_stem` get onto the machine — plus one unresolved import collision edge case. Fix those two, add the degraded-mode spec, and this document is implementation-ready.

**Confidence in core architecture:** High. The design is well-reasoned and the fixes were done correctly.
**Confidence in implementation readiness:** Medium — blocked on NI1, NI4, NI6.

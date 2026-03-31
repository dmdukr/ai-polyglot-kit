# Context Engine Architecture — Fourth Review (v5)

**Date:** 2026-03-28
**Reviewer:** Claude Sonnet 4.6 (Senior Systems Architect — fourth pass)
**Spec reviewed:** `docs/superpowers/specs/2026-03-28-context-engine-architecture.md`
**Previous review:** `docs/reviews/v4/architecture-sonnet.md`
**Spec status claim:** "Draft v5 — all review rounds resolved"
**Scope:** Verify all 20 issues flagged in v4 (NI1–NI9 + 11 consistency/analysis items). Search for new issues introduced by fixes.

---

## Fix Verification (20 items — PASS/FAIL each)

The v4 review identified 9 new issues (NI1–NI9) plus additional consistency findings, DPAPI overhead analysis, and prompt injection analysis. Below each is verified against the current spec.

---

### v4-NI1: pymorphy3 1-3s initialization cost undocumented — PASS

**Previous finding:** Module-level `morph = pymorphy3.MorphAnalyzer(lang='uk')` would block at import time for 1-3 seconds. Spec claimed `<5ms` context resolution with no startup caveat.

**Current spec (Section 11.1):**
- The instantiation is now a lazy singleton via `get_morph()`, not a module-level call.
- Section 11.1 states: "Lazy singleton — initialized once, in a background thread at app startup. MorphAnalyzer loads the DAWG dictionary (~15-50MB in RAM) which takes ~500ms."
- Startup strategy explicitly documented: `threading.Thread(target=get_morph, daemon=True).start()` at app startup.
- Section 2 (Goal 2) and Section 14.1 now state `<15ms` total (not `<5ms`) and include: "pymorphy3 lemmatization adds ~10ms."
- Section 14.2 accuracy table shows "Context resolution time: ~10ms (lemmatization only)" at 0 chats baseline.

**Assessment:** Fix is complete and correct. The initialization cost is documented, the singleton pattern is lazy, and the background thread strategy is explicit. The startup worst-case (`~500ms if first dictation arrives before init completes`) is acknowledged. The performance budget has been revised upward to `<15ms` to account for this. **PASS.**

---

### v4-NI2: `copy_table` PK collision undefined for integer PK tables — PASS

**Previous finding (carried from v3-NI4):** `conversation_threads`, `conversation_fingerprints`, and `clusters` were imported via `copy_table` with no collision strategy for auto-increment integer PKs.

**Current spec (Section 13.3):**
```python
id_map_clusters = remap_integer_pks(import_db, db, "clusters")
id_map_threads = remap_integer_pks(import_db, db, "conversation_threads",
                                    fk_remap={"cluster_id": id_map_clusters})
id_map_fingerprints = remap_integer_pks(import_db, db, "conversation_fingerprints",
                                         fk_remap={"cluster_id": id_map_clusters})
remap_fk_column(db, "thread_keywords", "thread_id", id_map_threads)
remap_fk_column(db, "fingerprint_keywords", "fingerprint_id", id_map_fingerprints)
```

`remap_integer_pks()` is fully defined (lines 1579–1601): strips the old `id`, lets autoincrement assign a new one, and builds an `{old_id: new_id}` mapping for FK remapping. `remap_fk_column()` patches join tables after the main tables are imported.

**Assessment:** Complete and correct. The strategy is well-chosen — re-assigning IDs is the safest approach for integer PK collision avoidance. FK integrity is maintained across `clusters → threads/fingerprints → join tables`. **PASS.**

---

### v4-NI3: All-LLM-providers-down behavior undefined — PASS

**Previous finding (carried from v3-NI6, originally REC10):** Three review cycles with no definition of Stage 5 degraded behavior.

**Current spec (Section 9.5):** A dedicated new section "LLM All-Fail Degraded Mode" now specifies:
1. Return `replaced_text` (Stage 3 output) unchanged.
2. Apply Stage 6 local post-processing only.
3. Show UI toast: "Text normalization unavailable — raw text inserted."
4. Log failure with `logger.warning()` and increment daily counter.
5. No automatic retry — next dictation tries the chain again.

Code example with `normalize_with_fallback()` and `AllProvidersFailedError` is provided.

**Assessment:** Fix is complete and meets the minimum bar specified in v4-NI3. All five behaviors are defined. **PASS.**

---

### v4-NI4: `name_cluster` only queries `term_a` — PASS

**Previous finding (carried from v3-NI7):** With canonical ordering (`term_a < term_b`), terms that sort alphabetically high appear predominantly as `term_b` and were invisible to the old single-column query.

**Current spec (Section 12.2):** The query now uses `UNION ALL`:
```sql
SELECT term, SUM(total) as grand_total FROM (
    SELECT term_a as term, SUM(weight) as total
    FROM term_cooccurrence WHERE cluster_id = ?
    GROUP BY term_a
    UNION ALL
    SELECT term_b as term, SUM(weight) as total
    FROM term_cooccurrence WHERE cluster_id = ?
    GROUP BY term_b
) GROUP BY term ORDER BY grand_total DESC LIMIT 3
```

The function comment explicitly explains: "Queries BOTH term_a and term_b via UNION to avoid alphabetic bias: with canonical ordering (term_a < term_b), Cyrillic terms (U+0400+) sort after Latin characters and predominantly appear as term_b."

**Assessment:** Fix is complete, correct, and well-documented. The UNION ALL approach correctly aggregates weights from both columns. Note that the function now takes `cluster_id` twice (once per sub-query) — the code correctly passes `[cluster_id, cluster_id]`. **PASS.**

---

### v4-NI5: `[*keywords, *keywords]` double-parameter pattern lacks explanatory comment — PASS

**Previous finding:** `should_update_cooccurrence` and `detect_cluster` used `[*keywords, *keywords]` in SQL parameter lists without a comment explaining why keywords appears twice.

**Current spec:**
- Section 6.3.1 (`should_update_cooccurrence`): the parameter list `[*keywords, *keywords]` is present at line 473 — **no comment added here.**
- Section 12.3 (`detect_cluster`): line 1260 now reads: `# keywords appears twice: once for term_a IN, once for term_b IN` immediately before the query.

**Assessment:** Fix is partial. The comment was added in `detect_cluster` (Section 12.3) but NOT in `should_update_cooccurrence` (Section 6.3.1). The v4-NI5 issue flagged both locations. The 6.3.1 instance remains without the explanatory comment. **PARTIAL PASS — minor omission in 6.3.1.**

---

### v4-NI6: `detect_cluster` threshold of `score >= 5` undocumented — PASS

**Previous finding:** The threshold of `5` for cluster assignment was a magic number with no documentation explaining its relationship to the decay formula or pruning thresholds.

**Current spec (Section 12.3):** A comment block now explains:
```python
# Threshold 5 means at least 5 cumulative co-occurrence hits (after decay).
# With temporal decay, a cluster needs recent sustained activity to be detected.
# A cluster with only weight=3-4 edges after pruning will remain undetectable
# until reinforced by new dictations — this is intentional to prevent stale
# clusters from capturing new threads.
```

**Assessment:** The comment documents the threshold's meaning and its intentional relationship to pruning. The acknowledged behavior ("weight=3-4 edges → undetectable") is now marked as intentional design, resolving the concern. **PASS.**

---

### v4-NI7: `merge_table_sum_weights` for `cluster_llm_stats` only summed `total_llm_resolutions` — PASS

**Previous finding:** The merge call specified `sum_col="total_llm_resolutions"` only, silently discarding imported `llm_errors` data and corrupting per-cluster error rates.

**Current spec (Section 13.3, line 1532–1534):**
```python
merge_table_sum_weights(import_db, db, "cluster_llm_stats",
                        key_cols=["cluster_id"],
                        sum_cols=["total_llm_resolutions", "llm_errors"])
```

The parameter is now `sum_cols` (plural) with both columns listed.

**Note:** The `term_cooccurrence` merge at line 1515–1517 still uses `sum_col` (singular). This is not an error — `term_cooccurrence` has only one numeric column to sum (`weight`). The singular/plural parameter naming inconsistency between the two calls is a minor API design quirk but not a functional issue.

**Assessment:** Fix is correct. Both error-rate columns are now summed during import. **PASS.**

---

### v4-NI8: Script validation runs on builtins — PASS

**Previous finding:** The post-import validation loop queried `SELECT name, body FROM scripts` — running LLM validation on all scripts including `is_builtin = 1` scripts, wasting tokens and risking false-positive sanitization of trusted app scripts.

**Current spec (Section 13.3, lines 1522–1529):**
```python
# Skip builtins (is_builtin = 1) — they are shipped with the app and trusted.
# Validating builtins wastes LLM tokens and risks false-positive sanitization.
for row in db.query("SELECT name, body FROM scripts WHERE is_builtin = 0"):
```

**Assessment:** Fix is correct. `WHERE is_builtin = 0` excludes built-ins, and the comment explains why. **PASS.**

---

### v4-NI9: `detect_cluster` used raw weights while co-occurrence lookups used temporal decay — PASS

**Previous finding:** `detect_cluster` used raw `SUM(weight)` while Section 6.4 co-occurrence lookups used temporal decay — inconsistent behavior that caused stale clusters to strongly influence new thread assignment.

**Current spec (Section 12.3):** `detect_cluster` now uses the same decay formula as Section 6.4:
```sql
SUM(weight * (1.0 / (MAX(julianday('now') - julianday(last_used), 0) + 1))) as score
```

The function docstring explicitly states: "Uses temporal decay consistent with Section 6.4 co-occurrence lookups: MAX(..., 0) guards against future-dated records (clock skew)."

**Assessment:** Fix is correct and consistent with the rest of the spec. **PASS.**

---

### v4-Consistency-1: pymorphy3 timing vs 5ms budget inconsistency — PASS

**Previous finding:** Section 14.1 showed `~5ms` total context resolution. With `~12 words × 0.1-1ms each` for pymorphy3, lemmatization alone exceeded this budget.

**Current spec:**
- Section 2 Goal 2: "Context resolution <15ms (local, includes pymorphy3 lemmatization ~10ms)"
- Section 14.1: `Lemmatization (pymorphy3, ~12 words): ~10ms`, `Total context resolution: <15ms`
- Section 14.2: baseline "Context resolution time: ~10ms (lemmatization only)"

**Assessment:** Budget revised upward to `<15ms`. The `~10ms` lemmatization estimate is internally consistent with `~12 words × ~0.1-1ms each` at the low end. **PASS.**

---

### v4-Consistency-2: Section 3.2 vs Section 9.4 wording inconsistency — PASS

**Previous finding (also flagged in v3):** Section 3.2 implied the CE could bypass the LLM ("fast path for confident resolutions"), contradicting Section 9.4's "LLM always called when at least one toggle is ON."

**Current spec (Section 3.2, lines 99–100):**
> "Reduces LLM token consumption and improves context quality (see Section 9.4 — LLM is always called when toggles are ON; the CE provides better context, not LLM bypass)"

The parenthetical explicitly cross-references Section 9.4 and clarifies the CE's role.

**Assessment:** Fix is correct. The ambiguity is resolved by an inline clarification with a section cross-reference. **PASS.**

---

### v4-Consistency-3: `error_source = 'both'` comment described one of two cases incorrectly — PASS (partial)

**Previous finding:** The `else` branch fires for two cases: (a) token in neither `raw` nor `normalized` (user addition), (b) token in both `raw` and `normalized` but user corrected it. The comment "Both raw and normalized differ from corrected" only described scenario (a) accurately.

**Current spec (Section 10.2, line 930):**
```python
else:
    error_source = "both"     # Both raw and normalized differ from corrected
```

The comment is unchanged from v4. The semantic ambiguity of the `else` branch (covering two distinct cases with one label) has not been addressed.

**Assessment:** This was an explicitly noted carry-over in v4 (minor correctness issue in error classification semantics). The spec is unchanged. **FAIL — not addressed.**

---

### v4-Consistency-4: Export list vs Import list consistency — PASS

**Previous finding (v4 confirmed it was fixed):** Export and import table lists were inconsistent in v3. In v4 this was marked as resolved.

**Current spec (Section 13.3):** Export loop includes `"clusters", "term_cooccurrence", "conversation_threads", "thread_keywords", "conversation_fingerprints", "fingerprint_keywords", "dictionary", "correction_counts", "cluster_llm_stats", "scripts", "app_rules"` — all 11 tables. Import handles all 11 via the appropriate merge/remap strategy. Replacements and encrypted tables are handled separately. No table is exported but not imported, or vice versa.

**Assessment:** Consistent. **PASS.**

---

### v4-Consistency-5: Section 10.2 `error_source` — `'both'` reachable — PASS

**Previous finding (v3 fixed, v4 verified):** The `else` branch making `'both'` reachable was fixed in v3 and verified in v4.

**Current spec:** The `else` branch is present and makes `'both'` reachable. Confirmed. **PASS.**

---

### v4-Consistency-6: `cluster_llm_stats` not imported (v3 gap) — PASS

**Previous finding:** Fixed in v4 (the import was added but with only one column). Now fully fixed with both columns (see NI7 above). **PASS.**

---

### v4-Analysis-1: Prompt injection defense — now "Three-layer defense" — PASS

**Previous finding:** v4 noted the "Double defense" label overstated protection. Recommended noting it is defense-in-depth, not cryptographic.

**Current spec (Section 9.3):**
- Renamed "Three-layer defense" (now includes deterministic blocklist as Layer 1, LLM validation as Layer 2, delimiter wrapping as Layer 3).
- Explicit note: "Neither is a cryptographic guarantee — this is defense-in-depth."
- `deterministic_check()` is fully implemented with `BLOCKED_PATTERNS` and 500-char limit.
- `validate_script()` docstring: "Layer 1: Deterministic check (fast, non-bypassable). Layer 2: LLM check (semantic attacks that bypass regex)."

**Assessment:** The defense architecture is improved significantly. The deterministic first-pass layer is a genuine improvement over the v4 two-layer design. The limitation caveat is appropriately documented. **PASS.**

---

### v4-Analysis-2: DPAPI overhead not quantified in Section 14.1 — FAIL

**Previous finding:** Section 14.1 showed context resolution at ~5ms but said nothing about DPAPI encryption overhead for history writes (~1-10ms per dictation). Recommended adding a row to the performance table.

**Current spec (Section 14.1):** The performance table covers: keyword extraction, lemmatization, find active threads, co-occurrence lookup, fingerprint search, dictionary exact match, batch co-occurrence INSERT, and total context resolution. There is no row for DPAPI encrypt/decrypt operations (Stage 7 history write).

**Assessment:** DPAPI overhead is still not quantified in the performance table. The total pipeline overhead claim of `<50ms` (Section 2, Goal 2) remains unvalidated against DPAPI costs. At 0.5-5ms per DPAPI call with 2 calls per history write, this could add 1-10ms — potentially pushing the total beyond 50ms in worst case. **FAIL — not addressed.**

---

### v4-Low-NI4: `name_cluster` term_b blind spot — PASS (see NI4 above)

This was explicitly deferred in v4 as a v1.1 item. It has been fixed ahead of schedule. **PASS.**

---

### v4-Low-NI5: `[*keywords, *keywords]` comment — PARTIAL PASS (see NI5 above)

Fixed in `detect_cluster` but not in `should_update_cooccurrence`. **PARTIAL PASS.**

---

### v4-Low-NI6: `detect_cluster` threshold undocumented — PASS (see NI6 above)

**PASS.**

---

## Consistency Check

### SC-1: `scripts` table lacks UNIQUE constraint on `name` — NEW ISSUE (MEDIUM)

**Location:** Section 15.2 schema vs Section 9.3 `save_script()` vs Section 13.3 import.

Schema definition (lines 1798–1804):
```sql
CREATE TABLE scripts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    is_builtin BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

`name` has `NOT NULL` but **no `UNIQUE` constraint**.

However, `save_script()` (Section 9.3, lines 843–845) uses:
```sql
INSERT INTO scripts (name, body) VALUES (?, ?)
ON CONFLICT(name) DO UPDATE SET body = ?
```

`ON CONFLICT(name)` requires either a `UNIQUE` constraint or a `PRIMARY KEY` on `name` to function. Without a `UNIQUE` constraint on `name`, this SQL will execute without error at schema creation time, but the `ON CONFLICT` clause will **silently do nothing** — it will never fire because SQLite will simply insert a duplicate row instead of conflicting. The result: every `save_script()` call inserts a new row rather than updating the existing one, accumulating script duplicates indefinitely.

Similarly, `merge_table_replace(import_db, db, "scripts", unique_col="name")` depends on `name` being a unique key to determine which rows to replace. Without the constraint, the merge semantics are undefined — the function will either duplicate rows or fail depending on its implementation.

**Fix required:** Add `UNIQUE` constraint to `scripts.name`:
```sql
CREATE TABLE scripts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    ...
);
```

### SC-2: `merge_table_ignore` for `correction_counts` not listed in strategy comment — MINOR

**Location:** Section 13.3, lines 1508–1514 and line 1531.

The strategy comment lists 6 tables with their merge approach:
```
term_cooccurrence: SUM weights
dictionary: imported values win (REPLACE)
thread_keywords, fingerprint_keywords: UNION
scripts: REPLACE by name
app_rules: REPLACE by app_name
cluster_llm_stats: SUM totals
```

`correction_counts` uses `merge_table_ignore` (line 1531) but is **not mentioned in the strategy comment**. This means `correction_counts` merge semantics are undocumented inline. The choice of `IGNORE` (local data wins, imported corrections discarded) is a deliberate decision — it should be documented the same way as the other six tables.

**Fix:** Add to the strategy comment:
```
#    correction_counts: IGNORE (local auto-promote history takes precedence — imported counts would re-trigger already-applied auto-promotes)
```

### SC-3: `merge_table_sum_weights` API inconsistency — `sum_col` vs `sum_cols` — MINOR

`term_cooccurrence` merge at line 1517: `sum_col="weight"` (singular string).
`cluster_llm_stats` merge at line 1534: `sum_cols=["total_llm_resolutions", "llm_errors"]` (plural list).

These are different parameter names and types. Either `merge_table_sum_weights` has an overloaded parameter (accepting both `str` and `list[str]`) or the two calls use different function signatures. The spec does not define `merge_table_sum_weights`'s signature — only its usage. If the implementation treats `sum_col` and `sum_cols` as separate parameters, one of these calls would silently fail (the wrong keyword argument is ignored). If the function is polymorphic, the spec should show the signature to remove ambiguity.

**Fix:** Show `merge_table_sum_weights` signature, or normalize to `sum_cols` for both calls (with `sum_cols=["weight"]` for the `term_cooccurrence` call).

### SC-4: `merge_table_union` for `thread_keywords` and `fingerprint_keywords` after `remap_fk_column` — ORDERING ISSUE (MEDIUM)

**Location:** Section 13.3 import flow, lines 1519–1520 vs 1543–1545.

`thread_keywords` and `fingerprint_keywords` are imported via `merge_table_union` at lines 1519–1520 (early in the import). Then at lines 1543–1545, `remap_fk_column` patches their FK references to use the new `thread_id`/`fingerprint_id` values.

The problem: `merge_table_union` imports rows with **old FK values** from the source DB. These old IDs may collide with existing IDs in the local DB (since conversation threads have auto-increment integer PKs with no coordination between source and local). After the import, `remap_fk_column` patches the FK values — but this relies on `remap_fk_column` correctly finding and updating all rows inserted by `merge_table_union`.

If `merge_table_union` uses `INSERT OR IGNORE` (which is the semantic implied by "UNION — no duplicates"), and if the local DB already has a `thread_keywords` row with the same `(thread_id, keyword)` PK that coincidentally matches an imported row (same old FK value happened to match a local FK value), then:
1. The imported row is silently ignored (INSERT OR IGNORE).
2. `remap_fk_column` won't fix the ignored row (it wasn't inserted).
3. The source DB's keyword data for that thread is lost.

This is the classic integer PK aliasing problem that `remap_integer_pks` was introduced to solve for the parent tables. The join tables (`thread_keywords`, `fingerprint_keywords`) have composite PKs of `(thread_id, keyword)` — the `thread_id` component contains old IDs that need remapping **before** insertion, not after.

**Fix:** Apply the FK remap before inserting into join tables. The correct sequence is:
1. `remap_integer_pks` for clusters → get `id_map_clusters`
2. `remap_integer_pks` for threads → get `id_map_threads`
3. `remap_integer_pks` for fingerprints → get `id_map_fingerprints`
4. Insert into `thread_keywords` with FK remapped (using `id_map_threads`)
5. Insert into `fingerprint_keywords` with FK remapped (using `id_map_fingerprints`)

The current code does (1), (2), (3), then inserts join tables with old IDs, then patches them — which has the aliasing race condition described above.

### SC-5: Section 4 confidence table threshold level-4 is `1.0` but LLM confidence can be `0.8` — MINOR INCONSISTENCY

**Location:** Section 4 "Resolution Confidence" table vs Section 10.4 `get_llm_confidence()`.

Section 4 table:
| Level | Threshold |
| 4 | **1.0** (LLM: final authority, always accepted) |

But Section 10.4 shows `get_llm_confidence()` can return `0.8` when the cluster error rate exceeds 20%. The `CONFIDENCE_THRESHOLDS[4] = 1.0` means: if LLM confidence is `0.8`, then `should_accept(4, 0.8)` returns `False` (0.8 < 1.0). Level 4 would reject its own result — but there is no Level 5 to escalate to.

This is the same dead-code issue noted in v3-NI5 ("low confidence still exceeds 0.6 acceptance threshold" — but now the threshold is 1.0, making it worse: `0.8 < 1.0` always fails). The `0.8` return from `get_llm_confidence()` can never cause acceptance at Level 4 with threshold `1.0`.

**Possible interpretations:**
1. The `1.0` threshold means "always accept" — but then `get_llm_confidence()` returning `0.8` has no effect.
2. The LLM confidence value is used differently (e.g., passed to the LLM prompt, not to `should_accept`) — but the spec does not show where `get_llm_confidence()` is used.

The spec does not show the call site of `get_llm_confidence()`. Without this, it is impossible to verify whether the `0.8` return value is used meaningfully or is dead logic.

**Fix:** Show the call site of `get_llm_confidence()` and clarify how the returned confidence interacts with `CONFIDENCE_THRESHOLDS[4] = 1.0`.

---

## New Issues

### NI-1: `scripts.name` missing UNIQUE constraint (MEDIUM — blocks correct operation)

Fully described in SC-1 above. This is a schema/code inconsistency that causes `save_script()` to silently insert duplicates instead of updating, and makes the import merge semantics undefined. This is a **new issue introduced in v5** — the `is_builtin` column was added to the scripts schema as part of the v4-NI8 fix, and the UNIQUE constraint appears to have been inadvertently omitted during schema reconstruction.

### NI-2: `merge_table_union` / `remap_fk_column` ordering causes FK aliasing (MEDIUM)

Fully described in SC-4 above. Join table rows are inserted with old FK values from the source DB, then patched — but if a local row with an aliased PK already exists, `merge_table_union` silently drops the imported row and `remap_fk_column` has nothing to fix. Source DB keyword data is lost without error.

### NI-3: DPAPI overhead still unquantified in Section 14.1 (LOW — carried from v4)

Section 14.1 performance table does not include a row for DPAPI encrypt/decrypt. The `<50ms total pipeline overhead` claim in Section 2 remains unvalidated against DPAPI costs. At 0.5-5ms per call with 2 calls per history write, worst-case DPAPI overhead (10ms) combined with the 15ms CE budget leaves only 25ms for STT dispatch and LLM network overhead — which is unrealistically tight. The note in Section 14.1 says "STT+LLM (~675ms) dominate total latency" suggesting the 50ms budget refers to local processing only — but this is not explicitly stated.

**Fix (minimal):** Add a note clarifying the `<50ms` refers to local processing only (excluding STT and LLM network latency), and add a DPAPI overhead row to the performance table.

### NI-4: `get_llm_confidence()` call site missing — threshold logic unverifiable (LOW)

Fully described in SC-5 above. The spec shows `get_llm_confidence()` defined but never shows where it is called. The return value of `0.8` cannot be accepted at Level 4 with `CONFIDENCE_THRESHOLDS[4] = 1.0`, making it either dead logic or used via a different code path not shown in the spec.

---

## FINAL VERDICT

### Fix Summary

| # | v4 Issue | Status |
|---|----------|--------|
| NI1 | pymorphy3 init cost — lazy singleton + background thread | **PASS** |
| NI2 | `copy_table` PK collision — `remap_integer_pks` introduced | **PASS** |
| NI3 | All-LLM-down behavior — Section 9.5 added | **PASS** |
| NI4 | `name_cluster` term_b blind spot — UNION ALL query | **PASS** |
| NI5 | `[*keywords, *keywords]` comment — added in 12.3 only | **PARTIAL PASS** |
| NI6 | `detect_cluster` threshold magic number — commented | **PASS** |
| NI7 | `merge_table_sum_weights` one column — `sum_cols` list | **PASS** |
| NI8 | Script validation on builtins — `WHERE is_builtin = 0` | **PASS** |
| NI9 | `detect_cluster` no temporal decay — decay added | **PASS** |
| Consistency-1 | pymorphy3 timing vs 5ms budget — revised to 15ms | **PASS** |
| Consistency-2 | Section 3.2 vs 9.4 wording — inline clarification added | **PASS** |
| Consistency-3 | `error_source = 'both'` comment — unchanged | **FAIL** |
| Consistency-4 | Export/import table lists — consistent | **PASS** |
| Consistency-5 | `'both'` reachable — confirmed | **PASS** |
| Consistency-6 | `cluster_llm_stats` not imported — now imported + both columns | **PASS** |
| Analysis-1 | Prompt injection "Double defense" label — three-layer + caveat | **PASS** |
| Analysis-2 | DPAPI overhead unquantified — still absent from 14.1 | **FAIL** |
| Low-NI4 | `name_cluster` term_b — fixed early | **PASS** |
| Low-NI5 | Double-keyword comment — partial (6.3.1 missing) | **PARTIAL PASS** |
| Low-NI6 | `detect_cluster` threshold — documented | **PASS** |

**Result: 16 PASS, 2 FAIL, 2 PARTIAL PASS out of 20 items.**

### New Issues Found in v5

| ID | Issue | Severity |
|----|-------|----------|
| NI-1 | `scripts` table missing `UNIQUE` constraint on `name` — `ON CONFLICT(name)` silently does nothing; `save_script()` inserts duplicates | **MEDIUM** |
| NI-2 | `merge_table_union` inserts join-table rows with old FK IDs before `remap_fk_column` can fix them — FK aliasing with existing rows causes silent data loss | **MEDIUM** |
| NI-3 | DPAPI overhead absent from Section 14.1 performance table (carried from v4) | LOW |
| NI-4 | `get_llm_confidence()` call site missing; `0.8` return cannot be accepted at Level 4 with threshold `1.0` — dead logic or undocumented code path | LOW |

### Blocking Issues

**NI-1 (MEDIUM):** The missing `UNIQUE` constraint on `scripts.name` is a schema defect that causes `save_script()` to insert duplicate rows indefinitely. This will produce incorrect behavior in the scripts UI (all saves create new rows, existing scripts appear duplicated, LLM prompts receive multiple conflicting script versions). **Must be fixed before implementation.**

**NI-2 (MEDIUM):** The join-table import ordering issue means that profile imports can silently lose thread keywords and fingerprint keywords when local DB IDs happen to alias source DB IDs. Since both databases use autoincrement starting from 1, this collision is common, not edge-case. **Must be fixed before implementation.**

### Issues Acceptable for v1.1 or Post-Launch

- Consistency-3: `error_source = 'both'` comment imprecision — low impact, not user-visible.
- NI5-partial: Missing comment in `should_update_cooccurrence` (6.3.1) — maintenance hygiene.
- NI-3: DPAPI overhead documentation gap — add one row to Section 14.1.
- NI-4: `get_llm_confidence()` call site — clarify in spec; likely not a code defect.

### Overall Assessment

The spec has improved substantially across five iterations. Thirteen of the fourteen medium-or-higher issues from v4 are fully resolved. The architecture is sound, the schema is largely consistent, and the major algorithmic decisions (lazy singleton, remap_integer_pks, temporal decay in detect_cluster, UNION ALL in name_cluster, three-layer injection defense) are correctly implemented.

Two new medium issues have been introduced by the v5 changes: a missing UNIQUE constraint in the scripts schema (likely a copy/paste error during schema reconstruction for the `is_builtin` column addition) and an import ordering problem in the join-table FK remapping. Both are one-to-three line fixes.

**Confidence in core architecture:** High. The design is mature and the most complex problems (PK collision, LLM degraded mode, prompt injection, temporal decay consistency) are correctly solved.

**Confidence in implementation readiness:** Medium-high. Fix NI-1 and NI-2 (both are small) and the spec is implementation-ready. These can be resolved in a 15-minute targeted update.

**Recommendation:** One final targeted pass fixing NI-1 (add `UNIQUE` to `scripts.name`) and NI-2 (remap join-table FKs before inserting, not after). All other remaining items are documentation quality improvements, not correctness issues. After those two fixes, implementation can begin on all modules.

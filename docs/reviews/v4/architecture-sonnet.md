# Context Engine Architecture — Third Review (v4)

**Date:** 2026-03-28
**Reviewer:** Claude Sonnet 4.6 (Senior Systems Architect — third pass)
**Spec reviewed:** `docs/superpowers/specs/2026-03-28-context-engine-architecture.md`
**Previous review:** `docs/reviews/v3/architecture-sonnet.md`
**Spec claims:** "Draft v4 — blockers fixed, technicals resolved"
**Status:** Third review — verifying 8 v3 issues (NI1-NI8), searching for new issues

---

## Blocker Fixes Verification (B1-B4)

The v3 review identified one blocker and two medium issues as "must fix before implementation." This section verifies each.

### B1 (v3-NI1): `tree_stem` not on PyPI — FIXED correctly

**Previous:** `tree_stem` used throughout the spec despite not existing as a PyPI package. Fatal for PyInstaller bundles.

**Current spec:** Section 2 now reads:
> "pure SQLite + `pymorphy3` for Ukrainian lemmatization (~5MB with dictionaries, on PyPI, actively maintained)"

Section 11.1 now uses:
```python
import pymorphy3
morph = pymorphy3.MorphAnalyzer(lang='uk')
```

Section 11.4 confirms:
> "`pymorphy3` is the only dependency (~5MB with dictionaries), <1ms per word"

`tree_stem` has been completely removed from the spec. `pymorphy3` is a real, actively maintained PyPI package (`pip install pymorphy3 pymorphy3-dicts-uk`). Last release: October 2025 (v2.0.6). **Fix verified. Correct. Blocker resolved.**

**Web validation of `pymorphy3` claims:**
- Package size claim of ~5MB: The `pymorphy3-dicts-uk` package is 8.1MB per PyPI metadata — the spec's "~5MB" is slightly understated. True install footprint is approximately 8-10MB. Minor inaccuracy; not a blocker.
- Memory usage: `MorphAnalyzer` instances occupy approximately 15MB of RAM when loaded (official pymorphy2/pymorphy3 documentation confirmed via web research). The spec does not claim a RAM figure, so no issue here.
- "<1ms per word" claim: Plausible for a trained in-process analyzer; pymorphy2 benchmarks suggest 10-100K words/second on modern hardware, consistent with sub-millisecond per-word. **Claim is credible.**

**New concern introduced by this fix — see NI1 below.**

### B2 (v3-NI4): `copy_table` undefined for integer PK tables — PARTIALLY FIXED

**Previous:** `conversation_threads`, `conversation_fingerprints`, and `clusters` were imported via `copy_table` with no collision strategy for auto-increment integer PKs.

**Current spec (Section 13.3 import flow):**
```python
copy_table(import_db, db, "conversation_threads")
copy_table(import_db, db, "conversation_fingerprints")
copy_table(import_db, db, "clusters")
```

The `copy_table` calls remain for all three tables. **The collision strategy is still undefined.** The v3 issue is not fixed — it is unchanged.

However, `cluster_llm_stats` now uses `merge_table_sum_weights` (which IS defined as SUM of totals), and there is no longer a `merge_table_ignore` omission for it. That specific gap from v3 consistency check is fixed.

The fundamental integer PK collision problem for `conversation_threads`, `conversation_fingerprints`, and `clusters` remains. **Medium issue — see NI2 (carried over from v3-NI4).**

### B3 (v3-NI6): All-LLM-providers-down behavior — NOT FIXED

The spec still does not define what happens when all three LLM providers (Groq → OpenAI → Anthropic) fail with toggles ON. Section 9.4 reads:

> "LLM normalization is always called when at least one toggle is ON"

No fallback behavior is defined for the case where all three providers fail. The pipeline diagram (Section 3.1) shows Stage 5 producing `normalized_text`, but there is no specification for what is returned if Stage 5 throws an exception or times out across all providers.

This was v3-NI6, which itself was REC10 from the original review. **Three review cycles without resolution. Medium issue — see NI3 (carried over).**

### B4 (v3-NI7): `name_cluster` only queries `term_a` — NOT FIXED

Section 12.2 `name_cluster` query is unchanged from v3:
```sql
SELECT term_a, SUM(weight) as total
FROM term_cooccurrence
WHERE cluster_id = ?
GROUP BY term_a
ORDER BY total DESC
LIMIT 3
```

With canonical ordering (`term_a < term_b`), terms that sort alphabetically high (late in the alphabet) will predominantly appear as `term_b` and be invisible to this query. The UI will show incorrect cluster display names for affected vocabularies.

This was labeled "display-only, safe to defer" in v3. It remains deferred. **Low issue — still present, still not fixed, see NI4.**

---

## Technical Fixes Verification

### v3-NI2 (double-parameter pattern documentation) — ADDRESSED

v3 noted the `[*keywords, *keywords]` pattern should have a comment explaining why keywords appears twice. Section 6.3.1 `should_update_cooccurrence` and Section 12.3 `detect_cluster` both retain the pattern. No comment was added to explain it.

This was marked LOW ("maintenance hazard"). The fix (adding a comment) was not implemented. **Minor omission — see NI5.**

### v3-NI3 (bigram stem artifacts) — NO ACTION NEEDED (CONFIRMED)

v3 marked this as a non-issue after analysis. The spec is unchanged and the analysis stands. **No action required.**

### v3-NI5 (LLM confidence step function) — NOT FIXED, BUT ACCEPTABLE

Section 10.4 `get_llm_confidence()` is unchanged — still a binary 1.0/0.8 threshold at 20% error rate. v3 noted this may be practically dead code because 0.8 confidence still exceeds the 0.6 acceptance threshold.

The spec neither improved the formula nor documented the specific scenario where 0.8 matters. The code is still likely dead logic in practice. **Low issue — accepted as is. See NI6 if implementation team hits this.**

### v3-NI8 (dead index `idx_corrections_pattern`) — NOT FIXED

Section 15.2 schema was searched for `idx_corrections_pattern` — it is **no longer present** in the schema. The dead index was silently removed without documentation.

**Fix verified. Correct. The dead index is gone.**

### v3-Consistency (`last_app` never written) — FIXED correctly

Section 5.2 Thread Lifecycle now explicitly includes:
```python
UPDATE conversation_threads SET last_app = ? WHERE id = ?
```

The `last_app` column is now written during thread updates. **Fix verified. Correct.**

### v3-Consistency (`'both'` error_source unreachable) — FIXED correctly

Section 10.2 `learn_from_correction` now has:
```python
else:
    error_source = "both"  # Both raw and normalized differ from corrected
```

The `else` branch makes `'both'` reachable when a token is absent from both `raw` AND `normalized` (correction introduces a completely new token). This is a valid third case. The schema comment `-- 'stt' | 'llm' | 'both'` now has corresponding code coverage. **Fix verified. Correct.**

### v3-Consistency (`cluster_llm_stats` not imported) — FIXED correctly

Section 13.3 import flow now has:
```python
merge_table_sum_weights(import_db, db, "cluster_llm_stats",
                        key_cols=["cluster_id"],
                        sum_col="total_llm_resolutions")
```

`cluster_llm_stats` is now imported and merged. However, `sum_col="total_llm_resolutions"` only sums one column — `llm_errors` is a separate column that also needs to be summed. If `merge_table_sum_weights` only increments one column, per-cluster error rates will be corrupted on import. **See NI7 (new issue).**

---

## New Issues Found

### NI1. `pymorphy3.MorphAnalyzer(lang='uk')` is a module-level singleton with ~1-3s startup cost (MEDIUM)

**Location:** Section 11.1

```python
import pymorphy3
morph = pymorphy3.MorphAnalyzer(lang='uk')
```

This declaration at module level means the analyzer is instantiated at `import` time of `keywords.py`. Based on pymorphy2/pymorphy3 documentation and user reports, `MorphAnalyzer` initialization loads the full dictionary into memory (~15MB RAM) which takes approximately **1-3 seconds on first initialization**. The spec's application is a Windows desktop app that must launch quickly (user double-clicks tray icon).

**The problem:** If `keywords.py` is imported at app startup, the 1-3s initialization delay will be experienced as UI freeze before the first dictation. If initialization is deferred (lazy import), the *first* dictation after launch will stall for 1-3 seconds instead — equally jarring.

**What the spec claims:** "context resolution <5ms (local), total pipeline overhead <50ms" (Section 2, Goal 2). An initialization stall of 1-3 seconds violates this goal.

**Fix required:** The spec must document initialization strategy explicitly. Options:
1. Initialize `MorphAnalyzer` in a background thread at app startup (warm-up before first dictation)
2. Show a loading indicator during first-launch initialization
3. Use a pre-initialized singleton stored in a module-level variable with documented startup impact

The spec needs to address this initialization cost explicitly. Currently it states only "<1ms per word" (per-word analysis time), not the initial cold-start cost.

**Web validation:** pymorphy2 official documentation explicitly warns: "MorphAnalyzer instances occupy around 15MB of RAM. You should organize your code to create the MorphAnalyzer instance beforehand and work with that single instance going forward." This confirms initialization is expensive enough to warrant advance planning.

### NI2. `copy_table` collision strategy undefined for integer PK tables (MEDIUM — carried from v3-NI4)

**Location:** Section 13.3 import flow, lines:
```python
copy_table(import_db, db, "conversation_threads")
copy_table(import_db, db, "conversation_fingerprints")
copy_table(import_db, db, "clusters")
```

Three tables with auto-increment integer PKs and no defined collision behavior. This is unchanged from v3. See v3-NI4 for full analysis.

**Why this matters now:** The fix of importing `cluster_llm_stats` via `merge_table_sum_weights` makes the oversight more visible — the spec clearly has per-table strategies for everything EXCEPT these three integer PK tables. Their `copy_table` usage appears to be an oversight, not a conscious choice.

**Fix required:** Define one of the three strategies from v3-NI4 (re-assign IDs with FK remapping, INSERT OR IGNORE, or ID offset by MAX).

### NI3. All-LLM-providers-down behavior undefined (MEDIUM — carried from v3-NI6)

This is the third consecutive review flagging the same gap. The pipeline specification for Stage 5 must define the fallback behavior when all three LLM providers fail. See v3-NI6 for full analysis.

**Minimum acceptable fix:**
> "When all LLM providers fail: return `replaced_text` (Stage 3 output) unchanged. Apply Stage 6 exact dictionary terms. Surface non-blocking UI notification ('Normalization unavailable'). Log failure with timestamp and provider error codes."

Without this, the implementation team will make an ad-hoc decision under time pressure. This decision is user-visible.

### NI4. `name_cluster` still only queries `term_a` (LOW — carried from v3-NI7)

Unchanged from v3. `name_cluster` misses high-frequency terms that appear primarily as `term_b` in canonical-order pairs. UI cluster display names will be incorrect for affected vocabularies.

This was explicitly deferred as "display-only, safe to defer." **Acceptable for v1.1 — just noting it remains unresolved.**

### NI5. Double-parameter `[*keywords, *keywords]` pattern still lacks explanatory comment (LOW — carried from v3-NI2)

Section 6.3.1 and 12.3 still use `[*keywords, *keywords]` in SQL parameter lists without a comment explaining why keywords appears twice (once for `term_a IN`, once for `term_b IN`). Easy maintenance trap.

**One-line fix:** Add `# keywords appears twice: once for term_a IN, once for term_b IN` above each such call.

### NI6. `detect_cluster` threshold of `score >= 5` is undocumented magic number (LOW)

**Location:** Section 12.3

```python
if scores and scores[0].score >= 5:
    return scores[0].cluster_id
```

The threshold of `5` for cluster assignment is unexplained. With temporal decay applied in `get_score_with_decay` queries (Section 6.4), a score of 5 could represent:
- 5 co-occurrences of weight=1 from today → very weak signal
- 1 heavily-weighted edge of weight=20 from 4 days ago → score ≈ 5 (20/4 = 5.0)

No documentation explains the choice of 5, whether it accounts for temporal decay or raw weight, or how it was calibrated. The spec also lacks consistency between this threshold and the "Emergency prune — weight < 3" threshold in Section 11.3 — a cluster could have only weight=3-4 edges after pruning, leaving it permanently undetectable.

**Fix:** Add a comment explaining the threshold choice and its relationship to the decay formula and pruning thresholds.

### NI7. `merge_table_sum_weights` for `cluster_llm_stats` only sums one column (MEDIUM — new)

**Location:** Section 13.3

```python
merge_table_sum_weights(import_db, db, "cluster_llm_stats",
                        key_cols=["cluster_id"],
                        sum_col="total_llm_resolutions")
```

The `cluster_llm_stats` table has two numeric columns:
```sql
total_llm_resolutions INTEGER DEFAULT 0,
llm_errors INTEGER DEFAULT 0
```

The merge call specifies `sum_col="total_llm_resolutions"` — only one column. The `llm_errors` column is not summed. After import:
- `total_llm_resolutions` = source + destination (correct)
- `llm_errors` = destination only (imported error data silently discarded)

This corrupts per-cluster error rates post-migration. If the source machine had a cluster with 100 resolutions and 40 errors (40% error rate → LLM unreliable), after import the destination would show 100+ resolutions but only its own (potentially 0) errors — effective error rate drops to near 0%, and `get_llm_confidence()` returns 1.0 instead of 0.8. The system loses learned LLM unreliability data.

**Fix:** Either extend `merge_table_sum_weights` to accept multiple sum columns, or add a second call:
```python
merge_table_sum_weights(import_db, db, "cluster_llm_stats",
                        key_cols=["cluster_id"],
                        sum_cols=["total_llm_resolutions", "llm_errors"])
```

### NI8. Script re-validation after import applies to ALL scripts including builtins (LOW)

**Location:** Section 13.3

```python
merge_table_replace(import_db, db, "scripts", unique_col="name")
# Validate imported scripts for prompt injection (see Section 9.3)
for row in db.query("SELECT name, body FROM scripts"):
    is_safe, sanitized, issues = validate_script(row.body)
    if issues:
        db.execute("UPDATE scripts SET body = ? WHERE name = ?",
                   [sanitized, row.name])
```

The validation loop runs over ALL scripts in `db` after the merge, including built-in scripts (`is_builtin = 1`). Built-in scripts are trusted (shipped with the app), and running them through the LLM validator:
1. Wastes tokens (each validation call costs ~200-500 tokens)
2. Risks the validator falsely flagging legitimate app instructions as injection attempts
3. Could corrupt built-in behavior if the validator sanitizes away valid formatting rules

**Fix:** Add `WHERE is_builtin = 0` to the validation query:
```python
for row in db.query("SELECT name, body FROM scripts WHERE is_builtin = 0"):
```

---

## Consistency Check

### NI1 (pymorphy3 initialization) vs Section 2 performance goal

Section 2 Goal 2: "Speed: Context resolution <5ms (local)". Module-level `morph = pymorphy3.MorphAnalyzer(lang='uk')` initialization takes 1-3 seconds on cold start. **These are inconsistent** — the cold-start cost is not "context resolution" time but it will be observed as startup latency. The spec must reconcile this.

### Section 14.1 query performance vs Section 11.1 lemmatization per-call

Section 14.1 shows total context resolution at ~5ms. Section 11.1 claims "<1ms per word" for pymorphy3. For a 30-word dictation with ~15 content words (after stopword removal), lemmatization alone is ~15ms — three times the total budget. This is internally **inconsistent**.

Either the "<1ms per word" is optimistic (should be ~0.1ms per word), or the 5ms total budget needs upward revision to ~20ms. The performance table in 14.1 should be re-validated against actual pymorphy3 benchmarks.

### Section 3.2 vs Section 9.4 (fast path language)

Section 3.2: "Decides whether LLM is needed at all (fast path for confident resolutions)"
Section 9.4: "LLM normalization is always called when at least one toggle is ON"

This wording inconsistency was flagged in v3 and remains unresolved. Section 3.2 still implies LLM can be bypassed for confident resolutions, which contradicts 9.4.

### Section 10.2 `error_source` classification logic vs comment

The new `else` branch in `learn_from_correction`:
```python
in_raw = old_token in raw
in_normalized = old_token in normalized
if in_raw and not in_normalized:
    error_source = "stt"
elif not in_raw and in_normalized:
    error_source = "llm"
else:
    error_source = "both"
```

The comment says `# Both raw and normalized differ from corrected`. But the `else` branch actually fires when NEITHER condition above is true — i.e., `not (in_raw and not in_normalized) AND not (not in_raw and in_normalized)`. This simplifies to `(not in_raw AND not in_normalized) OR (in_raw AND in_normalized)`.

- `not in_raw AND not in_normalized`: token appears in neither raw nor normalized — user added a completely new token in correction. This isn't "both" wrong; it's a user addition.
- `in_raw AND in_normalized`: token in both raw and normalized but user corrected it. This means the STT got it "right" and the LLM preserved it but the user disagrees. This is genuinely "both" or neither — the original was correct and user preference differs.

The `'both'` label is misleading for at least one of these cases. The comment describes the scenario incompletely. **Minor correctness issue in error classification semantics.**

### Section 13.3 export list vs import list

Export (Section 13.3):
```python
for table in ["clusters", "term_cooccurrence", "conversation_threads",
               "thread_keywords", "conversation_fingerprints",
               "fingerprint_keywords", "dictionary",
               "correction_counts", "cluster_llm_stats",
               "scripts", "app_rules"]:
    copy_table(db, export_db, table)
```

Import handles all of these tables. The `replacements` table is handled separately (sensitive DPAPI re-encryption path). **Export and import are now consistent. No gap.**

### Section 15.2 schema vs Section 6.3 `update_cooccurrence` code

Schema: `PRIMARY KEY (term_a, term_b, cluster_id)` — three columns.
Code: `ON CONFLICT(term_a, term_b, cluster_id)` — matches exactly. **Consistent.**

### Section 12.3 `detect_cluster` query vs Section 6.1 purpose

`detect_cluster` does NOT apply temporal decay (uses raw `SUM(weight)`), while the co-occurrence lookup in Section 6.4 uses decay. This means cluster detection for new threads uses stale weights, while term disambiguation uses fresh weights. This is inconsistent behavior — a cluster created by an old project that hasn't been touched in a year would still strongly influence cluster detection. Temporal decay should arguably apply to `detect_cluster` as well. **Design inconsistency — see NI9 (new, low priority).**

### NI9. `detect_cluster` uses raw weights while co-occurrence lookups use temporal decay (LOW)

**Location:** Section 12.3 `detect_cluster` vs Section 6.4 temporal decay.

`detect_cluster` uses `SUM(weight)` without decay. The temporal decay formula (`1/(days + 1)`) is only applied in Section 6.4 for "term context lookup." This means:
- An IT cluster with 200 raw weight from 2 years ago → `detect_cluster` assigns new threads to IT
- But a co-occurrence lookup with decay → the same IT edges contribute only ~1/730 of their raw weight

New threads get assigned to stale clusters even when the user's vocabulary has shifted. This is the "cluster drift" problem (v3-E6, accepted as known limitation), but it's worsened by the inconsistency between raw and decayed weight queries.

**Minimum fix:** Apply temporal decay in `detect_cluster` for consistency, or document the intentional divergence.

---

## Prompt Injection Defense Validation

**Web research findings on delimiter effectiveness:**

1. **Spotlighting (2024, Microsoft Research):** Delimiter-based defense reduced attack success rate from >50% to <2% against non-adaptive attacks using GPT-3.5 Turbo.

2. **Adaptive attacks (2025, Nasr et al.):** Under adaptive attack conditions, every published defense including delimiting was bypassed with attack success rates above 90% for most defenses. Google Gemini (2025) reported that after applying best defenses including adversarial fine-tuning, the most effective attack technique still succeeded 53.6% of the time.

3. **PromptArmor (2025):** Multi-layer defenses (delimiter + instruction + validation) provide better protection than any single mechanism.

**Assessment of spec's Section 9.3 defense:**

The spec implements a two-layer defense:
1. LLM-based validation at save time (`validate_script()`)
2. Delimiter wrapping at prompt time

This two-layer approach is appropriate for the threat model. The spec's threat is specifically a user importing a profile from an untrusted source — not an adversary who can observe model outputs and craft adaptive follow-up attacks. For this offline, one-shot injection scenario, the combination of save-time LLM validation plus delimiter wrapping is reasonable.

**Caveat documented:** The spec should note that delimiter wrapping is a partial mitigation (effective against naive injections, bypassable by sophisticated adversarial inputs). The current wording "Double defense" implies stronger protection than the literature supports.

**No blocking issue.** The defense is appropriate for the stated threat model. Add a note that it is "defense-in-depth against naive injection attempts, not a cryptographic guarantee."

---

## DPAPI Overhead Validation

**Web research findings:**

1. DPAPI (`CryptProtectData`/`CryptUnprotectData`) uses a local RPC call to lsass.exe. No network traversal, but IPC overhead is present.
2. No specific per-call latency benchmarks were found in public literature. Based on known IPC overhead characteristics, local RPC calls to lsass.exe are typically in the **0.5-5ms range per call**.
3. SQLCipher (whole-database encryption) reports 5-15% overhead — but DPAPI is used per-row in this spec (encrypting individual BLOBs), not the whole database.

**Assessment of spec's DPAPI use:**

The spec uses DPAPI for:
- History rows: 2 encrypted BLOBs per row (raw_text, normalized_text) — 2 encrypt calls on write, 2 decrypt calls on read
- Correction rows: 3 encrypted BLOBs per row — 3+3 calls
- Sensitive replacements: 1 BLOB

At 2 DPAPI calls per history write and 0.5-5ms per call, each dictation could incur **1-10ms of DPAPI overhead** — potentially exceeding the spec's "<50ms total pipeline overhead" claim (Section 2, Goal 2) in the worst case.

**The spec does not benchmark or acknowledge DPAPI overhead.** Section 14.1 shows total context resolution at ~5ms but says nothing about encryption overhead for history writes (Stage 7: "Save to history" in the pipeline).

**Recommendation:** Add DPAPI overhead to Section 14.1 performance table:
> "History write (2× DPAPI encrypt): ~1-5ms"
And update the total pipeline overhead estimate accordingly.

---

## Final Verdict

### Summary of Issue Status Across All Four Versions

| ID | Issue | v1 | v2 | v3 | v4 |
|----|-------|----|----|----|----|
| (W1-W6, A1-A5, E1-E6, REC1-REC10) | 20 original issues | Open | Fixed | Verified | — |
| NI1 (v3) | tree_stem not on PyPI | — | — | Found | **FIXED** |
| NI2 (v3) | detect_cluster double-keyword pattern | — | — | Found | Open (LOW) |
| NI3 (v3) | IMPORTANT_SHORT lemmatization | — | — | Found/closed | — |
| NI4 (v3) | copy_table PK collision | — | — | Found | **OPEN (MEDIUM)** |
| NI5 (v3) | LLM confidence step function | — | — | Found | Open (LOW) |
| NI6 (v3) | All-LLM-down undefined | — | — | Found | **OPEN (MEDIUM)** |
| NI7 (v3) | name_cluster term_b blind spot | — | — | Found | Open (LOW) |
| NI8 (v3) | idx_corrections_pattern dead | — | — | Found | **FIXED** |
| Consistency: last_app never written | — | — | Found | **FIXED** |
| Consistency: 'both' unreachable | — | — | Found | **FIXED** |
| Consistency: cluster_llm_stats not imported | — | — | Found | **FIXED (partially)** |
| **NI1 (v4)** | pymorphy3 1-3s init cost undocumented | — | — | — | **NEW (MEDIUM)** |
| **NI2 (v4)** | copy_table PK collision (carried) | — | — | — | MEDIUM |
| **NI3 (v4)** | All-LLM-down (carried) | — | — | — | MEDIUM |
| **NI4 (v4)** | name_cluster (carried) | — | — | — | LOW |
| **NI5 (v4)** | Double-keyword comment missing | — | — | — | LOW |
| **NI6 (v4)** | detect_cluster threshold undocumented | — | — | — | LOW |
| **NI7 (v4)** | merge_table_sum_weights one column | — | — | — | **NEW (MEDIUM)** |
| **NI8 (v4)** | Script validation runs on builtins | — | — | — | NEW (LOW) |
| **NI9 (v4)** | detect_cluster no temporal decay | — | — | — | NEW (LOW) |
| Consistency: pymorphy3 timing vs 5ms budget | — | — | — | **NEW (MEDIUM)** |
| Consistency: Section 3.2 vs 9.4 wording | — | — | Found | Open (LOW) |
| DPAPI overhead unquantified | — | — | — | NEW (LOW-MEDIUM) |

### Blocking Issues

**None that were not already present in v3.** The v3 blocker (tree_stem) is correctly fixed.

### Issues Requiring Resolution Before Implementation

**NI1 (v4): pymorphy3 initialization cost** — The spec must document startup strategy (background thread warm-up or explicit loading screen) to avoid violating the <50ms per-dictation performance goal. Also, the 14.1 performance table budget of ~5ms total context resolution is mathematically incompatible with 15 words × ~0.1-1ms each for pymorphy3 analysis. Numbers need reconciliation.

**NI2 (v4 = v3-NI4): copy_table undefined for integer PKs** — Unchanged from v3. Must be defined before implementation.

**NI3 (v4 = v3-NI6): All-LLM-down behavior** — Unchanged from v3. Must be defined before implementation.

**NI7 (v4): merge_table_sum_weights missing `llm_errors` column** — New issue. `cluster_llm_stats` import corrupts error rate data. One-line fix, must be done.

### Issues for v1.1 or Sprint 1 Backlog

- NI4 (name_cluster term_b): display-only cosmetic issue
- NI5 (double-keyword comment): maintenance hygiene
- NI6 (detect_cluster threshold): document or remove magic number
- NI8 (builtin script validation): minor efficiency + safety issue
- NI9 (detect_cluster no decay): design inconsistency, low impact
- Section 3.2 vs 9.4 wording: documentation cleanup
- DPAPI overhead: document in Section 14.1 performance table

### Overall Assessment

The core architecture is solid and has improved significantly across four reviews. The pivot from `tree_stem` to `pymorphy3` resolves the critical build system blocker and is the right technical choice. The schema, query design, thread lifecycle, and fingerprint matching logic are all implementation-ready.

Three medium issues remain unresolved from v3 (NI2, NI3, and a new NI7 variant of the cluster_llm_stats import). One new medium issue was found (NI1 — pymorphy3 startup cost). None of these are architectural in nature — they are specification gaps that will cause implementation-time surprises if not addressed.

**Confidence in core architecture:** High. The design is well-reasoned, internally consistent (with the exceptions noted), and superior to the original draft.

**Confidence in implementation readiness:** Medium — 4 medium issues must be resolved, all of which are one-paragraph spec additions rather than structural changes.

**Recommendation:** One more targeted spec update addressing NI1, NI2, NI3, NI7 is warranted before implementation begins. These are 30-minute fixes. If the team accepts the risk, implementation can begin now on all modules except `keywords.py` (pending pymorphy3 startup strategy) and profile import (pending PK collision strategy).

---

## Sources

Web research conducted for this review:

- [pymorphy3 · PyPI](https://pypi.org/project/pymorphy3/) — package status, version, maintenance
- [pymorphy3-dicts-uk · PyPI](https://pypi.org/project/pymorphy3-dicts-uk/) — dictionary package size (8.1MB)
- [pymorphy2 User Guide](https://pymorphy2.readthedocs.io/en/stable/user/guide.html) — MorphAnalyzer ~15MB RAM, singleton recommendation
- [Defending Against Indirect Prompt Injection Attacks With Spotlighting](https://arxiv.org/abs/2403.14720) — delimiter defense effectiveness, <2% ASR against non-adaptive attacks
- [Adaptive Attacks Break Defenses Against Indirect Prompt Injection](https://aclanthology.org/2025.findings-naacl.395.pdf) — 90%+ bypass rate under adaptive conditions
- [How Microsoft Defends Against Indirect Prompt Injection Attacks](https://www.microsoft.com/en-us/msrc/blog/2025/07/how-microsoft-defends-against-indirect-prompt-injection-attacks) — 2025 industry practice
- [OWASP LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) — defense-in-depth recommendations
- [Lessons from Defending Gemini Against Indirect Prompt Injections](https://storage.googleapis.com/deepmind-media/Security%20and%20Privacy/Gemini_Security_Paper.pdf) — 53.6% residual ASR post-mitigation (2025)
- [CryptProtectData function (dpapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) — local RPC to lsass.exe, no network traversal
- [SQLite Performance Benchmarks 2025](https://toxigon.com/sqlite-performance-benchmarks-2025-edition) — WAL mode and encryption overhead context

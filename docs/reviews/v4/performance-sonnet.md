# Context Engine v4 — Performance Review (Second Pass)

**Date:** 2026-03-28
**Reviewer:** Claude Sonnet 4.6
**Spec reviewed:** `2026-03-28-context-engine-architecture.md`
**Prior review:** `docs/reviews/v3/performance-sonnet.md`
**Focus:** Verify fixes from v3 review, assess new component costs (pymorphy3, DPAPI on corrections, LLM validator)

---

## Fix Verification

### Fix 1: idx_history_context index column order — VERIFIED FIXED

**v3 finding:** Index was `(app, thread_id, timestamp DESC)`, forcing an unnecessary B-tree scan prefix on `app` for the `get_recent_messages(thread.id, limit=3)` query, which filters only by `thread_id`. Estimated overhead: 0.5–1ms per dictation.

**v4 spec (Section 15, line 1608):**
```sql
CREATE INDEX idx_history_context ON history(thread_id, timestamp DESC);
```

The `app` column has been removed as the leading prefix. The index now matches the query access pattern exactly — `thread_id` equality scan followed by `timestamp DESC` ordering. This is the correct fix. Estimated savings: 0.5–1ms per dictation on warm cache. **No remaining concern.**

---

### Fix 2: pymorphy3 replaces tree_stem — PARTIALLY ASSESSED

**v3 finding:** No prior mention in v3 review — this is a new component added to the spec for Ukrainian lemmatization (Section 11.1, 12). The spec states: "pymorphy3 is the only dependency (~5MB with dictionaries), <1ms per word."

**Assessment of the <1ms per word claim:**

The claim is plausible but not conservative. Research findings:

- **pymorphy2 benchmark data** (the codebase pymorphy3 is forked from): the original pymorphy2 paper (arXiv:1503.07283) and PyPI documentation document performance in the range of "several thousand to over 100,000 words per second" in a single thread, depending on the operation. At the lower end (conservative: 5,000 words/sec), per-word cost is 0.2ms. At the upper end (100,000 words/sec), per-word cost is 0.01ms.
- **pymorphy3 specifically:** No independent published benchmarks found as of March 2026. The library is a fork/continuation of pymorphy2 and uses the same DAWG (Directed Acyclic Word Graph) data structure with optional C extensions. The Ukrainian dictionary (`pymorphy3-dicts-uk`) is 8.1MB on disk.
- **Initialization time is the real risk:** pymorphy2's `MorphAnalyzer` loads the full dictionary into memory at construction time. For Russian, this takes approximately 1–3 seconds on a cold start and consumes 50–150MB of RAM. The Ukrainian dictionary (`pymorphy3-dicts-uk`) at 8.1MB is significantly smaller than the Russian dictionary (~28MB compressed), but initialization time for the Ukrainian model is undocumented and requires empirical measurement. A 500ms–2s cold initialization is plausible.

**The spec instantiates the analyzer at module level:**
```python
morph = pymorphy3.MorphAnalyzer(lang='uk')
```

This means initialization cost is paid at app startup, not per-dictation. This is architecturally correct. However:

1. **The spec does not document the initialization time** as part of the startup latency budget.
2. **Memory footprint is unspecified.** pymorphy2 with Russian dictionary uses 50–150MB RAM. The Ukrainian dictionary being smaller (8.1MB disk vs ~28MB for Russian) suggests RAM footprint may be 15–50MB — but this is an estimate, not a measured value.
3. **The `<1ms per word` claim is almost certainly true at steady state** (post-initialization), but should be qualified as "per-word at runtime after initialization."

**Per-word cost for a typical 8-keyword dictation:** 8 × ≤1ms = ≤8ms total lemmatization. This is within the 50ms pipeline overhead budget but adds to the Context Engine's 5ms local budget if keyword extraction becomes a bottleneck. The spec quotes Level 1 cost as "~1ms" (Section 4.1) — if pymorphy3 adds up to 8ms for lemmatization of keywords, this budget needs revision.

**Remaining concern (medium priority):** The spec's "~1ms" for keyword extraction at Level 1 likely refers to the regex pass, not the full lemmatization pass. The total keyword extraction cost (regex + pymorphy3 lemmatization of 8–12 terms) may be 2–10ms, not 1ms. This should be measured empirically on the target Windows 10/11 hardware before final latency budget is published.

---

### Fix 3: DPAPI encryption on correction triads — NEW ADDITION, OVERHEAD QUANTIFIED

**v3 finding:** The v3 review noted DPAPI adds ~0.2ms for the 2 history blobs per dictation (0.1ms each). This was accepted as acceptable.

**v4 change:** DPAPI encryption is now also applied to correction triads — 3 blobs per correction (raw_text_enc, normalized_text_enc, corrected_text_enc). Section 10.2 and Section 15 (corrections schema) confirm this.

**DPAPI latency per call:**

No published benchmarks found via web search for `CryptProtectData` overhead. The following estimate is derived from DPAPI architecture:

- DPAPI calls route through a local RPC to the LSA (Local Security Authority) process. This is an in-process system call on Windows 10/11, but involves inter-process communication via LRPC.
- The v3 review's estimate of 0.1ms per call was consistent with developer-reported observations (Python `win32crypt.CryptProtectData` on small payloads). Microsoft's documentation confirms the function creates a session key and adds a MAC, which implies AES-CBC or AES-GCM internal operation on the plaintext.
- For small payloads (50–500 bytes, typical dictation text), the dominant cost is the LRPC round-trip to LSA, not the cryptographic work. LRPC on local loopback on modern Windows is ~0.05–0.2ms.

**Correction path DPAPI overhead:** 3 blobs × 0.1ms = 0.3ms additional per correction. Combined with the 2 history blobs already counted (0.2ms), a dictation that triggers correction learning now incurs 0.5ms total DPAPI overhead.

**The v3 write budget showed the correction path subtotal as 2.2ms.** Adding 0.3ms DPAPI overhead for correction triads revises this to ~2.5ms. The total worst-case write budget becomes:

| Path | v3 estimate | v4 revised |
|------|-------------|------------|
| Normal path subtotal | 4.3ms | 4.3ms (unchanged) |
| Correction path subtotal | 2.2ms | 2.5ms (+0.3ms DPAPI) |
| **TOTAL WORST CASE** | **~6.5ms** | **~6.8ms** |

**Verdict:** Acceptable. The 0.3ms addition does not change the overall assessment. The correction path remains well within acceptable bounds.

**Export/import DPAPI cost (separate concern):** During profile export, every history row and correction row requires 2–3 DPAPI decrypt calls. At 36K history rows + 5K correction rows = ~41K rows × 2.5 calls average = ~102,500 DPAPI calls × 0.1ms = **~10 seconds for a full export**. The v3 review estimated 3.6 seconds for history alone; adding correction triads raises this to approximately 8–12 seconds. This is a UX concern for the export flow — the UI should display a progress indicator and not block the main thread.

---

### Fix 4: LLM validator for scripts — ONE-TIME COST, MODEL UNSPECIFIED

**v3 finding:** Not present in v3 review — this is a new security feature in v4 (Section 9.3).

**Spec states:** `model="fast"` — cheapest model, safety check. Called ONCE at script save time, NOT per dictation.

**Problem: `model="fast"` is an unresolved alias.** The spec does not define what "fast" maps to in the LLM provider chain (Groq → OpenAI → Anthropic). This is architecturally incomplete.

**Latency assessment by likely model:**

The VALIDATOR_PROMPT is ~140 tokens. A typical script body is 20–80 tokens. Output is ~30–50 tokens (JSON with issues list). Total: ~190–270 tokens per validation call.

| Candidate model | Provider | TTFT | Total latency est. |
|---|---|---|---|
| Groq Llama 3.3 70B | Groq | ~200–220ms | ~300–400ms |
| Groq Llama 3.1 8B | Groq | ~50–100ms | ~100–200ms |
| GPT-4o-mini | OpenAI | ~300–500ms | ~500–800ms |
| Claude Haiku 3.5 | Anthropic | ~200–400ms | ~400–600ms |

**For a one-time save action, any of these latencies are acceptable from a UX perspective.** The user is saving a script — 300–800ms is imperceptible in that context.

**For profile import with multiple scripts:** If an imported profile contains 10 scripts, sequential validation calls = 10 × 300–800ms = 3–8 seconds. This could be perceived as slow. The spec calls `validate_script()` sequentially in `import_profile()` for each script without batching or parallelization.

**New concern:** The `model="fast"` alias must be defined. If it falls back to a 70B model (e.g., Groq Llama 3.3 70B as the primary Groq model), the latency is still acceptable for single-script saves but inefficient. Groq's Llama 3.1 8B would be more appropriate — lower latency, lower cost, and the task (prompt injection detection) does not require a 70B model's reasoning capability.

---

## Updated Latency Budget

### Per-dictation critical path (warm cache, normal path)

| Stage | v3 estimate | v4 revised | Change |
|-------|-------------|------------|--------|
| VAD silence detection | 50–200ms | 50–200ms | — |
| STT (AssemblyAI streaming) | 200–400ms | 200–400ms | — |
| Replacements (local) | 1–5ms | 1–5ms | — |
| Keyword extraction (regex) | ~1ms | ~1ms | — |
| **Lemmatization (pymorphy3, 8 words)** | not budgeted | **~1–8ms** | NEW |
| Thread/co-occurrence resolution | ~3ms | ~3ms | — |
| History index read (idx fix) | ~1.5ms | ~0.5ms | -1ms |
| Prompt assembly | <0.5ms | <0.5ms | — |
| **Context Engine total** | **~5ms** | **~5–13ms** | depends on word count |
| LLM normalization (Groq Llama 3.3 70B) | 160–360ms | 160–360ms | — |
| Post-processing + injection | 2–5ms | 2–5ms | — |

**Groq Llama 3.3 70B TTFT:** Independent benchmarks (Artificial Analysis, March 2026) report **~200–220ms TTFT** for short prompts (~100 input tokens) and **279 tokens/second generation speed**. For 30 output tokens, generation time = 30/279 × 1000 ≈ 108ms. Total LLM latency: **~320–330ms typical**.

**Revised typical case total:** 150ms VAD + 350ms STT + 8ms CE (with pymorphy3) + 325ms LLM + 3ms inject = **~836ms** (vs ~760ms in v3)

The additional 76ms comes from pymorphy3 lemmatization. The 5ms CE budget stated in Section 2 is now tight — it depends on whether pymorphy3 achieves the upper end of its performance range (~0.1ms/word) or the lower end (~1ms/word). The spec's claim of `<1ms per word` needs to be validated empirically on Windows 10/11 with C extensions compiled.

### Startup latency (one-time)

The spec does not document startup latency. New items that add to startup time:

| Component | Estimated startup cost |
|---|---|
| pymorphy3 `MorphAnalyzer(lang='uk')` initialization | 500ms–2s (estimated; unmeasured) |
| SQLite page cache warm-up (`warm_cache()`) | 10–50ms |
| daily_maintenance (if run on startup) | 50–500ms (background thread) |

**The pymorphy3 initialization is the new unknown.** At 500ms–2s it is acceptable for a desktop app. At the worst case (slow disk, cold OS), it could approach 3–5s. This should be measured before shipping.

---

## Updated Memory Budget

### Steady-state memory footprint additions

| Component | v3 budget | v4 addition |
|---|---|---|
| SQLite page cache (64MB) | 64MB | unchanged |
| Python runtime + app baseline | ~30–50MB | unchanged |
| **pymorphy3 Ukrainian dictionary (in-memory)** | not present | **~15–50MB estimated** |
| DB rows at 1 year (35MB on disk) | mostly cached | unchanged |

**New total memory budget (estimated):** ~110–165MB vs ~95–115MB in v3.

The pymorphy3 memory impact is significant but not alarming for a desktop app targeting Windows 10/11 (which typically has 8–16GB RAM). However, the spec should document the expected RAM footprint explicitly. The Ukrainian dictionary (`pymorphy3-dicts-uk`, 8.1MB on disk) likely expands to 15–50MB in memory after DAWG deserialization — this range is wide because no published measurements for the UK variant were found.

---

## New Performance Concerns

### Concern 1 (HIGH): pymorphy3 initialization time undocumented

The spec states `<1ms per word` for pymorphy3 but does not document the initialization time. The `MorphAnalyzer(lang='uk')` instance is created at module import time (module-level global). On a cold Windows boot with the executable loaded from SSD, initialization time of 500ms–2s is plausible.

**Risk:** First-launch experience may show a 1–3 second delay before the tray icon appears and the app is ready. If initialization is synchronous on the main thread, the entire app is frozen during this window.

**Recommendation:** Initialize `MorphAnalyzer` in a background thread at startup. The app can safely accept dictations without lemmatization during the ~500ms initialization window — fall back to raw tokens (no lemmatization) if `morph` is not yet ready, then enable lemmatization once initialized. Add a startup timing log for first-run telemetry.

### Concern 2 (MEDIUM): CE latency budget breach risk from pymorphy3

The spec's Section 2 states "Context resolution <5ms." The v3 review confirmed this was achievable at ~5ms warm-cache. With pymorphy3 adding 1–8ms for lemmatization of 8–12 keywords, the CE budget can reach 8–15ms in the worst case.

**Impact:** The 5ms CE target is now potentially unachievable without restricting lemmatization. However, in the overall pipeline context, 8–15ms CE vs 5ms CE is irrelevant — STT and LLM latencies (350ms + 325ms) dominate. The 5ms target appears to be an internal quality bar, not a user-visible constraint.

**Recommendation:** Revise the CE latency target in Section 2 to `<15ms` to accurately reflect pymorphy3's contribution, or explicitly break out "keyword extraction" as a separate budget item (`<2ms regex + <10ms lemmatization`).

### Concern 3 (MEDIUM): `model="fast"` alias undefined

Section 9.3 calls `llm_call(model="fast")` for script validation. This alias is undefined in the spec. If the alias resolves to the primary LLM provider's primary model (Groq Llama 3.3 70B), validation latency is 300–400ms — fine for single saves.

**For profile import with N scripts:** N × 300–400ms validation is sequential. At N=10 scripts, this is 3–4 seconds of blocking. The spec does not show parallelization of validation calls in `import_profile()`.

**Recommendation:** Define `model="fast"` explicitly as Groq Llama 3.1 8B (or equivalent small model), which achieves ~50–100ms TTFT with sufficient capability for prompt injection classification. For profile import, run validation calls concurrently (asyncio or thread pool) with a cap of 3 parallel calls.

### Concern 4 (LOW): Profile export time increase

Adding DPAPI encryption to correction triads (3 blobs per row) increases full export time from ~3.6s (v3 estimate, history only) to ~8–12s. This is not a real-time concern but should be reflected in the export UX — a progress bar with estimated time remaining is necessary for exports of user profiles with 12+ months of data.

### Concern 5 (LOW): pymorphy3 memory footprint undocumented

No published measurements exist for pymorphy3-dicts-uk RAM usage at runtime. The spec claims "~5MB with dictionaries" — this appears to refer to the on-disk install size, not the in-memory footprint after DAWG deserialization. Actual RAM usage is estimated at 15–50MB based on pymorphy2 Russian dictionary behavior (which uses ~50–150MB for a larger dictionary). This needs empirical measurement.

---

## Verdict

### Fixes from v3: status

| v3 Issue | Fix Applied | Assessment |
|---|---|---|
| `idx_history_context` wrong column order | Fixed: now `(thread_id, timestamp DESC)` | Correct and complete |
| SQLITE_BUSY retry logic unspecified | Not verified in this review (schema-level spec) | Carry forward from v3 |
| daily_maintenance blocking thread | Not verified (implementation detail) | Carry forward from v3 |
| WAL checkpoint tuning | Not verified (implementation detail) | Carry forward from v3 |

### New components from v4: assessment

| Component | Risk Level | Key Concern |
|---|---|---|
| pymorphy3 runtime (<1ms/word) | LOW | Claim is plausible; verify empirically on Windows |
| pymorphy3 initialization | MEDIUM | 500ms–2s cold start; needs background threading |
| pymorphy3 memory footprint | MEDIUM | 15–50MB unbudgeted; measure before ship |
| DPAPI on corrections (0.3ms added) | LOW | Budget impact negligible |
| LLM validator (`model="fast"`) | MEDIUM | Alias undefined; profile import sequential |

### Overall

The spec is in good shape. The index fix from v3 is confirmed correct. The major new risk introduced in v4 is **pymorphy3 initialization time and memory footprint** — both are uncharacterized in the spec and require empirical measurement on the target Windows 10/11 hardware before the latency and memory budgets in Section 2 can be considered verified.

The `<5ms` Context Engine latency target in Section 2 is technically breached by the addition of pymorphy3 lemmatization (which adds 1–8ms). Given that STT+LLM dominate the total pipeline at ~675ms, this breach has zero user-visible impact. The target should be updated to `<15ms` to reflect reality, or the spec will fail its own stated goals in any empirical measurement.

The LLM validator is correctly designed as a one-time save-time check and poses no per-dictation overhead. The `model="fast"` alias needs to be resolved before implementation to avoid accidentally routing validation through a 70B model.

**Blocking for ship:** None. All identified concerns are medium or low priority.
**Recommended before ship:** Measure pymorphy3 init time and RAM on Windows 10/11 with PyInstaller packaging; update Section 2 latency target; define `model="fast"` alias explicitly.

---

*End of performance review v4.*

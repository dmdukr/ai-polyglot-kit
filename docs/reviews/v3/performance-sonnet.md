# Context Engine v3 — Performance Review

**Date:** 2026-03-28
**Reviewer:** Claude Sonnet 4.6
**Spec reviewed:** `2026-03-28-context-engine-architecture.md`
**Focus:** Write amplification, read latency, SQLite contention, memory footprint, scaling limits, LLM latency

---

## Write Path Analysis (per-dictation write budget with exact numbers)

### Normal dictation — typical case (8 keywords, one active thread)

The write path involves six distinct write operations after every dictation.

**1. Co-occurrence UPSERT batch**

8 keywords → 7 terms with bigrams = 15 terms after the unigrams+bigrams pass, but the spec caps at `max_keywords=12`, so realistic output is 12 terms. Co-occurrence pairs = T*(T-1)/2:

| Keyword count | Terms (unigrams+bigrams, capped) | Pairs | UPSERTs |
|---|---|---|---|
| 4 words → 7 terms | 7 | 21 | 21 |
| 6 words → 11 terms | 11 | 55 | 55 |
| 8 words → 12 terms (capped) | 12 | 66 | 66 |
| 10 words → 12 terms (capped) | 12 | 66 | 66 |

Each UPSERT touches the `term_cooccurrence` table with a 3-column compound PK (term_a, term_b, cluster_id). With SQLite WAL and a batch transaction, the spec estimates ~2ms for ~100 pairs. This is plausible: WAL mode benchmarks show ~3,600 writes/sec for single-row writes, but batched in one transaction that overhead collapses to effectively I/O-bound page writes — 66 UPSERTs in one transaction should complete in 1–3ms on an NVMe-backed desktop.

**2. Thread UPDATE**
1 row UPDATE on `conversation_threads` (last_message, message_count, optionally cluster_id).

**3. Thread keywords INSERT**
Up to 12 INSERTs into `thread_keywords` (PRIMARY KEY conflict = ignored if keyword already in thread). Deduplication happens at INSERT time — no pre-check needed.

**4. History INSERT**
1 row INSERT into `history` (DPAPI encryption of two TEXT blobs happens in Python before INSERT — DPAPI call is ~0.1ms each, so 0.2ms total encryption overhead).

**5. Cluster re-evaluation (conditional)**
Every 3+ messages: 1 SELECT (detect_cluster) + potentially 1 INSERT into `clusters` + 1 UPDATE on `conversation_threads`. Amortized: roughly 1/3rd of dictations trigger this.

**6. Mixed-topic guard query (read before write)**
1 SELECT on `term_cooccurrence` with IN clause — this is a read, but it blocks the write transaction. See read path below.

### Worst-case write budget (10 keywords, new thread, correction triggered)

| Operation | Rows | Est. time |
|---|---|---|
| Mixed-topic guard SELECT | 1 query, scan <200 rows | 1ms |
| Co-occurrence UPSERT batch (66 pairs) | 66 rows in 1 txn | 2ms |
| Thread UPDATE | 1 row | 0.2ms |
| Thread keywords INSERT (12 terms) | up to 12 rows | 0.3ms |
| History INSERT (with DPAPI) | 1 row + 0.2ms crypto | 0.5ms |
| Cluster INSERT + name UPDATE | 2 rows | 0.3ms |
| **Subtotal — normal path** | **~82 rows** | **~4.3ms** |
| + Correction path (if feedback given) | | |
| Correction INSERT | 1 row | 0.2ms |
| correction_counts UPSERT per diff token | 1–5 rows | 0.3ms |
| co-occurrence reinforcement per keyword×diff | up to 12 × 5 = 60 UPSERTs | 1.5ms |
| dictionary INSERT (if auto-promote triggered) | 1 row | 0.1ms |
| cluster_llm_stats UPSERT | 1 row | 0.1ms |
| **Subtotal — correction path** | **~68 rows** | **~2.2ms** |
| **TOTAL WORST CASE** | **~150 rows** | **~6.5ms** |

### Amplification ratio

A 10-word dictation (30 characters of raw text) produces up to **150 SQLite row writes**. That is a write amplification factor of approximately **15×** per word, or **5× per raw character**.

The dominant cost is the co-occurrence UPSERT batch. The compound PK (term_a, term_b, cluster_id) requires a B-tree lookup per UPSERT even on conflict — at 66 pairs, this is 66 B-tree traversals within a single transaction. With the WAL page cache set to 64MB this is likely all in-memory, but the WAL itself must be written before transaction commit under NORMAL sync, adding one fdatasync equivalent.

### Fingerprint creation (amortized)

When a thread expires (first dictation in a new conversation after >15min gap), a fingerprint is saved: 1 INSERT into `conversation_fingerprints` + up to 12 INSERTs into `fingerprint_keywords`. This is ~1ms extra, amortized across the lifetime of a thread (typically 5–20 messages → effectively negligible per dictation).

---

## Read Path Analysis (per-dictation read latency breakdown)

### Are the four resolution levels sequential or parallelizable?

The spec states "tries 4 levels in order, stops at the first confident result." This is inherently sequential by design — each level is a fallback for the previous. **They cannot be naively parallelized** because:

1. Level 2 depends on Level 1's result (if L1 resolves with confidence ≥ 0.6, L2 is skipped)
2. Level 3 is only reached when Level 2 fails
3. Levels 1-3 share the same database connection and their reads interact with concurrent writes

However, **Levels 1 and 2 can be partially overlapped**: the co-occurrence query (Level 1) and the active thread lookup (Level 2) touch different tables (`term_cooccurrence` vs `conversation_threads`). In practice, Python's GIL and synchronous SQLite driver prevent true parallelism here unless a thread pool with separate connections is used (architecturally complex).

### Cold cache vs warm cache

The spec sets `cache_size = -64000` (64MB). At steady state (1 year, ~35MB total DB), the entire database fits in the page cache. After the first few queries on app startup, subsequent dictation reads are essentially in-memory operations.

**Cold cache (first query after app restart):**

| Level | Query | Cold (page fault) | Warm (cache hit) |
|---|---|---|---|
| Keyword extraction | Python: regex + stem_uk | ~1ms | ~1ms (CPU only) |
| L1 mixed-topic guard | `term_cooccurrence` WHERE IN | 3–8ms | <1ms |
| L1 co-occurrence lookup | `term_cooccurrence` WITH decay | 3–8ms | ~1ms |
| L2 active thread lookup | `conversation_threads` JOIN `thread_keywords` | 2–5ms | ~1ms |
| L3 fingerprint lookup | `conversation_fingerprints` JOIN `fingerprint_keywords` | 2–5ms | ~1ms |
| Prompt assembly | Python string ops | <0.5ms | <0.5ms |
| **Total — cold cache** | | **~12–27ms** | **~5ms** |

Cold start is triggered once per app session (app restart). The `warm_cache()` function called at end of `daily_maintenance` pre-warms this by touching all three relevant tables, which mitigates the restart penalty.

### Read amplification in the mixed-topic guard

`should_update_cooccurrence()` queries `term_cooccurrence` with a double IN clause:
```sql
WHERE (term_a IN (?, ?, ...) OR term_b IN (?, ?, ...))
```
With 12 keywords this is 24 bind parameters. The query cannot use a single index efficiently for the OR condition — SQLite will likely do two index scans (one on idx_cooccurrence, one on idx_cooccurrence_reverse) and UNION the results. At 60K edges this is acceptable; at 200K edges (emergency prune threshold) this becomes the hottest read path in the system. See Scaling Projections below.

### History fetch for thread context (3 recent messages)

The prompt builder calls `get_recent_messages(thread.id, limit=3)` — a SELECT on `history` filtered by `thread_id` and ordered by `timestamp DESC`. The index `idx_history_context(app, thread_id, timestamp DESC)` covers this but is composite — the query must use `thread_id` as the leading column for optimal performance. Since the index has `app` first, SQLite will use it as app+thread_id lookup when both are provided, or do a partial index scan on thread_id alone. This is a minor inefficiency: the index should be `(thread_id, timestamp DESC)` for this query pattern. Currently it adds ~0.5–1ms overhead.

---

## Scaling Projections (when does each component hit its limit?)

### Component 1: co-occurrence table (first to degrade)

| Edge count | co-occurrence lookup | mixed-topic guard | write batch |
|---|---|---|---|
| 10K edges | <0.5ms | <0.5ms | <1ms |
| 60K edges (1 year) | ~1ms | ~1ms | ~2ms |
| 100K edges | ~1.5ms | ~2ms | ~3ms |
| 200K edges (emergency cap) | ~3ms | ~4ms | ~5ms |
| 500K edges (if pruning disabled) | ~8ms | ~12ms | ~10ms |

The **200K emergency prune** is the spec's self-imposed ceiling, and it is well-chosen. Beyond that, the double-OR query on term_cooccurrence without covering indexes becomes the dominant latency. The spec's 5ms context resolution target breaks at approximately **300K–400K edges** under warm-cache conditions.

### Component 2: fingerprint table

The spec caps fingerprints at 10K rows with `fingerprint_keywords` growing proportionally (average ~5 keywords per fingerprint = 50K rows in `fingerprint_keywords`). The cold-start query does a JOIN with an IN clause — performance is O(keywords × index_lookups) = 12 × log(50K) ≈ 12 × 16 = ~192 comparisons. Well within budget.

At 10K fingerprints the JOIN returns up to hundreds of candidate rows before GROUP BY aggregation. This scales acceptably to the 10K cap.

### Component 3: thread_keywords table

`find_active_thread()` queries thread_keywords WHERE keyword IN (?) AND filtered by active+time window. Index `idx_tk_keyword(keyword, thread_id)` makes this O(keywords × active_threads). Active threads are bounded by the 15-minute window — in practice 1–20 active threads at any time. No scaling concern.

### Component 4: history table

With 36K rows at 1 year and encrypted BLOBs, the history table is the largest but rarely the hottest. The 3-message context fetch is indexed. Only the privacy export (DPAPI decrypt of all rows) becomes expensive at scale — 36K DPAPI calls at ~0.1ms each = **~3.6 seconds for a full export**. Not a real-time concern but worth documenting for the export UX.

### Overall scaling limit summary

| Threshold | Symptom | Trigger |
|---|---|---|
| **60K co-occurrence edges** | Still fast, within spec | 1 year at 100 dict/day |
| **200K co-occurrence edges** | Emergency prune fires, brief 50–100ms freeze | Pruning disabled, or 5+ years heavy use |
| **300K+ edges** | 5ms context budget exceeded | Only if pruning logic fails |
| **10K fingerprints** | Fingerprint cap fires, DELETE subquery | ~3 years at 100 dict/day |
| **1M+ history rows** | History retention DELETE becomes slow (seconds) | ~27 years — not realistic |

**First bottleneck is the co-occurrence OR query at 200K+ edges.** The spec's emergency prune at 200K is the correct defensive measure, but the prune itself (`DELETE WHERE weight < 3`) is not atomic with ongoing writes — see SQLite contention below.

---

## SQLite Contention Analysis

### WAL mode: what it solves and what it doesn't

WAL mode eliminates reader-writer blocking in the normal case: context reads proceed concurrently with co-occurrence writes. This is correctly identified in the spec (Section 15.1). SQLite WAL benchmarks confirm ~3,600 write/sec in WAL mode vs ~291 write/sec in rollback mode.

However, three scenarios cause contention:

**Scenario 1: VACUUM during active dictation**

The spec defers VACUUM to an idle scheduler (Section 13.2): "called by the app's idle scheduler (e.g., after 60s of no dictation activity). NOT run inline in daily_maintenance."

This is correct. However, the idle detection is not defined in the spec. If VACUUM fires and a dictation arrives within its execution window (VACUUM can take 200–500ms on a 35MB database), SQLite will return `SQLITE_BUSY` to the writer. The app must implement retry logic with a timeout. **The spec does not specify how SQLITE_BUSY is handled in the write path.**

VACUUM also doubles the WAL file size temporarily (WAL grows by the number of used pages), which on a heavily written system can cause a checkpoint stall.

**Scenario 2: daily_maintenance co-occurrence prune during dictation**

`daily_maintenance()` runs at startup, but includes five sequential DELETE statements. These each acquire exclusive write locks for their duration. The largest is the co-occurrence prune:
```sql
DELETE FROM term_cooccurrence WHERE weight = 1 AND last_used < datetime('now', '-90 days')
```
At 60K edges, approximately 40% may be pruned (~24K rows). On a cold page cache, this DELETE can take **50–200ms**. If a dictation arrives during this window, the writer will block.

**Mitigation not specified:** The spec says "run at app startup" but does not specify whether startup maintenance runs on the main thread or a background thread. If on the main thread, app startup is blocked for up to 500ms before the first dictation can be processed.

**Scenario 3: WAL checkpoint starvation**

SQLite auto-checkpoints at 1000 WAL pages (default). With 66+ UPSERTs per dictation at a rate of 30 dictations/hour, the WAL accumulates ~2,000 row writes/hour. The auto-checkpoint runs asynchronously but can stall if there is a long-running reader. The `warm_cache()` function at the end of maintenance creates exactly such a reader (three COUNT(*) queries). If checkpoint triggers while warm_cache is running, the WAL will not truncate.

**Recommendation:** Set `PRAGMA wal_autocheckpoint = 400` (reduce from 1000) to checkpoint more frequently with less contention per checkpoint event.

---

## LLM Latency Analysis (end-to-end user-perceived timing)

### Pipeline timing breakdown

```
User stops speaking
        │
        ▼  VAD silence detection
    +50–200ms (VAD end-of-speech buffer)
        │
        ▼  Stage 2: STT (AssemblyAI/Deepgram streaming)
    +200–400ms (word emission latency)
    [AssemblyAI Universal-Streaming: ~300ms median, ~1,012ms P99]
    [Deepgram Nova-3: ~516ms median, ~1,907ms P99]
        │
        ▼  Stage 3: Replacements (local)
    +1–5ms
        │
        ▼  Stage 4: Context Engine (local)
    +3–5ms (warm cache) / 12–27ms (cold cache)
        │
        ▼  Stage 5: LLM normalization
    +200–400ms (Groq TTFT, sub-300ms guaranteed, ~100ms typical)
    [~30 output tokens at 500 tok/sec = 60ms generation time]
    [Total LLM: TTFT + generation = ~160–360ms]
        │
        ▼  Stage 6: Local post-processing
    +1–2ms
        │
        ▼  Stage 7: Text injection
    +1–3ms (Windows SendInput / clipboard)
```

### Total user-perceived latency

| Path | Breakdown | Total |
|---|---|---|
| **Best case** (warm cache, Groq, AssemblyAI) | 100ms VAD + 300ms STT + 5ms CE + 160ms LLM + 3ms inject | **~570ms** |
| **Typical case** | 150ms VAD + 350ms STT + 5ms CE + 250ms LLM + 3ms inject | **~760ms** |
| **P99 case** (cold cache, Deepgram fallback, OpenAI) | 200ms VAD + 1,907ms STT + 25ms CE + 800ms LLM + 5ms inject | **~2,940ms** |

The 50ms context resolution target from Section 2 is easily met by the Context Engine itself (5ms warm). The **bottleneck is the STT+LLM sequential pair**, which consumes 450–700ms in the typical case.

### Can STT and LLM be overlapped?

Theoretically yes — streaming STT returns partial transcripts. The LLM normalization could begin on the partial transcript while STT is still finalizing. However this creates correctness problems:

1. Partial transcripts change as more audio arrives (AssemblyAI's immutable transcripts arrive ~300ms after last word, not during)
2. The Context Engine reads the final text for keyword extraction and thread assignment
3. Sending partial text to LLM wastes tokens on corrections

**The spec makes the correct architectural choice**: wait for STT finalization before LLM. The latency is dominated by the network round-trips, not by the Context Engine. Overlapping would add implementation complexity for minimal gain (~50–80ms at best).

The one **valid optimization**: the Context Engine's DB reads (Steps 4a–4c of the 4-level resolution) could be **pre-started** upon VAD end-of-speech while STT is still completing. Since context resolution needs the app name and window title (available immediately) but only needs the dictation text for Level 1 (keyword extraction), Levels 2 and 3 could run speculatively:

- On VAD silence: immediately start Level 2 (active thread lookup — no text needed) and Level 3 (fingerprint lookup for most-recent app)
- When STT result arrives: run Level 1, combine with pre-fetched Level 2/3 results
- Savings: 1–2ms of the 5ms CE budget (marginal, but free)

---

## Bottleneck Summary (ranked by impact)

| Rank | Bottleneck | Impact | Mitigation |
|---|---|---|---|
| 1 | **STT API latency (P99)** | Up to 1,907ms added to user latency | Provider fallback already specced; consider streaming-partial hint for faster immutable transcript |
| 2 | **LLM API latency** | 160–800ms sequential after STT | Groq as primary is the right call (~100ms TTFT); OpenAI fallback is ~300–500ms |
| 3 | **VACUUM contention (undefined idle window)** | Potential SQLITE_BUSY on writer; no retry logic specced | Define idle threshold, implement write retry with 50ms timeout and 3 attempts |
| 4 | **daily_maintenance blocking on main thread** | 50–200ms freeze at startup if run synchronously | Move all 5 DELETE operations to a background thread; flag completion before first dictation |
| 5 | **co-occurrence OR query at 200K edges** | 4–12ms; breaks 5ms CE budget | Already mitigated by emergency prune at 200K; add `weight < 3` partial index to accelerate the prune query itself |
| 6 | **WAL checkpoint starvation during warm_cache** | WAL file grows unboundedly | Add `PRAGMA wal_autocheckpoint = 400` |
| 7 | **history index column order** | 0.5–1ms extra on 3-message context fetch | Change `idx_history_context` to `(thread_id, timestamp DESC)` as primary columns |
| 8 | **Write amplification (150 rows worst case)** | 6.5ms total write time — acceptable now | Not a problem at current scale; becomes relevant if dictation frequency exceeds 10/minute |

---

## Recommendations

### Priority 1 — Safety (must fix before shipping)

**1.1 SQLITE_BUSY retry logic in write path**

The spec defers VACUUM to idle time but does not specify retry behavior when the writer receives SQLITE_BUSY. SQLite WAL mode can still return SQLITE_BUSY in certain conditions (checkpoint blocking, VACUUM). Implement:

```python
def execute_with_retry(query, params, retries=3, delay_ms=50):
    for attempt in range(retries):
        try:
            return db.execute(query, params)
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                time.sleep(delay_ms / 1000)
                continue
            raise
```

**1.2 Run daily_maintenance on a background thread**

The five DELETE operations in `daily_maintenance()` must not block the main thread. Move to a `threading.Thread(daemon=True)`. Add a `maintenance_complete` event that the dictation pipeline waits for (with a 500ms timeout) before its first write. This prevents write conflicts during the maintenance window on startup.

### Priority 2 — Performance (should fix for release)

**2.1 Fix history index for thread context reads**

Change:
```sql
CREATE INDEX idx_history_context ON history(app, thread_id, timestamp DESC);
```
To:
```sql
CREATE INDEX idx_history_context ON history(thread_id, timestamp DESC);
```
The `get_recent_messages(thread.id, limit=3)` query filters by `thread_id` first — app is not in the WHERE clause. The current index forces SQLite to include `app` in the scan prefix, costing an unnecessary B-tree level.

**2.2 Add WAL checkpoint tuning**

Add to database initialization:
```sql
PRAGMA wal_autocheckpoint = 400;  -- checkpoint every 400 pages (~1.6MB WAL)
```
This keeps WAL file size bounded without manual intervention.

**2.3 Speculative context pre-fetch on VAD silence**

As described in the LLM Latency section: start Level 2 (thread lookup) and Level 3 (fingerprint lookup) on VAD silence while waiting for STT result. These queries require only `current_app`, which is available immediately. Saves 1–2ms from the critical path at zero correctness risk.

### Priority 3 — Future scalability (defer to v7)

**3.1 Add partial index for prune query acceleration**

```sql
CREATE INDEX idx_cooccurrence_prune
ON term_cooccurrence(weight, last_used)
WHERE weight <= 2;
```
This makes the emergency prune (`DELETE WHERE weight < 3`) use the index instead of a full table scan. Critical once the table approaches 200K edges.

**3.2 Separate read and write connections**

When the system exceeds ~200 dictations/day (power users), consider opening two SQLite connections: one read-only (`SQLITE_OPEN_READONLY`) for the context resolution reads, one writable for the co-occurrence UPSERTs. WAL mode supports this natively. This eliminates any serialization between Level 1-3 reads and the write batch.

**3.3 Consider async write pipeline for corrections**

The correction learning path (Section 10.2) is called synchronously but is not on the critical path for user experience — the text has already been injected into the app. Move correction writes to a background queue processed by a single writer thread. This decouples user-perceived latency entirely from the correction write amplification (60+ additional UPSERTs).

---

*End of performance review.*

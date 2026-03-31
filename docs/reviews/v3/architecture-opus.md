# Context Engine Architecture — Second Review (v3)

**Spec reviewed:** `docs/superpowers/specs/2026-03-28-context-engine-architecture.md` (Draft v3)
**Previous review:** `docs/reviews/2026-03-28-context-engine-review-opus.md` (20 issues)
**Reviewer:** Claude Opus 4.6 (senior systems architect, second-pass review)
**Date:** 2026-03-28
**Verdict:** Most previous issues were resolved correctly. Several new issues found, two of which are blocking. See Final Assessment.

---

## Previous Issues — Verification

The previous review raised 8 weaknesses (W1-W8), 8 edge cases (E1-E8), 5 architecture concerns (A1-A5), and 11 recommendations (R1-R11). The spec's status line says "all 20 review issues resolved." I verify each below.

### W1. No lemmatization — RESOLVED CORRECTLY

Section 11.1 now uses `tree_stem` for Ukrainian stemming. The `lemmatize()` function correctly detects Cyrillic characters and applies `stem_uk()` only to Ukrainian words, passing English through unchanged. Section 11.2 shows stemmed examples (`zamku` -> `zamok`, `vkhidnykh` -> `vkhidn`, `dveriakh` -> `dver`). The `tree_stem` dependency is acknowledged in Section 2 Goal 6 and Section 11.1.

**Concern (minor):** The spec states `from tree_stem import stem_uk` but `tree_stem` does not appear to be published on PyPI. The GitHub repository ([amakukha/stemmers_ukrainian](https://github.com/amakukha/stemmers_ukrainian)) provides the source code, but there is no `pip install tree-stem` path. The spec should clarify the dependency management: vendored copy of the single `.py` file (~48KB), git submodule, or a private PyPI mirror. This matters for PyInstaller packaging.

**Verdict:** FIXED, with minor packaging clarification needed.

### W2. Cluster identity fragile (string-based, no stable IDs) — RESOLVED CORRECTLY

Section 6.2 now defines a `clusters` table with `id INTEGER PRIMARY KEY AUTOINCREMENT` and a separate `display_name TEXT`. All foreign keys (`term_cooccurrence.cluster_id`, `conversation_threads.cluster_id`, `conversation_fingerprints.cluster_id`, `history.cluster_id`, `corrections.cluster_id`, `cluster_llm_stats.cluster_id`) reference `clusters(id)`. Section 12.2 explicitly states display_name is "Used only for UI display" and "Renaming a cluster has zero impact on threads, fingerprints, or co-occurrence data."

**Verdict:** FIXED correctly. Integer IDs with separate display names is the right approach.

### W3. Co-occurrence graph stores both directions — RESOLVED CORRECTLY

Section 6.3 now stores pairs in canonical order (`term_a < term_b` via `a, b = sorted([t1, t2])`). The reverse INSERT is gone. Section 6.4 lookup query checks both directions with `OR (term_b = ? AND term_a IN (...))`. Section 15.2 adds `idx_cooccurrence_reverse` on `(term_b, cluster_id, weight DESC)` to support the reverse lookup efficiently.

**Verdict:** FIXED correctly. Both the storage and the query pattern are sound.

### W4. `cold_start_cluster` app-filter bias — PARTIALLY RESOLVED

Section 7.4 still uses a hard binary: first query with `AND cf.app = ?`, then fallback without app filter. The previous review recommended mirroring the `find_active_thread` weighted pattern (app match = 2x, non-match = 1x). This was NOT done — the function still uses a hard filter/fallback approach.

However, the practical impact is reduced because fingerprints are a cold-start mechanism (no active thread exists), and the hard filter catches the common case (same app). The fallback without filter handles cross-app. This is acceptable for v1 but remains a known inconsistency with the thread-matching philosophy.

**Verdict:** PARTIALLY FIXED. Functional but inconsistent with Section 5.4's weighted approach. Acceptable for v1.

### W5. Confidence formula for Level 3 statistically unsound — RESOLVED CORRECTLY

Section 4 now shows Level 3 confidence as `hits_winner / sum(hits_all_clusters)` with the additional requirement `requires hits >= 2`. This prevents the 1-hit-wonder problem. The previous review suggested incorporating absolute hit count; the `hits >= 2` floor is a simpler solution that achieves the same goal for the most dangerous case (single match).

**Verdict:** FIXED. The `hits >= 2` minimum is a pragmatic guard. Could be stronger (hits >= 3 or the scaled formula) but acceptable.

### W6. LIKE-based correction matching — RESOLVED CORRECTLY

Section 10.2 now uses a dedicated `correction_counts` table with `PRIMARY KEY (old_token, new_token)` and exact UPSERT matching. No LIKE patterns anywhere in the correction flow. The `correction_counts` table also appears in the complete schema (Section 15.2).

**Verdict:** FIXED correctly. Clean solution that eliminates SQL injection risk, false positives, and full table scans.

### W7. Thread expiry "checked periodically" — RESOLVED CORRECTLY

Section 5.2 now explicitly states: "THREAD EXPIRY (lazy -- checked at query time, NOT a background job)." The `find_active_thread()` WHERE clause filters by `last_message > datetime('now', '-15 minutes')` and the spec states "this IS the expiry mechanism; no periodic cleanup needed." Section 13.2 daily maintenance marks old threads as inactive for cleanup purposes.

**Verdict:** FIXED correctly. Lazy expiry is the right choice for a desktop app.

### W8. VACUUM blocks all writes — RESOLVED CORRECTLY

Section 13.2 now separates VACUUM into an idle-time scheduled task: `schedule_vacuum()` is called by the app's idle scheduler after 60 seconds of no dictation. It is NOT run inline in `daily_maintenance`. The daily backup uses `VACUUM INTO` which creates a separate file without blocking the main DB.

**Verdict:** FIXED correctly. The idle-time scheduling is appropriate.

### E1. Language switching mid-dictation — RESOLVED CORRECTLY

Section 11.1 now explicitly addresses code-switching: "Mixed Ukrainian+English is expected and normal." The tokenizer splits on hyphens and slashes for mixed-script tokens ("PR-zapyt" -> ["pr", "zapyt"], "CI/CD" -> ["ci", "cd"]). Ukrainian words get stemmed, English words pass through.

**Verdict:** FIXED. The split-by-script approach is pragmatic and correct.

### E2. Rapid app switching — NOT ADDRESSED (acknowledged)

The spec does not address the scenario of a rapid switch where the VS Code dictation has no matching keywords. This remains a known limitation — keyword-less cross-app follow-ups will lose context. The spec's orphan dictation handling (thread_id = NULL) is the correct fallback, but no attempt is made to use temporal proximity as a signal.

**Verdict:** NOT FIXED, but acknowledged. Acceptable as a known limitation for v1.

### E3. Multiple simultaneous active threads per app — NOT ADDRESSED (acknowledged)

The `LIMIT 1` for keyword-less messages still picks the most recent active thread in the app. The spec does not discuss this as a design risk for rapid chat switching.

**Verdict:** NOT FIXED. Remains a known limitation. Acceptable for v1.

### E4. Sensitive content in unencrypted fields — ADDRESSED VIA DOCUMENTATION

Section 17 now documents exactly which fields are unencrypted, provides content examples, discusses the threat model, and proposes a future "privacy mode" with AES-SIV. This is appropriate transparency rather than a code fix.

**Verdict:** FIXED (via documentation). The threat model section is honest and complete.

### E5. Dictionary conflicts between exact and context terms — RESOLVED CORRECTLY

Section 8.2 now explicitly states: "If a term exists as both exact and context type, context resolution (Stage 4) takes precedence. Stage 6 exact replacement only applies to terms NOT already resolved by the context engine. A `resolved_terms: set[str]` is passed from Stage 4 to Stage 6 to prevent double-application."

**Verdict:** FIXED correctly. The `resolved_terms` set is the right mechanism.

### E6. Clock skew and timezone handling — RESOLVED CORRECTLY

New Section 19 explicitly addresses this: "All timestamps in the database are stored as UTC using ISO 8601 format." Thread expiry uses `datetime('now')` which is always UTC in SQLite. The UI layer converts to local time for display.

**Verdict:** FIXED correctly. UTC throughout is the right call.

### E7. Database corruption recovery — RESOLVED CORRECTLY

New Section 18 covers WAL mode protection, startup integrity check (`PRAGMA integrity_check(1)`), daily backups via `VACUUM INTO`, and a recovery strategy with 4 levels (WAL auto-recovery, backup restore, profile import, fresh start).

**Verdict:** FIXED correctly. Comprehensive recovery strategy.

### E8. Cold start is really cold — NOT ADDRESSED

The spec still projects 50 dictations of "all unknown" with no seed clusters. Section 12.1 explicitly states "No Seed Clusters -- Fully Organic Growth." The previous review recommended optional pre-loaded seed clusters (R10). This was not implemented.

This is a defensible design choice (universality over convenience), but the cold start period remains long for casual users.

**Verdict:** NOT FIXED. Deliberate design decision. Acceptable but could improve first-run experience.

### A1. Single-threaded SQLite / no WAL — RESOLVED CORRECTLY

Section 15.1 now explicitly sets `PRAGMA journal_mode = WAL` with a comment explaining concurrent reads during writes. The spec also adds `PRAGMA synchronous = NORMAL`, `PRAGMA cache_size = -64000`, and `PRAGMA temp_store = MEMORY`.

**Verdict:** FIXED correctly. WAL + NORMAL sync + 64MB cache is the right configuration for this workload.

### A2. Bigram explosion in co-occurrence pairs — NOT ADDRESSED

Bigram-to-bigram co-occurrence is still stored. Section 11.3 mitigates via batch INSERT and daily pruning, but does not reduce the fundamental O(T^2) pair generation where T includes bigrams.

**Verdict:** NOT FIXED. The mitigations (pruning, emergency cap at 200K) keep it manageable, but the quadratic growth with bigrams is a latent scalability concern. Acceptable for v1's expected scale.

### A3. Single global 0.6 confidence threshold — NOT ADDRESSED

Section 4 still uses a single 0.6 threshold for all levels. The previous review recommended per-level thresholds (0.8 for silent local application, 0.5 for LLM-influencing). This was not implemented.

**Verdict:** NOT FIXED. Remains a correctness risk — Levels 1-2 apply terms silently and should have a higher bar. Recommend fixing before implementation.

### A4. No observability/debugging hooks — NOT ADDRESSED

No `resolution_log` table or debug mode was added. The spec still lacks any mechanism to understand why a term was resolved a particular way.

**Verdict:** NOT FIXED. This will make debugging the system very difficult during development and tuning. Recommend adding before implementation.

### A5. Useless index on corrections — RESOLVED

Section 15.2 still has `CREATE INDEX idx_corrections_pattern ON corrections(raw_text, corrected_text)` but the LIKE queries that made it useless are gone (W6 fix). However, there is no query in the spec that uses this index. The `correction_counts` table handles auto-promotion. The `corrections` table is queried by... nothing in the spec's code examples.

**Verdict:** PARTIALLY FIXED. The dangerous LIKE query is gone, but the index is now orphaned — no code path uses it. Should either remove the index or add a query that benefits from it (e.g., correction history display by raw_text).

---

## Summary of Previous Fix Verification

| Issue | Status | Notes |
|-------|--------|-------|
| W1 (no lemmatization) | FIXED | Minor: tree_stem PyPI availability unclear |
| W2 (string cluster IDs) | FIXED | Correctly uses integer IDs |
| W3 (dual-direction storage) | FIXED | Canonical order + reverse index |
| W4 (cold_start app bias) | PARTIAL | Hard filter/fallback, not weighted |
| W5 (confidence formula) | FIXED | hits >= 2 minimum |
| W6 (LIKE correction) | FIXED | correction_counts table |
| W7 (thread expiry) | FIXED | Lazy evaluation documented |
| W8 (VACUUM blocking) | FIXED | Idle-time scheduling |
| E1 (language switching) | FIXED | Code-switching handled |
| E2 (rapid app switch) | NOT FIXED | Known limitation |
| E3 (multi-thread per app) | NOT FIXED | Known limitation |
| E4 (sensitive metadata) | FIXED | Documented in Section 17 |
| E5 (dict conflicts) | FIXED | resolved_terms set |
| E6 (clock skew) | FIXED | UTC throughout |
| E7 (corruption recovery) | FIXED | Section 18 |
| E8 (cold start) | NOT FIXED | Design decision |
| A1 (no WAL) | FIXED | Section 15.1 |
| A2 (bigram explosion) | NOT FIXED | Mitigated via pruning |
| A3 (single threshold) | NOT FIXED | Risk for Levels 1-2 |
| A4 (no observability) | NOT FIXED | Debugging will be hard |
| A5 (useless index) | PARTIAL | Index now orphaned |

**Score: 13/20 fully fixed, 2 partially fixed, 5 not fixed (3 are deliberate design decisions, 2 are genuine gaps).**

---

## New Issues Found

### N1. `tree_stem` is NOT a PyPI package — dependency is unresolvable as written [BLOCKING]

The spec writes `from tree_stem import stem_uk` (Section 11.1) and describes `tree_stem` as a dependency (~50KB, pure Python). However, research confirms that `tree_stem` is NOT published on PyPI. The [stemmers_ukrainian GitHub repository](https://github.com/amakukha/stemmers_ukrainian) provides the source code as `src/tree_stem.py`, but there is no `setup.py`, `pyproject.toml`, or PyPI package.

This means:
- `pip install tree-stem` will fail
- PyInstaller cannot find the module via standard import
- The spec's "no binary dependencies" claim is correct (it IS pure Python), but the installation path is undefined

**Fix:** Either (a) vendor the `tree_stem.py` file directly into `src/context/` (it is a single ~48KB file), or (b) fork and publish to PyPI under the project's namespace. Option (a) is simpler and aligns with the "minimal dependencies" goal. Document the vendoring in the file header with the source URL and license.

### N2. `stem_uk()` can produce collision stems that merge unrelated words [MEDIUM]

The `tree_stem` benchmarks show an overstemming index of 2.71e-06, which is extremely low — but the ERRT of 0.125 means roughly 1 in 8 word-pairs will have a stemming error relative to truncation. More importantly, the benchmarks were run on a dictionary of word forms, not on the mixed Ukrainian/English/transliterated vocabulary this app processes.

The spec's `lemmatize()` function applies `stem_uk()` to ANY word containing Cyrillic characters. But consider Ukrainian IT loanwords that are written in Cyrillic:
- "деплой" (deploy), "деплою" (I deploy), "деплоїти" (to deploy) — will these all stem to the same root?
- "рефакторинг" vs "рефакторити" — the stemmer was trained on native Ukrainian vocabulary, not transliterated English tech terms

If `stem_uk("деплой")` and `stem_uk("деплою")` produce different stems, the co-occurrence graph fragments for the most important vocabulary (IT loanwords), which is exactly the domain this app targets.

**Fix:** Add a unit test suite for the 20 most common IT loanwords in their inflected forms. If `tree_stem` fails on these, add a pre-stemming lookup table for known loanword stems (e.g., `{"деплой*": "деплой", "рефактор*": "рефактор"}`). This is a small table (~50 entries) that handles the highest-value vocabulary.

### N3. `name_cluster()` query is biased — only counts `term_a` occurrences [MEDIUM]

Section 12.2:
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

Because pairs are stored in canonical order (`term_a < term_b`), terms that sort early in the alphabet appear more often as `term_a` and less often as `term_b`. This query only counts `term_a` appearances, so it is biased toward alphabetically early terms.

Example: the term "auth" (sorts early) always appears as `term_a` in pairs like ("auth", "deploy"), ("auth", "git"), ("auth", "замок"). But "замок" (sorts late in Unicode, Cyrillic > Latin) almost never appears as `term_a` — it is always `term_b`. So "замок" will never show up in the cluster display name, even if it has the highest total weight across both columns.

**Fix:** Use a UNION query or aggregate both columns:
```sql
SELECT term, SUM(total) as weight FROM (
    SELECT term_a AS term, SUM(weight) AS total
    FROM term_cooccurrence WHERE cluster_id = ?
    GROUP BY term_a
    UNION ALL
    SELECT term_b AS term, SUM(weight) AS total
    FROM term_cooccurrence WHERE cluster_id = ?
    GROUP BY term_b
) GROUP BY term ORDER BY weight DESC LIMIT 3
```

### N4. `detect_cluster()` query does not apply temporal decay [MEDIUM]

Section 12.3 `detect_cluster()` sums raw weights without temporal decay:
```python
scores = db.query(f"""
    SELECT cluster_id, SUM(weight) as score
    FROM term_cooccurrence
    WHERE term_a IN ({placeholders}) OR term_b IN ({placeholders})
    GROUP BY cluster_id
    ORDER BY score DESC
""", [*keywords, *keywords])
```

But Section 6.4 demonstrates that temporal decay is critical for accurate resolution (the "zamok" example where IT usage was months ago but household usage is recent). The cluster detection query ignores decay entirely, meaning a cluster with ancient high-weight edges will dominate even when the user has shifted to a different domain.

This is inconsistent: term resolution (Section 6.4) uses decay, but cluster detection (Section 12.3) does not.

**Fix:** Apply the same decay formula:
```sql
SELECT cluster_id,
       SUM(weight * (1.0 / (julianday('now') - julianday(last_used) + 1))) as score
FROM term_cooccurrence
WHERE term_a IN (...) OR term_b IN (...)
GROUP BY cluster_id
ORDER BY score DESC
```

### N5. `should_update_cooccurrence()` does not apply temporal decay either [LOW]

Section 6.3.1 uses raw `SUM(weight)` to determine if a dictation is mixed-topic. The same decay inconsistency as N4 applies. If an old cluster has accumulated huge weight, even a clearly single-topic dictation about a different cluster could appear "mixed" because the old cluster's raw weight competes with the current one.

**Fix:** Apply decay consistently across all co-occurrence queries.

### N6. `VACUUM INTO` in daily maintenance creates the backup file — but never deletes old ones [LOW]

Section 13.2:
```python
backup_path = config.db_path + ".bak"
db.execute(f"VACUUM INTO '{backup_path}'")
```

`VACUUM INTO` requires the target file to either not exist or be empty. If this runs daily, the second run will fail because `config.db_path + ".bak"` already exists from yesterday. The spec needs to either (a) delete the old backup before creating a new one, or (b) use timestamped backup filenames.

Additionally, the backup path is interpolated directly into the SQL string (`f"VACUUM INTO '{backup_path}'"`) instead of using a parameter. If `config.db_path` contains a single quote (unlikely but possible on Windows), this is a SQL injection vector.

**Fix:**
```python
import os
backup_path = config.db_path + ".bak"
if os.path.exists(backup_path):
    os.remove(backup_path)
db.execute("VACUUM INTO ?", [backup_path])
```

Note: Verify that SQLite supports parameterized `VACUUM INTO`. If not, use proper escaping.

### N7. Fingerprint creation only captures first message keywords [LOW]

Section 7.3 `on_thread_expired()`:
```python
first_msg = get_first_message(thread.id)
keywords = extract_keywords(first_msg)
```

Only the first message's keywords are stored in the fingerprint. But the cluster was determined from the full conversation. Consider: a thread opens with "привіт, як справи?" (hello, how are you?) — keywords: ["справ"]. The conversation then develops into an IT discussion. The fingerprint stores cluster=IT with keywords=["справ"], which is useless for future cold-start matching.

The previous review did not catch this because the Section 7.2 description says fingerprints store "opening keywords" by design. But the rationale ("conversations that started like X turned out to be about Y") only works if the opening keywords are distinctive. Generic greetings are not distinctive.

**Fix:** Store keywords from the first N messages (e.g., first 3) or from the first message that contains >= 2 non-greeting keywords. This gives the fingerprint more signal while still capturing the "conversation opening" intent.

### N8. The `warm_cache()` function does not actually warm the relevant cache pages [LOW]

Section 13.2:
```python
def warm_cache():
    """Pre-load frequently accessed tables into SQLite page cache."""
    db.execute("SELECT COUNT(*) FROM term_cooccurrence")
    db.execute("SELECT COUNT(*) FROM conversation_threads WHERE is_active = 1")
    db.execute("SELECT COUNT(*) FROM fingerprint_keywords")
```

`SELECT COUNT(*)` in SQLite can be satisfied by scanning an index (often the primary key index), not the full table data pages. This means the data pages that actual lookup queries will need (`weight`, `last_used`, `cluster_id` columns in `term_cooccurrence`) may NOT be loaded into the page cache.

A more effective warming strategy would run queries that touch the actual columns used in hot-path lookups:
```python
db.execute("SELECT term_a, term_b, cluster_id, weight, last_used FROM term_cooccurrence LIMIT 10000")
db.execute("SELECT id, app, cluster_id, last_message FROM conversation_threads WHERE is_active = 1")
```

This is a minor optimization issue, not a correctness bug.

**Verdict:** Low priority. The 64MB cache will warm naturally after a few dictations.

---

## Consistency Check

### SQL Schema vs Code Examples

I cross-checked every SQL table definition in Section 15.2 against every code example that references those tables.

| Check | Result | Notes |
|-------|--------|-------|
| `clusters` table definition matches Section 6.2 | MATCH | Both use `id INTEGER PRIMARY KEY AUTOINCREMENT, display_name TEXT` |
| `term_cooccurrence` PK matches Section 6.3 UPSERT | MATCH | `ON CONFLICT(term_a, term_b, cluster_id)` aligns with `PRIMARY KEY (term_a, term_b, cluster_id)` |
| `conversation_threads.cluster_id` type matches Section 5.4 | MATCH | `INTEGER REFERENCES clusters(id)` in both |
| `thread_keywords` PK matches Section 5.4 insert logic | MATCH | `PRIMARY KEY (thread_id, keyword)` |
| `correction_counts` in Section 10.2 matches Section 15.2 | MATCH | `PRIMARY KEY (old_token, new_token)` in both |
| `conversation_fingerprints.cluster_id` references `clusters(id)` | MATCH | Consistent in both Section 7.2 and 15.2 |
| `history.thread_id` nullable matches Section 5.2 orphan logic | MATCH | Code returns `None`, column has no `NOT NULL` constraint |
| `cluster_llm_stats` in Section 10.4 matches Section 15.2 | MATCH | Both have `cluster_id INTEGER PRIMARY KEY REFERENCES clusters(id)` |
| `dictionary` in Section 8.4 matches Section 15.2 | MATCH | Identical schemas |
| `corrections` in Section 10.3 matches Section 15.2 | MATCH | Identical schemas |

**All schema definitions are consistent across sections.**

### MISMATCH: `idx_corrections_pattern` index has no corresponding query

Section 15.2 defines:
```sql
CREATE INDEX idx_corrections_pattern ON corrections(raw_text, corrected_text);
```

No code example in the spec queries `corrections` by `raw_text` or `corrected_text`. The LIKE queries that originally justified this index (old Section 10.2) were replaced with the `correction_counts` table. This index is dead weight.

### Section Number Cross-References

| Reference | Target | Valid? |
|-----------|--------|--------|
| Section 3.2: "4-level resolution (see Section 4)" | Section 4 exists | YES |
| Section 3.2: "Assemble LLM system prompt (see Section 5)" | Section 5 is Conversation Threads, NOT prompt assembly | **WRONG** — should reference Section 9 |
| Section 4: "Level 4: ~5-10% of cases" | Section 4 text matches | YES |
| Section 5.2: "see Section 13" for daily pruning | Section 13.2 has daily maintenance | YES |
| Section 6.3: "Lookup queries check BOTH directions (see Section 6.4)" | Section 6.4 has OR clause | YES |
| Section 8.2: "Applied in Stage 6 (post-LLM)" | Section 3.1 Stage 6 matches | YES |
| Section 11.3: "see Section 13" for daily pruning | Section 13.2 matches | YES |
| Section 13.2: "see Section 13.3" for profile export | Section 13.3 exists | YES |
| Section 18.2: "Section 13.2" for backup | Section 13.2 has VACUUM INTO backup | YES |

**One cross-reference error found:** Section 3.2 says "Assemble LLM system prompt (see Section 5)" but Section 5 is "Conversation Threads." The prompt assembly is in Section 9. This should read "(see Section 9)."

### Token Budget Discrepancy

Section 9.2 states total per request is ~160-245 tokens. Section 14.2 states 0-chat average is ~260 tokens, 1000-chat average is ~190 tokens. The 260 figure exceeds the 245 upper bound from Section 9.2. This is because at 0 chats, the LLM receives more unresolved term candidates (all terms are unresolved). The Section 9.2 budget should note that the upper bound applies to steady state and can be exceeded during cold start.

---

## Research Validation

### 1. tree_stem Ukrainian Stemmer

**Quality:** tree_stem achieves ERRT of 0.125 (best among stemmers, better than pymorphy2's 0.391) and understemming index of 0.0907 (lowest among stemmers). The overstemming index is 2.71e-06, meaning false merges are extremely rare. These benchmarks come from the [stemmers_ukrainian repository](https://github.com/amakukha/stemmers_ukrainian).

**Performance:** 24x faster than lemmatization (pymorphy2), consistent with the spec's <1ms target.

**Limitations:** (a) Not on PyPI — must be vendored. (b) Trained on a dictionary of native Ukrainian word forms — behavior on transliterated IT loanwords (the most important vocabulary for this app) is unknown and untested. (c) The ERRT of 0.125 means ~12.5% of word-pairs have stemming errors relative to truncation. For co-occurrence graph construction, this translates to some fragmentation.

**Alternatives:** pymorphy3 (pure Python, on PyPI, provides full lemmatization with POS tags) is more accurate but 24x slower. For the spec's <1ms budget, tree_stem is the correct choice, but it should be supplemented with a small loanword override table.

**Verdict:** Correct choice with a known gap on loanwords (see N2).

### 2. Canonical Ordering for Co-occurrence Pairs

**Standard practice:** Yes. Storing symmetric co-occurrence matrices as upper-triangle-only (where index_a < index_b) is a well-established technique in NLP. The [quanteda R package](https://quanteda.io/reference/fcm.html) uses `tri = TRUE` for this purpose. Academic literature confirms: "The upper and lower triangles of the matrix are identical since co-occurrence is a symmetric relation." ([ACL 2008 case study](https://aclanthology.org/D08-1044.pdf)).

The spec's approach of lexicographic ordering (`term_a < term_b`) with two indexes (forward and reverse) is the correct adaptation of this principle for a relational database.

**Verdict:** Standard, well-validated approach. Correctly implemented.

### 3. Cluster Stable IDs vs String Names

**Best practice:** AWS graph data modeling guidelines recommend ["supplying your own IDs when creating vertices"](https://aws-samples.github.io/aws-dbs-refarch-graph/src/graph-data-modelling/) using stable domain attributes. Neo4j documentation warns that [internal database-generated IDs are volatile](https://neo4jrb.readthedocs.io/en/stable/UniqueIDs.html) and "may be reused or change throughout a database's lifetime." The Graph Protocol [recommends immutable IDs](https://thegraph.com/docs/en/subgraphs/best-practices/immutable-entities-bytes-as-ids/) for indexing performance.

The spec's approach (auto-increment integer IDs with separate mutable display names) correctly separates identity from presentation. The use of `AUTOINCREMENT` in SQLite guarantees IDs are never reused (unlike the default `ROWID` behavior).

**Verdict:** Correct and well-aligned with industry best practices.

### 4. Lazy vs Eager Thread Expiry

**Standard practice:** Both approaches are used in industry. Eager expiry (background timer) is standard for security-sensitive session management (OWASP [recommends server-side enforcement](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/06-Session_Management_Testing/07-Testing_Session_Timeout)). Lazy expiry (check on access) is standard for non-security contexts where simplicity matters — ASP.NET Core's session middleware [resets timeout on each request](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/app-state?view=aspnetcore-8.0), effectively implementing lazy expiry.

For this spec's use case (conversation thread continuity, not security), lazy expiry is the simpler and correct choice. There is no security risk from a thread being "alive" slightly longer than 15 minutes — it just means one extra dictation might match the old thread, which is likely the correct behavior anyway.

**Verdict:** Lazy expiry is the right choice for this use case. Correctly implemented.

---

## Final Assessment

### Ready for Implementation?

**Almost.** The spec is well-structured, internally consistent (with one cross-reference error), and addresses the majority of the first review's concerns correctly. The architecture is sound and backed by relevant research.

### Blocking Issues (must fix before implementation)

1. **N1: `tree_stem` is not on PyPI.** The import path `from tree_stem import stem_uk` will fail. Decision needed: vendor the file or publish to PyPI. This is a 10-minute fix but blocks the entire keyword extraction pipeline.

2. **A3 (unfixed): Single global 0.6 confidence threshold.** Levels 1-2 silently apply terms without LLM verification. A false positive at Level 1 or 2 is an uncorrectable error that the user may not notice. These levels need a higher threshold (0.75-0.8). Level 3 only influences the LLM prompt and can afford a lower threshold (0.5). This is a 5-minute config change but has significant impact on accuracy.

### Should-Fix Before Implementation

3. **N3: `name_cluster()` alphabetic bias.** Cyrillic terms will never appear in cluster display names because they sort after Latin characters. This makes the UI useless for Ukrainian-dominant users. Fix: UNION query counting both columns.

4. **N4: `detect_cluster()` missing temporal decay.** Inconsistent with the core decay philosophy. Old clusters will dominate even when the user has shifted domains.

5. **A4 (unfixed): No observability.** Without a resolution log, developers cannot tune thresholds, debug incorrect resolutions, or measure accuracy improvements over time. At minimum, add a `resolution_log` table before the first beta.

### Nice-to-Have

6. N2: Loanword stemming validation (unit test suite)
7. N5: Decay in `should_update_cooccurrence()`
8. N6: Backup file deletion before `VACUUM INTO`
9. N7: Multi-message fingerprint keywords
10. N8: Better cache warming
11. Section 3.2 cross-reference fix (Section 5 -> Section 9)
12. Remove orphaned `idx_corrections_pattern` index
13. Token budget upper bound note for cold start

### Overall Quality

The spec is above the bar for implementation. The first review raised 20 issues; 13 were fully fixed, 2 partially, and the 5 remaining unfixed items include 3 deliberate design decisions. This second pass found 8 new issues, 2 of which are blocking. After addressing the 2 blocking items and the 3 should-fix items, the spec is ready for implementation.

---

Sources:
- [stemmers_ukrainian (tree_stem) GitHub](https://github.com/amakukha/stemmers_ukrainian)
- [Co-occurrence Matrix - Wikipedia](https://en.wikipedia.org/wiki/Co-occurrence_matrix)
- [ACL 2008: Computing Word Co-occurrence Matrices](https://aclanthology.org/D08-1044.pdf)
- [quanteda Feature Co-occurrence Matrix](https://quanteda.io/reference/fcm.html)
- [AWS Graph Data Modelling Best Practices](https://aws-samples.github.io/aws-dbs-refarch-graph/src/graph-data-modelling/)
- [Neo4j Unique IDs](https://neo4jrb.readthedocs.io/en/stable/UniqueIDs.html)
- [The Graph: Immutable Entities and Bytes as IDs](https://thegraph.com/docs/en/subgraphs/best-practices/immutable-entities-bytes-as-ids/)
- [OWASP Session Timeout Testing](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/06-Session_Management_Testing/07-Testing_Session_Timeout)
- [ASP.NET Core Session Management](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/app-state?view=aspnetcore-8.0)
- [SQLite VACUUM Documentation](https://sqlite.org/lang_vacuum.html)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [pymorphy3 GitHub](https://github.com/no-plagiarism/pymorphy3)
- [Co-occurrence Matrices in NLP - Spot Intelligence](https://spotintelligence.com/2024/04/04/co-occurrence-matrices/)

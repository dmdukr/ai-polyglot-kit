# AI Polyglot Kit v6.0 - Context Engine Review and Recommendations

**Date:** 2026-03-28
**Status:** Review memo
**Scope:** Review of `2026-03-28-context-engine-architecture.md` plus external research on lightweight word sense disambiguation, streaming inverse text normalization, and hybrid retrieval/reranking pipelines.

---

## 1. Executive Verdict

The current Context Engine spec is directionally strong for a v6 MVP. The core idea to keep context resolution local, privacy-preserving, and SQLite-based is sound.

However, the **co-occurrence graph should not be the sole reasoning substrate**. The best practical design for this product is a **hybrid pipeline**:

1. **Deterministic local normalization** for categories that should not require semantic guessing.
2. **Cheap local retrieval and evidence gathering** from threads, corrections, fingerprints, app priors, and term graph.
3. **Candidate ranking / reranking** for ambiguous terms instead of stopping at the first source that crosses a threshold.
4. **LLM fallback** only when local evidence is weak or conflicting.

In short: **do not replace the graph; demote it from "the resolver" to one evidence source in a layered resolver**.

---

## 2. What Research Suggests

### 2.1 Main conclusion

The literature does not point to a single universally better replacement for graphs. It points to **hybrid systems** that combine:

- structured knowledge or graph information,
- contextual encoders or gloss-based candidate scoring,
- retrieval before fine discrimination,
- deterministic transduction for safe normalization classes.

### 2.2 Most relevant external patterns

**A. Hybrid tagger + WFST / rules is strongest for deterministic normalization**

- Microsoft "Streaming, fast and accurate on-device Inverse Text Normalization for ASR" uses a **streaming tagger** to detect where transformation is needed and applies **category-specific WFST** only on tagged spans.
- The 2025 dynamic streaming ITN paper extends the same general idea: **contextual tagging + deterministic transduction/postprocess**, with explicit emphasis on low latency and preservation of source text.

**Implication for this project:** numbers, dates, phone numbers, currencies, and much punctuation should stay out of the semantic graph path as much as possible.

**B. Retrieval-then-rerank beats flat one-shot scoring for ambiguity**

- BEM (Gloss-Informed Bi-encoders) frames WSD as finding the nearest sense embedding to a context embedding.
- SANDWiCH (2025) explicitly splits the problem into **coarse sense retrieval** followed by **cluster discrimination**, and shows strong gains on rare and out-of-domain senses.

**Implication for this project:** for ambiguous terms, the right abstraction is not "which cluster wins first" but "which candidate meaning survives retrieval and ranking given multiple evidence sources".

**C. Graphs help, but mostly when combined with richer context representations**

- EWISER and later hybrid WSD systems improve performance by injecting knowledge graph information into a neural or encoder-based architecture.
- The common research pattern is not graph-only. It is **graph plus contextual scoring**.

**Implication for this project:** the graph is valuable for priors, neighbor evidence, and explainability, but not as the final decider for all cases.

---

## 3. Recommended Target Architecture

### 3.1 Recommended stack

Use this local decision stack for each dictation:

1. **Deterministic pass**
   - exact dictionary terms
   - number/date/currency formatting
   - safe punctuation and capitalization rules

2. **Ambiguous term candidate generation**
   - dictionary sense inventory
   - thread context
   - fingerprint retrieval
   - co-occurrence graph
   - correction store
   - app prior

3. **Evidence fusion / ranking**
   - score all candidate meanings together
   - require a minimum confidence **and** minimum margin over runner-up
   - abstain when evidence conflicts

4. **Optional local reranker (later phase)**
   - small bi-encoder or cross-encoder over `(context, candidate gloss)`
   - only for high-value ambiguous terms if data justifies it

5. **LLM fallback**
   - send only top 2-3 candidate meanings with glosses and scores
   - do not ask the LLM to search the full meaning space

### 3.2 Key change from the current spec

The current design says "try Level 1, then Level 2, then Level 3, stop at first confident result".

That should change to:

> gather evidence from all cheap local sources, then rank candidates once.

This is the single most important recommendation in the whole review.

---

## 4. Priority Recommendations

## P0 - Change before implementation

### 4.1 Replace first-hit resolution with fused candidate scoring

**Problem in current spec:**

- a weak but early signal can win too soon;
- signals from self-context, thread, fingerprint, and corrections are complementary but currently not combined;
- confidence formulas are absolute, not comparative.

**Recommendation:**

Represent each ambiguous term as candidate meanings:

```text
zamok:
  - mutex_lock
  - door_lock
  - castle
```

Then compute one final score per candidate, for example:

```text
score(candidate) =
  self_context_score
  + active_thread_score
  + fingerprint_score
  + correction_prior
  + app_prior
  + recency_bonus
  - contradiction_penalty
```

Accept only if:

- `top_score >= accept_threshold`, and
- `top_score - second_score >= margin_threshold`, and
- evidence count is above a minimum floor.

If not, escalate.

### 4.2 Add a sense inventory table

The current spec models ambiguity mostly through clusters. That is not enough.

You need a table closer to this:

```sql
CREATE TABLE term_senses (
    id INTEGER PRIMARY KEY,
    term TEXT NOT NULL,
    sense_key TEXT NOT NULL,          -- e.g. 'door_lock'
    gloss TEXT NOT NULL,              -- short human-readable meaning
    cluster TEXT NOT NULL,
    aliases TEXT,
    is_active BOOLEAN DEFAULT 1,
    UNIQUE(term, sense_key)
);
```

Why this matters:

- LLM prompts become precise.
- Corrections can update a specific sense, not just a cluster.
- Retrieval/reranking becomes possible.
- You can handle more than two meanings per term.

### 4.3 Do not use CSV + LIKE as the main retrieval substrate

The current spec uses `keywords TEXT` and `opening_keywords TEXT` with `LIKE '%kw%'` search.

That has three serious issues:

1. poor scaling,
2. poor ranking quality,
3. mismatch between expected and actual SQLite index usage.

`LIKE '%kw%'` does not benefit meaningfully from a normal B-tree index.

**Recommendation:**

- use **SQLite FTS5** for thread/fingerprint search, or
- use normalized keyword tables.

For example:

```sql
CREATE VIRTUAL TABLE fingerprint_fts USING fts5(
    fingerprint_id UNINDEXED,
    opening_text,
    app,
    content=''
);
```

For the stated constraints, FTS5 is still "pure SQLite" and is a much better fit than CSV substring search.

### 4.4 Add abstain logic and uncertainty calibration

Current confidence formulas are too optimistic:

- `min(weight / 5.0, 1.0)`
- `hits / total_fingerprints`
- `min(thread.message_count / 3.0, 1.0)`

These are useful starting heuristics, but they are not calibrated.

**Recommendation:**

- add `margin`, `evidence_count`, and `source_diversity` to the decision rule;
- log false accepts and false abstains from user corrections;
- tune thresholds from real data instead of fixing them upfront in the spec.

### 4.5 Build an offline evaluation harness before auto-learning goes live

The spec has performance projections, but it needs explicit quality evaluation.

Add a benchmark harness with labeled cases:

- ambiguous terms in short messages,
- ambiguous terms in ongoing threads,
- first-message cold starts,
- code/editor vs messenger vs household contexts,
- correction replay.

Minimum metrics:

- top-1 local resolution accuracy,
- abstain rate,
- false accept rate,
- LLM fallback rate,
- median and p95 latency.

Without this, the learning loop will be hard to trust.

## P1 - Strongly recommended for v6.0 or v6.1

### 4.6 Split deterministic ITN from semantic disambiguation

The spec already moves numbers to local post-processing. Push this idea further.

Create a separate deterministic category layer for:

- numbers,
- dates,
- currencies,
- phone numbers,
- stable punctuation patterns,
- exact dictionary terms.

Do not force these through the context engine when the transformation is category-safe.

This follows the strongest production pattern in on-device ITN research.

### 4.7 Add a small right-context revision buffer

The spec currently treats dictations as discrete finalized inputs. In practice, ambiguity often resolves one or two tokens later.

Examples:

- "key" vs "house key"
- "lock" vs "auth lock"
- punctuation after clause completion

**Recommendation:**

- keep a tiny right-context buffer or allow a local revision window on the last unresolved span;
- especially useful for streaming STT or chunked providers.

This is one of the most valuable ideas from recent streaming ITN work.

### 4.8 Use the correction store as retrieval memory, not only as graph updater

The spec already has a correction triad design in the parent v6 spec. Integrate it directly into the Context Engine.

For ambiguous terms, retrieve:

- similar raw phrases,
- similar opening messages,
- same app + same term + same nearby keywords,
- recent corrections involving the same term.

This can start with lexical retrieval only:

- FTS5 BM25,
- app filter,
- recency reweighting.

Embeddings can stay optional for later.

### 4.9 Separate strategy by ambiguity type

Not all ambiguous items are the same.

Recommended routing classes:

- **deterministic formats**: numbers, dates, phones, money
- **technical jargon / transliterations**: Python, React, API key, branch
- **common polysemous nouns**: lock, key, root, branch
- **person / project / local names**: best learned from corrections/history

This routing will outperform a single generic scoring formula.

## P2 - Good follow-up improvements

### 4.10 Replace raw co-occurrence counts with association strength

Raw frequency is vulnerable to generic high-frequency terms.

Prefer one of:

- PMI-like score,
- log-scaled counts,
- TF-IDF-style downweighting for generic neighbors,
- cluster-normalized edge weights.

This is especially important once the graph grows.

### 4.11 Support optional cross-app carryover

Current spec keeps threads app-local. That is safe, but sometimes too strict.

Recommended compromise:

- threads remain app-scoped,
- but app-independent **topic prior** can be consulted when apps change within a short time window.

Example: user talks about deploy in Telegram, then switches to VS Code two minutes later.

This should be an opt-in heuristic, not the default thread identity rule.

---

## 5. Section-by-Section Review

### 5.1 Section 4 - Four-Level Term Resolution

**What is good:**

- clear progressive fallback,
- cheap local sources first,
- explicit fast path.

**What should change:**

- do not stop after the first source crosses a threshold;
- use candidate ranking from all local evidence;
- reserve sequential fallback only for expensive stages.

**Concrete change:**

Replace "Level 1/2/3 accept if confidence >= 0.6" with:

```text
Level 1/2/3 all contribute evidence.
If combined score is decisive, resolve locally.
If not decisive, escalate.
```

### 5.2 Section 5 - Conversation Threads

**Risk:** keyword overlap `>= 2` is too brittle.

Failure modes:

- short messages,
- morphological variants,
- transliteration variants,
- topic drift within a thread.

**Recommendation:**

- use weighted overlap or BM25 instead of fixed overlap count;
- include app prior and recency;
- store top keywords with weights, not only flat CSV.

### 5.3 Section 6 - Co-occurrence Graph

**Risk 1:** reverse-edge duplication doubles writes and storage.

If the graph is logically undirected, store canonical pairs:

```text
min(term_a, term_b), max(term_a, term_b)
```

If directional evidence matters, then document why and separate directional semantics explicitly.

**Risk 2:** decay inside every query may become expensive.

Recommendation:

- keep `last_used`,
- compute a cached decay bucket or lightweight exponential recency factor,
- benchmark before locking the formula.

**Risk 3:** graph edges alone cannot represent mutually exclusive senses cleanly.

This is another reason to add `term_senses`.

### 5.4 Section 7 - Conversation Fingerprints

This section has the right product intuition but the wrong storage/query shape.

**Recommendation:**

- replace `opening_keywords LIKE '%kw%'` with FTS5 or normalized rows;
- store opening text from first 1-2 messages, not only extracted keywords;
- score by lexical similarity + recency + app prior.

### 5.5 Section 8 - Dictionary Integration

The split into `exact` vs `context` is correct.

But `context` terms should not live only as graph behavior. They need explicit senses.

Recommended evolution:

- `dictionary` keeps term ownership and UI metadata,
- `term_senses` stores possible meanings,
- graph stores neighborhood evidence,
- corrections adjust priors and examples.

### 5.6 Section 9 - LLM Prompt Assembly

Good direction overall. Two changes recommended:

1. Send **candidate senses with glosses**, not only cluster names.
2. Include confidence hints, for example:

```text
Term: zamok
Candidates:
- door_lock | household door lock | score 0.71
- mutex_lock | software lock / synchronization primitive | score 0.54
Prefer local evidence over translation if uncertain.
```

This makes the LLM a resolver among shortlisted options, not an unconstrained guesser.

### 5.7 Section 10 - Learning from Corrections

This is one of the strongest parts of the overall design, but one rule is too aggressive:

> same correction 3+ times -> promote to exact term

That can produce bad promotions for context-dependent terms.

**Recommendation:**

Promote to exact only if all are true:

- at least 5 consistent corrections,
- cluster purity above threshold,
- no contradictory correction in recent window,
- app distribution not highly mixed unless the term is clearly global.

### 5.8 Section 11 - Keyword Extraction

For MVP, the rule-based extractor is acceptable.

But for Ukrainian/Russian mixed dictation with English technical terms, add these improvements:

- light lemmatization or stemming where practical,
- transliteration normalization,
- snake_case / camelCase decomposition for technical tokens,
- mixed-script normalization (`ріакт`, `react`, `реакт`).

Without this, thread matching and graph learning will fragment.

### 5.9 Section 12 - Cluster Detection

Seed clusters are useful as priors, but avoid making them the primary semantic object.

Cluster is good for:

- routing,
- priors,
- analytics,
- UI summaries.

Sense is better for:

- final resolution,
- corrections,
- LLM prompt candidates.

### 5.10 Section 13 - Performance Claims

The latency target is plausible, but only if retrieval is redesigned.

The current claim that fingerprint search is `~2ms` with `LIKE` on `opening_keywords` is optimistic.

With FTS5 and prepared statements, the target becomes realistic again.

### 5.11 Section 14 - SQLite Schema

Main schema issue: too many CSV text columns for things that will be queried semantically.

Recommended additions:

```sql
CREATE TABLE term_senses (...);
CREATE TABLE thread_keywords (...);
CREATE TABLE fingerprint_keywords (...);
CREATE VIRTUAL TABLE thread_fts USING fts5(...);
CREATE VIRTUAL TABLE fingerprint_fts USING fts5(...);
```

### 5.12 Section 15 - File Structure

Recommended additions:

```text
src/
  context/
    senses.py          # sense inventory, candidate lookup
    scorer.py          # fused evidence scoring
    retrieval.py       # FTS5/BM25 retrieval for threads/fingerprints/corrections
    resolver.py        # orchestration for candidate generation -> scoring -> abstain
```

This will keep `engine.py` and `pipeline.py` clean.

---

## 6. Suggested Revised Resolution Flow

```python
def resolve_term(term: str, text: str, app: str) -> Resolution:
    candidates = sense_inventory.get_candidates(term)
    if not candidates:
        return Resolution.unknown(term)

    evidence = collect_evidence(
        text=text,
        app=app,
        active_thread=find_active_thread(text, app),
        fingerprints=retrieve_fingerprints(text, app),
        corrections=retrieve_similar_corrections(text, term, app),
        cooccurrence=graph.lookup(term, extract_keywords(text)),
    )

    ranked = score_candidates(candidates, evidence)
    best, second = ranked[0], ranked[1] if len(ranked) > 1 else None

    if is_decisive(best, second, evidence):
        return Resolution.local(best)

    return Resolution.defer_to_llm(ranked[:3])
```

This still matches the product goals:

- local-first,
- cheap,
- explainable,
- SQLite-friendly,
- compatible with later learning.

---

## 7. Recommended Decisions on Open Questions

### 7.1 Cluster naming

Recommendation: keep a **fixed seed vocabulary plus emergent internal cluster ids**.

- UI label can be auto-generated later.
- Internal logic should not depend on human-readable names.

### 7.2 Thread merging

Recommendation: **do not merge in v6.0**.

The complexity and risk of history corruption are not worth it yet.

### 7.3 Cross-app context

Recommendation: **no cross-app thread identity**, but allow **cross-app topic priors** as an optional later heuristic.

### 7.4 Privacy mode

Recommendation: yes, offer a "strict privacy mode" that disables thread/fingerprint intelligence and keeps only exact dictionary + deterministic rules.

### 7.5 Graph pruning

Recommendation: prune stale weak edges, for example:

- weight = 1,
- last_used older than 90 days,
- no supporting correction evidence.

---

## 8. Practical Implementation Plan

### Phase A - Best ROI, low complexity

- keep SQLite,
- add FTS5,
- add `term_senses`,
- replace first-hit resolution with fused scoring,
- integrate correction retrieval into context resolution,
- keep graph as evidence source.

### Phase B - After real data collection

- add calibration from correction logs,
- add better normalization for keywords/transliteration,
- add right-context revision buffer,
- refine scoring weights from offline replay.

### Phase C - Only if needed

- add small local reranker over `(context, candidate gloss)`,
- optionally add embeddings for correction retrieval,
- optionally add app-independent topic priors.

---

## 9. Bottom Line

For this product, a **pure graph approach is not the best end state**.

The strongest architecture is:

**deterministic local rules + retrieval memory + graph evidence + candidate ranking + LLM fallback**.

If you want one concise design change to apply now, make it this:

> replace "four levels with early stop" with "one local evidence fusion stage plus abstain".

That preserves the spec's local-first philosophy while making the resolver more robust, more explainable, and more compatible with future learning from corrections.

---

## 10. External References Reviewed

1. Streaming, fast and accurate on-device Inverse Text Normalization for Automatic Speech Recognition
   - https://arxiv.org/abs/2211.03721
   - Key takeaway: tagging + category-specific WFST is production-friendly for deterministic normalization.

2. Dynamic Context-Aware Streaming Pretrained Language Model For Inverse Text Normalization
   - https://arxiv.org/abs/2505.24229
   - Key takeaway: right context and dynamic chunk-aware revision materially improve streaming normalization quality.

3. Moving Down the Long Tail of Word Sense Disambiguation with Gloss Informed Bi-encoders
   - https://aclanthology.org/2020.acl-main.95/
   - Key takeaway: independent context and gloss encoders with nearest-sense retrieval help rare senses.

4. Breaking Through the 80% Glass Ceiling: Raising the State of the Art in Word Sense Disambiguation by Incorporating Knowledge Graph Information
   - https://aclanthology.org/2020.acl-main.255/
   - Key takeaway: knowledge graph information improves WSD, but as part of a hybrid neural architecture.

5. SANDWiCH: Semantical Analysis of Neighbours for Disambiguating Words in Context ad Hoc
   - https://arxiv.org/abs/2503.05958
   - Key takeaway: coarse retrieval plus cluster discrimination is stronger than direct single-sense scoring on rare and out-of-domain cases.
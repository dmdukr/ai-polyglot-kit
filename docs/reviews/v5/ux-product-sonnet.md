# UX & Product Review v5 — Context Engine Architecture
**Spec:** `2026-03-28-context-engine-architecture.md` (Draft v5)
**Previous review:** `docs/reviews/v4/ux-product-sonnet.md`
**Reviewer:** Claude Sonnet 4.6 (PM/UX perspective)
**Date:** 2026-03-28
**Role assumed:** Non-technical user who just wants to speak and have text come out right.

---

## Previous P0 Verification

Three P0s carried into v5 from prior rounds. Two new UX items were flagged in v4 for tracking (auto-promote toast, privacy screen). All five checked against Draft v5.

---

### P0-1: Offline fallback referenced and named — RESOLVED

**Previous state:** Section 3.1 contained only the parenthetical `(offline)` with no model named, no install flow, no user indicator. Three review rounds could not get a concrete answer.

**Current state (Draft v5):** Section 3.1 now reads:

> "Offline fallback: faster-whisper local model (see parent spec Section 2.15). UI: show "Offline" indicator in recording overlay."

The model is named (`faster-whisper`). The UI behavior is specified (overlay indicator). The full specification is delegated to parent spec Section 2.15, which is an acceptable architectural boundary — this spec does not need to re-document what the parent spec owns.

**Remaining gap (non-blocking):** The cross-reference is one-directional. If a reader encounters Section 3.1 in isolation, "see parent spec Section 2.15" gives no path to find that document. The parent spec filename is not provided. This is an internal documentation issue, not a user-facing gap — does not block shipping.

**Verdict: Resolved. P0 closed.**

---

### P0-2: Cold-start onboarding text defined — RESOLVED

**Previous state (v4):** Section 12.1 described the cold-start period internally ("No degradation — just more LLM calls initially") but specified no user-facing communication. The phrase "no degradation" contradicted the Section 14.2 metrics (20% correction rate, 50% term accuracy at 0 chats).

**Current state (Draft v5):** Section 12.1 now specifies:

> "**First-run onboarding toast:** 'The app learns your vocabulary over time. Accuracy improves with each dictation.'"

The user-facing message is written, its trigger is defined (cold start / first run), and its format is specified (toast).

**Remaining gap (non-blocking):** The toast is a single-line message shown once. It communicates that learning happens; it does not set a concrete expectation for how long the learning period is or what "improves" means in measurable terms. A user at dictation 48 with a 15% correction rate has no way to know they are two dictations away from a meaningful improvement in cluster detection. This is a P2 experience gap — the system is technically correct, the user is technically informed. Detailed expectation-setting (e.g., a progress indicator toward the 50-dictation threshold) would improve retention but is not blocking.

**Verdict: Resolved. P0 closed. P2 gap noted below.**

---

### P0-3: LLM all-fail now shows warning toast — RESOLVED

**Previous state (v4):** The LLM fallback chain (Groq → OpenAI → Anthropic) terminated at Anthropic with no defined behavior. Silent degradation was possible — user would receive raw STT text with no explanation.

**Current state (Draft v5):** Section 9.5 ("LLM All-Fail Degraded Mode") now fully specifies the failure path:

1. Return `replaced_text` (Stage 3 output) immediately — no retry, no buffer
2. Apply local post-processing (Stage 6: number formatting + exact dictionary)
3. **Show UI warning toast:** "Text normalization unavailable — raw text inserted"
4. Log failure with provider names and error codes; increment daily diagnostics counter
5. Next dictation retries the full LLM chain from scratch

The implementation is present as Python code (`normalize_with_fallback`) with `AllProvidersFailedError` exception handling and explicit `show_toast()` call.

**Remaining gap (none blocking):** The toast text is functional but clinical. A user who does not know what "normalization" means will see a message that does not tell them what to do. A softer alternative — "Could not reach AI services — your text was inserted as spoken" — would be more user-facing. This is a copy suggestion, not an architecture gap.

**Verdict: Resolved. P0 closed.**

---

### Tracked item: Auto-promote toast defined — RESOLVED

**Previous state (v4):** The auto-promotion mechanism (3 corrections → exact dictionary entry) was invisible. The v4 review called this "the single highest-leverage UX improvement available."

**Current state (Draft v5):** Section 12.1 specifies:

> "**Auto-promote toast:** When `correction_counts` reaches 3 for a pair, show: 'Learned: [old] -> [new] (will be applied automatically)'"

The trigger (count reaching 3), the format (toast), and the exact copy are all defined. The copy correctly uses the correction pair variables `[old]` and `[new]` — the user sees the actual words, not a generic message.

**Remaining gap (P2):** The toast does not offer an undo path. If the auto-promotion is incorrect (e.g., the user corrected a term three times in different contexts and the promotion encodes the wrong default), there is no "Undo" or "Manage" link on the toast itself. The user would need to know to navigate to Settings > Dictionary to reverse it. This is a recoverable UX gap but worth surfacing.

**Verdict: Resolved. Tracked item closed.**

---

### Tracked item: Privacy screen on first run defined — RESOLVED

**Previous state (v4):** Section 17.1 documented unencrypted metadata thoroughly in the spec but specified no user-facing communication. The v4 recommendation was a plain-language privacy summary screen.

**Current state (Draft v5):** Section 17.4 ("First-Run Privacy Summary") specifies:

> "On first launch, show a one-time privacy summary screen explaining in plain language:
> - Stored locally only: dictation history (encrypted), vocabulary patterns, correction history
> - Sent to cloud: only dictation text to STT and LLM APIs — no metadata, no co-occurrence data, no correction history
> - User controls: how to export all data, how to delete all data, how to disable cloud LLM (all-toggles-OFF mode)
> - This screen must be dismissable and accessible later from Settings > Privacy."

All four elements from the v4 recommendation are present: plain language, specific disclosure of what goes to cloud, user controls, and a path back to the screen after first run.

**Remaining gap (P2):** The screen is specified in plain-language bullet points but the spec does not say where the unencrypted keyword metadata disclosure fits. Section 17.1 documents that thread keywords, topic summaries, cluster names, and correction token counts are stored unencrypted on disk. The first-run screen says "vocabulary patterns, correction history" — which is accurate but may understate the specificity of what is reconstructable from the plaintext SQLite tables. A user who reads "vocabulary patterns" does not understand that the full correction pair "замок → lock" is stored as plaintext. This is a copy precision gap, not a missing feature.

**Verdict: Resolved. Tracked item closed.**

---

## Remaining UX Gaps

### G1 — Toast copy is functional but not user-facing (P2)

Three toasts are now specified. All use technically accurate but internally-framed language:

| Toast | Current copy | User-facing alternative |
|-------|-------------|------------------------|
| LLM all-fail | "Text normalization unavailable — raw text inserted" | "Could not reach AI services — text inserted as spoken" |
| Cold-start onboarding | "The app learns your vocabulary over time. Accuracy improves with each dictation." | Acceptable as-is |
| Auto-promote | "Learned: [old] -> [new] (will be applied automatically)" | Acceptable as-is |

The LLM all-fail toast is the only one that uses a technical term ("normalization") that may not be understood by the target user profile (non-technical, primarily Ukrainian-speaking). Recommend replacing "normalization" with "AI services" or "text improvement" in the user-visible string. The internal log message can retain precise terminology.

---

### G2 — Auto-promote toast has no undo path (P2)

When the system auto-promotes a correction pair after three occurrences, the toast "Learned: [old] -> [new] (will be applied automatically)" confirms the action but provides no reversal mechanism. If the promotion is wrong:

- The user must know that Settings > Dictionary exists
- Must know that auto-promoted entries appear there
- Must find and delete the entry manually

The toast should include a secondary action: a small "Manage" or "Undo" link that opens the relevant dictionary entry directly. This converts a potentially frustrating silent automation into an observable, controllable event — consistent with the "transparency as a feature" pattern cited in the v4 competitive analysis.

---

### G3 — Cold-start progress is invisible beyond the initial toast (P2)

The first-run toast fires once. Between dictation 1 and dictation 50, the user has no signal that the learning period is active, progressing, or near completion. Section 12.5 maps the maturation timeline precisely (0-20 dictations: all-LLM; 20-50: first clusters detectable; 50-100: 70% local resolution). This information exists in the spec but reaches no user.

The v4 competitive note on Voibe is now more urgent: Voibe's manual dictionary seeding during onboarding solves cold-start accuracy by frontloading user effort. If AI Polyglot Kit's positioning is "learns automatically without setup," the invisible learning period is a trust gap. A lightweight indicator — even a "Context: learning (23/50)" line in the settings diagnostics page — would give the technically curious user enough feedback to understand the system. The exact-dictionary seeding flow (already present in settings) could be surfaced more prominently during this period with a hint: "Add key terms now to improve accuracy while the app learns."

---

### G4 — `notify_user()` implementation still unspecified for script validation (P1)

This gap was flagged in v4 (N4) and remains open in v5. Section 9.3 calls `notify_user()` when script validation finds issues, but `notify_user()` is not defined. The spec has now defined `show_toast()` (Section 9.5, LLM all-fail) as a distinct call. This creates two unreconciled notification mechanisms:

- `show_toast()` — defined, used for LLM failure
- `notify_user()` — undefined, used for script validation and database integrity errors

The difference matters for script validation specifically: if `notify_user()` produces a modal dialog (blocking), the user cannot see the script editor while reading the validation issues. If it produces a toast, the message may be too brief for a multi-issue list. Section 9.3 shows the notification content includes a formatted list of issues (`"\n".join(...)`), which suggests it should render as a multi-line dialog, not a toast. This needs to be resolved before the script editor UI can be implemented.

**Recommendation:** Define `notify_user()` explicitly. For script validation: a non-blocking side panel or inline annotation in the script editor showing removed rules in red strikethrough, with a plain-language summary line above the LLM-generated issue list.

---

### G5 — Export dialog does not surface the portability table (P1)

This gap was flagged in v4 (N6) and is unresolved. Section 13.3 contains a complete portability summary table showing what transfers and what does not (API keys and voice profile are non-transferable). The export UI is described as:

> "Export flow (UI: Account → Export all settings → 'Include context profile')"

The portability table exists in the spec but is not specified to appear in the export dialog. A user who clicks "Export all settings" and relies on the resulting `.apk-profile` file for a machine migration will be surprised to find their API keys are missing. The table (or a simplified version of it) should appear as a confirmation step before export: "What will be included / What will not be included."

---

## FINAL UX VERDICT

### What resolved since v4

All three v4 P0 items are closed. All two v4 tracked items are closed. This is a meaningful improvement: the spec now specifies user-visible behavior for the three most impactful failure and transition states (LLM all-fail, cold-start, auto-promotion). The privacy summary screen in Section 17.4 is well-designed and appropriately scoped.

The offline fallback, while delegated to the parent spec, is now named and has a UI indicator defined. The cross-reference is sufficient for implementation purposes.

### What remains open

Five gaps carry forward, none of them blocking at the P0 level:

| Priority | Gap | Section |
|----------|-----|---------|
| P1 | `notify_user()` undefined — modal vs. toast ambiguity in script validation | 9.3 |
| P1 | Export dialog does not surface portability table | 13.3 |
| P2 | LLM all-fail toast uses technical term "normalization" | 9.5 |
| P2 | Auto-promote toast has no undo/manage path | 12.1 |
| P2 | Cold-start learning progress invisible after first toast | 12.1, 12.5 |

### Readiness assessment

**The spec is ready to hand to implementation for the core pipeline.** The context engine, correction learning, LLM fallback, privacy disclosure, and cold-start communication are all specified to a level that allows implementation without UX ambiguity for the primary flows.

Two P1 items (script validation notification format, export dialog portability table) should be resolved before implementing those specific UI surfaces. They are scoped features, not architectural gaps — they do not block work on the dictation pipeline, overlay, or settings pages.

The product is now closer to shippable than in any previous review round. The engine specification is mature. The user-facing layer has crossed the minimum threshold: the three most important moments (first use, learned word, total failure) now have defined communication. What remains is refinement, not foundation.

**Recommendation:** Proceed to implementation. Resolve G4 (notify_user specification) and G5 (export dialog table) in the UI design pass before those surfaces are built. Track G1-G3 as post-launch polish candidates.

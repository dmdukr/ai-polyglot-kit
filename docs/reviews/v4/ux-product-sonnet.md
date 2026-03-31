# UX & Product Review v4 — Context Engine Architecture
**Spec:** `2026-03-28-context-engine-architecture.md` (Draft v4)
**Previous review:** `docs/reviews/v3/ux-product-sonnet.md`
**Reviewer:** Claude Sonnet 4.6 (PM/UX perspective)
**Date:** 2026-03-28
**Role assumed:** Non-technical user who just wants to speak and have text come out right.

---

## Previous P0 Recommendations — Status

Three P0 items were flagged in v3 as must-fix before shipping. Tracking them against Draft v4.

### P0-1: Define the offline fallback completely — UNRESOLVED

**Previous finding:** The spec listed "(offline)" as the final STT fallback in Section 3.1 but gave zero specification — no model named, no install flow, no user-facing indicator.

**Current state (Draft v4):** Section 3.1 still reads:
> `#1 AssemblyAI → #2 Deepgram → #3 OpenAI → (offline)`

The parenthetical is still parenthetical. There is no section defining what the offline mode is. The question asked in v3 — "Which offline model? Whisper.cpp? Vosk? What is the accuracy? Is it always available or requires setup?" — receives no answer in this draft.

**Verdict: Not addressed. Still P0.**

### P0-2: Add cold-start onboarding — PARTIALLY ADDRESSED (spec, not UX)

**Previous finding:** No first-run experience design. User hits 20% error rate on day one with no explanation.

**Current state (Draft v4):** Section 12.1 now explicitly states:
> "Cold start (first ~50 dictations): All threads created with `cluster_id = NULL` — LLM handles all term disambiguation — No degradation — just more LLM calls initially"

And Section 12.5 adds a timeline table showing the maturation path (0-20 → 20-50 → 50-100 → 100-500 → 500+).

**What changed:** The spec now accurately documents the cold-start period internally. This is better than v3.

**What still has not changed:** There is no onboarding screen, no progress indicator, no user-facing communication about this period. The phrase "No degradation — just more LLM calls initially" reappears from v3 and is still, as noted then, technically accurate but experientially false. Section 14.2 confirms: at 0 chats, correction rate is ~20% and term resolution accuracy is 50%. That is degradation in any user-facing sense.

The spec knows the cold-start period exists and has mapped it precisely. It has not designed any UX around it.

**Verdict: Architecture documented, UX still undefined. Still P0 for user-facing design.**

### P0-3: Add LLM/STT failure UI — UNRESOLVED

**Previous finding:** No graceful degradation UI. When all LLM providers fail, user gets raw STT output with no banner, no indicator, no explanation.

**Current state (Draft v4):** Section 9.4 clarifies:
> "LLM is skipped ONLY when all four toggles are OFF — effectively 'raw STT output' mode. This is an edge case (<1% of users)."

This is an improvement in spec clarity — it confirms that toggle-OFF is intentional raw mode, not a failure mode.

**What remains unaddressed:** The spec still does not define what happens when all three LLM providers fail while toggles are ON. The "3 providers in fallback order: #1 Groq → #2 OpenAI → #3 Anthropic" chain from Section 3.1 terminates at Anthropic with no further branch. If Anthropic also fails: the code path is unspecified. Does the pipeline return raw text? Does it throw? Does it show an error? Silent degradation remains possible.

**Verdict: Not addressed. Still P0.**

---

## New UX Concerns

### N1 — Unencrypted keyword metadata creates a privacy gap the spec partially acknowledges (P1)

Section 17.1 is new in Draft v4 and is genuinely commendable — it explicitly lists every field stored unencrypted and why. This is the right thing to do in a spec. However, the list is sobering for a privacy-first app:

| What is stored unencrypted | Example |
|---------------------------|---------|
| Thread keywords | "замок", "деплой" |
| Fingerprint keywords | "PR", "auth" |
| Thread topic summaries | "ремонт квартири", "auth module refactor" |
| Cluster display names | "git / deploy / PR" |
| Co-occurrence graph terms | all term pairs |
| Correction token counts | "замок" → "lock" |

A person with filesystem access to the SQLite file can reconstruct a fairly complete picture of what the user has been dictating — topics, technical domain, correction history — without touching any DPAPI-encrypted content. The spec justifies this with:
> "Risk level: low — an attacker with filesystem access likely has access to far more sensitive data on the machine"

This is a reasonable technical risk assessment. It is not a user communication strategy.

**The UX problem:** The v3 recommendation for a Privacy Summary screen called for plain-language explanation of what is stored. Section 17.1 now exists in the spec but is not referenced anywhere in onboarding, settings, or a user-visible privacy page. The user still has no window into this. The spec has done the right internal work; the user-facing communication layer is still absent.

**Specific concern:** The word "DPAPI-encrypted" appears in Section 10.3 with the note: "The `correction_counts(old_token, new_token)` table stays plaintext — individual tokens without surrounding context are not sensitive." This is a reasonable engineering decision. It may surprise a user who assumed their corrections were private. The correction_counts table contains every word pair the user has ever corrected — a vocabulary fingerprint.

### N2 — Daily maintenance runs at startup: timing conflict with pymorphy3 initialization (P1)

Section 13.2 specifies:
> "Run at app startup, max once per 24 hours"

The `daily_maintenance()` function includes: co-occurrence pruning, history deletion, thread cleanup, fingerprint capping, database consolidation, and `VACUUM INTO` for backup.

The `pymorphy3` analyzer is initialized at module load with:
```python
morph = pymorphy3.MorphAnalyzer(lang='uk')
```

This is a module-level singleton that takes ~500ms on first load (dictionary parsing). Combining pymorphy3 initialization (~500ms) with `daily_maintenance()` startup tasks (VACUUM INTO alone can take 200-500ms on a 40MB database) creates a realistic scenario where app startup takes 1-2 seconds before the user can dictate.

The spec states a design goal of "Speed: Context resolution <5ms (local), total pipeline overhead <50ms" (Section 2). These targets are met during steady-state operation. They are not met during startup. The startup latency is unspecified and likely significant.

**Research context:** Nielsen's guidelines establish that 1 second is the threshold where users feel the system is slow and their flow is interrupted. The Doherty threshold (400ms) marks the point where the system feels "addicting" — below it, the interaction feels seamless. A 1-2 second startup on first daily use, with no indicator, crosses both thresholds.

**Recommendation:** Lazy-load pymorphy3 on first dictation (not at module import). Run `daily_maintenance()` asynchronously on a background thread, not blocking the dictation pipeline. Show a brief loading indicator if the app is not ready within 400ms.

### N3 — The correction UX still shows the user a token count, not a word (P1)

The v3 review noted the correction UX was completely unspecified. It remains so in Draft v4. Section 10.1 shows the feedback flow:
```
raw_text:      "треба поміняти замок на вхідних"
normalized:    "Need to change the lock on the front door"
corrected:     "Треба поміняти замок на вхідних дверях"
```

The spec defines what is stored but not what the user sees. The correction mechanism operates on `token_diffs` between normalized and corrected text. The user has no UI spec: not what is highlighted, not what they type into, not what confirmation they receive.

This gap compounds with the new DPAPI encryption of correction triads (Section 10.3). The full correction (raw + normalized + corrected) is encrypted, which is correct for privacy. But the `correction_counts` table stores plaintext token pairs for auto-promotion tracking. From a UX standpoint: if the user corrects "замок" → "lock" twice and is on their third correction, they are one correction away from permanent auto-promotion. They do not know this. The count is invisible.

### N4 — Script validation shows issues list but the UX of "2 rules modified" is underspecified (P1)

Section 9.3 now includes the `save_script()` function with this notification:
```python
notify_user(
    f"Script validation found {len(issues)} issue(s):\n"
    + "\n".join(f"  - {issue}" for issue in issues)
    + "\n\nProblematic rules have been removed."
)
```

This is a meaningful addition since v3. The user now learns that something was changed. Several UX gaps remain:

1. **`notify_user()` is not specified.** Is this a toast? A modal? An inline warning in the script editor? The difference matters — a modal blocks the user from seeing what changed; an inline warning does not.

2. **The issues list is LLM-generated text.** The `VALIDATOR_PROMPT` instructs the LLM to return `"issues": ["list of problematic rules found"]`. These strings will vary in phrasing, length, and technical level. A non-technical user who wrote "always format messages casually" and had it flagged as potentially injective will see an LLM-generated explanation of why. This may be clear or may be incomprehensible.

3. **The user cannot see the diff.** They know "2 rules modified" (from the count) but not which lines were changed. The spec saves the sanitized version without showing a before/after comparison. The user has no way to verify that the sanitization was correct and did not inadvertently remove a legitimate rule.

4. **The "fast model" choice for validation creates inconsistency.** Section 9.3 specifies `model="fast"` for validation — the cheapest available model. The LLM-generated issue descriptions will therefore come from a different (likely weaker) model than the normalization LLM. Issue quality may be inconsistent.

**Recommendation:** Show a diff view — original lines in grey, removed lines struck through in red — with an "Accept" / "Revert all" button. Use a single-sentence plain-language summary above the technical LLM issues list.

### N5 — No user-visible signal that pymorphy3 or the context engine is active (P2)

The context engine is the primary new feature of v6. After 50+ dictations, it materially improves output quality. The user does not know this is happening. There is no indicator in the tray, overlay, or settings showing:
- That the context engine exists
- That it is running
- That their dictation history is being used to improve results
- What topics it has detected

This was a P2 in v3 (recommendation #10: "Learning progress indicator"). It remains unaddressed in Draft v4 and the gap is widening: the spec is now more complete technically, making the absence of any user-facing representation more conspicuous.

### N6 — Profile export: what-does-not-transfer communication still missing (P1)

v3 flagged: during export, the user should see explicitly what will and will not transfer if the password is forgotten.

Section 13.3 now includes a detailed portability summary table, which is the right spec content. However, the export flow description remains:
> "Export flow (UI: Account → Export all settings → 'Include context profile')"

The table (which shows API keys and voice profile as non-transferable) exists in the spec but is not specified to appear in the UI. The user clicks "Export all settings" and may believe "all settings" means all settings.

---

## Script Validation UX

This section addresses the specific question: does the current spec give a user-friendly experience when B4 (script validation) runs?

### What the spec now defines

Script validation (Section 9.3) now exists as code, not just a concept. The key behaviors:
- Validation runs once on save and once on import — not per dictation
- User sees `notify_user()` with issue count and issue list
- Sanitized version is always saved, not the original
- On import, each imported script is re-validated

### What remains undefined for the user

**The save flow:** User writes a script, clicks Save. Validation runs. If issues found — notification appears. What is the UI state during validation? The LLM call for validation has latency (100-500ms depending on provider). Does the script editor show a spinner? A "Validating..." label? Or does it appear to hang?

**The notification trigger timing:** The spec shows `notify_user()` called synchronously within `save_script()`. If the notification is a modal dialog that appears while the script editor is still open, the user has two UI layers competing for attention.

**The import flow:** On profile import, `validate_script()` is called for each imported script in a loop. A profile with 10 scripts means 10 LLM calls during import. The import progress indicator (if any — none is specified) would need to account for this. A user importing a 40MB profile on a slow connection who sees a progress bar stall at 90% while scripts are being validated will think something went wrong.

**The "issues" framing:** The current notification text says "Problematic rules have been removed." This is accurate but may alarm users who wrote legitimate rules. A softer framing — "The app adjusted 2 rules to improve compatibility. Your script is active." — would reduce friction for the common case (user wrote nothing malicious, LLM was slightly over-eager in flagging).

### Verdict on Script Validation UX

The mechanism is correct. The UX around it needs: loading state during validation, a diff view showing what changed, softer notification copy for the non-malicious case, and a progress accounting during import.

---

## Competitive Update

### Wispr Flow onboarding (2025-2026)

Wispr Flow's onboarding was documented as "the best onboarding I've ever seen" by behavioral scientists at Irrational Labs (Kristen Berman, 2025 Substack analysis). Key elements:

- **Problem identification first:** "Which of these resonate with you?" — lists problems the app solves before showing any feature
- **Guided practice:** Users dictate a real email and a real note during onboarding, in their actual apps — proving it works before commitment
- **Placeholder text and inline prompts:** Makes it "nearly impossible to mess up" first use
- **Dropoff insight:** Wispr found that non-technical users installed, tried dictation in only one app, and churned — because they didn't realize it worked across all apps. Onboarding was redesigned to explicitly guide users to use it in 2-3 of their most-used apps.

**Implication for AI Polyglot Kit:** Wispr's biggest cold-start problem was not accuracy — it was discoverability. Users who succeeded were the ones who discovered the cross-app capability within the first session. For AI Polyglot Kit, the analogous discovery moment is: users who make their first few corrections and see the app improve will retain; users who experience repeated errors without understanding why will churn. The equivalent of Wispr's "try it in your apps" guided step would be: walk the user through their first correction, explicitly show the auto-promote mechanism, and set expectations for the learning period.

### "AI is learning" communication patterns (2025)

Current industry patterns for communicating adaptive AI to non-technical users:

- **Badges and chips:** "Suggested by AI" / "AI-Powered" / "Smart Suggestions" — used by productivity apps to signal AI presence without technical explanation
- **Progress framing:** Duolingo's "streak" mechanism, Spotify Wrapped — non-technical ways to show "the system knows you"
- **Contextual reveals:** Show the learning moment when it happens ("We noticed you often say X — we've saved it as a shortcut") rather than in a settings page the user never visits
- **Transparency as a feature, not a disclaimer:** Apps like Notion AI and Copilot now show "what I used to answer this" — surfacing sources builds trust

AI Polyglot Kit has the correction loop (3 corrections → auto-promotion) as a natural "learning moment." It is currently invisible. The v3 recommendation for a toast on auto-promotion remains the single highest-leverage UX improvement available — one sentence of feedback that converts a frustration cycle into a trust-building event.

### Voibe and new entrants (2026)

New entrant Voibe (getvoibe.com, 2026) positions itself explicitly on accuracy-from-day-one for non-English languages, with a manual dictionary seeding flow during onboarding. Users add 10-20 key terms before first use, dramatically reducing cold-start errors. This is the same mechanism as AI Polyglot Kit's exact dictionary — but surfaced as the primary onboarding step rather than buried in settings.

This represents a direct competitive response to the cold-start problem. If Voibe ships a 5-minute "teach me your words" setup flow before AI Polyglot Kit ships cold-start onboarding, the differentiator ("it just learns automatically") becomes a liability ("it takes a month to learn, while Voibe is good on day one").

---

## Verdict

### What improved since v3

The spec is substantially more complete technically. Section 17.1 (unencrypted metadata) is a mature privacy analysis that did not exist before. Section 9.3 (script validation) now has working code and a user notification. Section 12.5 maps the cold-start timeline precisely. The correction storage architecture (DPAPI for triads, plaintext for counts) is a well-reasoned engineering decision now explicitly justified.

### What has not improved

The three P0 items from v3 remain open:
1. Offline STT fallback — still undefined
2. Cold-start onboarding — architecture documented, user experience not designed
3. LLM all-fail degraded mode — still no UI, still no defined behavior

The UX surface of the app has not expanded in proportion to the engine's complexity. The engine now has: thread lifecycle, fingerprint matching, co-occurrence graph, cluster detection, script validation, DPAPI encryption, correction counting, LLM confidence tracking. The user sees: a feedback key. These are not matched.

### Priority list for v5 spec

| Priority | Item |
|----------|------|
| P0 | Define offline STT: model, install, user indicator |
| P0 | Define LLM all-fail behavior: what user sees, what text they receive |
| P0 | Cold-start onboarding screen: problem framing + expectation setting |
| P1 | Toast on auto-promotion: "'[word]' will always be written as '[corrected]'" |
| P1 | Script validation UX: loading state + diff view + softer copy |
| P1 | pymorphy3 + daily_maintenance startup: lazy load + async, target <400ms |
| P1 | Privacy summary screen: plain-language explanation of unencrypted metadata |
| P1 | Export dialog: show portability table + explicit password-loss warning |
| P2 | "Context & Learning" settings page: show detected topics, clear context |
| P2 | Correction UX spec: what user sees, what they type, confirmation |
| P2 | Import progress accounting: LLM validation calls included in progress bar |

### Overall assessment

The context engine architecture is production-ready from an engineering standpoint. The co-occurrence graph, thread lifecycle, fingerprint matching, and correction learning form a coherent and well-specified system. Privacy handling is thoughtful and the new Section 17.1 shows genuine internal reflection on data exposure.

The product is not yet ready to ship to a non-technical user. The gap is not in the engine — it is in everything the user sees while the engine runs. An app that silently degrades, silently learns, silently validates, and silently stores metadata will generate support tickets, negative reviews, and churn from exactly the users it is designed to help.

The engine is ready. The UX layer around it needs one more focused design pass.

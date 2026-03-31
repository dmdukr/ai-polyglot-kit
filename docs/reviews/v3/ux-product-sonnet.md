# UX & Product Review — Context Engine Architecture
**Spec:** `2026-03-28-context-engine-architecture.md`
**Reviewer:** Claude Sonnet 4.6 (PM/UX perspective)
**Date:** 2026-03-28
**Role assumed:** Non-technical user who just wants to speak and have text come out right.

---

## First-Run Experience Analysis

### What the spec says
- Dictations 0–20: all unknown, all LLM fallback
- Dictations 20–50: clusters emerging, ~30% local hit rate
- Dictations 50–100: ~60% local hit rate
- Dictations 100–500: ~80% local hit rate
- Correction rate at 0 chats: ~20%. At 1000: ~5%.

### The user's actual experience

The first 50 dictations are the highest-risk period for any productivity app. This is when the user decides whether to keep using it or uninstall. The spec is silent on what this period feels like from the user's side.

**The cold-start math is uncomfortable.** At 0 dictations, 1-in-5 outputs needs correction. That is not "no degradation." That is a 20% error rate on day one. For a non-technical user who installed the app expecting it to "just work," correcting every fifth dictation feels broken — not like a system warming up.

**The spec claims "no degradation — just more LLM calls initially" (Section 12.1).** This is technically accurate but user-experientially false. More LLM calls means LLM makes more guesses without context. LLM guesses on ambiguous terms are wrong 50% of the time (Section 14.2: "50% (LLM guesses)" at 0 chats). That is degraded. The spec needs to stop saying otherwise.

**No progress feedback is defined.** The user has no way to know:
1. That the app is learning at all
2. How far along the learning is
3. When they can expect it to improve
4. Why a correction they made last week is still being repeated

The spec defines a rich internal state (cluster hit rate, correction rate, graph density) but zero UI surface for any of it. The user is flying blind.

**What's missing:** A first-run experience design. Wispr Flow and Monologue both deliver high baseline accuracy from day one because they rely primarily on the STT provider's generic model and cloud AI, not on a personal learned graph. AI Polyglot Kit's competitive advantage (the personal context graph) is also its first-run liability. The spec needs to acknowledge this tension and address it.

### Specific scenarios that will frustrate new users

- **Day 1, first message:** User dictates "поміняй замок" in Telegram. System has no threads, no graph, no fingerprints. LLM guesses. If it guesses wrong ("change the lock" in an IT context when the user meant a door lock), the user has no idea why or how to prevent it next time.
- **Day 3:** User makes the same correction for the third time. The spec says this auto-promotes to an exact term. But the user doesn't know this is about to happen. They just see "it's wrong again."
- **Day 7:** Some dictations are suddenly much more accurate. The user doesn't know why. This creates an unpredictable, magical-feeling experience — which can be charming or unsettling depending on personality.

---

## Error Handling & User Feedback

### What the spec defines

- Double-tap feedback key → enters corrected text
- System classifies error source (STT vs LLM)
- Learns from correction, increments correction count
- After 3 identical corrections → auto-promotes to exact term

### What it doesn't define

**The correction UX is completely unspecified.** "Double-tap feedback key" is mentioned in Section 10.1 but:
- What does the UI show when correction mode is active?
- Does the user see the raw STT text, the normalized text, both?
- How does the user understand what to correct — the word itself, or the full sentence?
- What happens after they submit the correction? Any confirmation?

**There is no explanation of why an error happened.** A non-technical user who gets wrong output sees: wrong text. Full stop. They have no access to:
- Was it the microphone (STT error)?
- Was it the AI normalizer (LLM error)?
- Was it an ambiguous word that was resolved to the wrong meaning?

From Wispr Flow user feedback: users who experience errors primarily complain about not understanding what went wrong and whether their correction will stick. The spec has the correction mechanism but skips the feedback loop that closes the trust cycle.

**The auto-promotion mechanism (3 corrections → exact term) is invisible.** This is actually a great feature — repeat yourself three times and it never happens again. But the user will never know this is happening. They're just correcting over and over wondering if the app is stupid.

**Recommendation:** After the third correction of the same word pair, show a brief toast: "Got it — 'пайтон' will always become 'Python' from now on." That one message would transform a frustration loop into a trust-building moment.

### What happens when the system gets it wrong and the user doesn't correct it?

The spec's learning mechanism is entirely correction-driven. If a user dictates wrong output, pastes it, and moves on without correcting, the system learns nothing. In practice, most users will not correct every error. They'll correct the ones that are egregious and ignore the small ones. The small ones will persist indefinitely.

This is acceptable — but the spec should acknowledge it rather than implying the system continuously improves on its own.

---

## Settings & Configurability

### The surface question

The spec describes a complex internal architecture: co-occurrence graphs, conversation threads, cluster IDs, fingerprint tables, confidence thresholds (0.6), thread expiry (15 minutes), fingerprint minimum depth (3 messages). None of this is framed as user-configurable — and most of it shouldn't be.

**The right call: keep internals invisible.** A non-technical user does not need to tune a confidence threshold. They need to say "it keeps getting this word wrong" and have that fixed. The spec's correction mechanism handles this. Good.

**What the user might reasonably want to configure (and the spec doesn't address):**
1. "Forget this conversation" — clear a thread that went wrong direction
2. "This word always means X, no exceptions" — force an exact term without waiting for 3 corrections
3. "This app is always technical" — manually assign an app to a cluster rather than waiting for it to be detected
4. "Start fresh" — wipe the learned context without losing dictionary/settings

**The export UI mentions "Include context profile" as a checkbox.** This is the only place the context engine surfaces in settings, and only in an export flow. There's no "My learned context" section, no way to view what the system thinks it knows, no way to selectively clear parts of it.

**Regarding the existing 14-page settings mockup:** The spec adds significant capability (threads, clusters, co-occurrence) with zero settings pages. This creates a false simplicity. The user can't see the feature working, can't control it, and can't debug it when it behaves unexpectedly. One page — a "Context & Learning" page — would cover all reasonable user needs.

---

## Degraded Mode Analysis

### STT provider failures

The spec defines 3 STT providers in fallback order: AssemblyAI → Deepgram → OpenAI → (offline). Section 3.1 mentions "(offline)" as the final fallback but provides zero specification for what offline STT means:

- Which offline model? Whisper.cpp? Vosk?
- What is the accuracy of the offline fallback?
- How does the user know they're in offline mode?
- Is offline mode always available or does it need to be set up in advance?

A non-technical user who is on a plane, on a train with no signal, or simply having an ISP outage will click the microphone button and expect something to happen. "All 3 cloud providers failed" is a silent failure mode in the spec. No UI for it is described.

### LLM provider failures

The spec defines 3 LLM providers: Groq → OpenAI → Anthropic. If all three fail:
- The spec says "LLM is skipped if all toggles are OFF"
- But it never describes what happens when all toggles are ON and all LLMs are unavailable

The user will get raw STT output — no punctuation, no grammar correction, no term normalization. This is significantly degraded output. The question is: does the user know this happened? Does the app show a banner? Does it silently emit raw text?

**The spec has no graceful degradation UI at all.** This is a critical gap. At minimum, the user needs:
1. Visual indicator showing which providers are active vs. failed
2. Clear message when falling back: "Using backup service — quality may vary"
3. Offline mode that is explicitly available and documented

### Internet down entirely

If internet is fully unavailable and offline STT is not pre-configured, the app simply does not work. For a user who has come to depend on voice dictation, this is a hard failure with no warning and no path forward. The spec should at minimum define the offline setup flow as a first-run recommendation.

---

## Privacy Communication

### What the spec stores (from user perspective)

The system stores, locally, encrypted:
- Everything the user has dictated (history, up to 365 days)
- Keyword pairs that co-occurred in their dictations
- Conversation topic clusters derived from their content
- Fingerprints of how conversations started
- All corrections they've made

From a technical standpoint, this is well-designed: all local, DPAPI-encrypted, no cloud upload of context data.

From a user's standpoint, if someone explained this list to them, a significant portion would find it unsettling. "The app keeps a record of everything I said for a year" is the headline, not "the keyword co-occurrence graph decays over 365 days."

### The creepiness threshold

Research on AI apps that learn user behavior (including Meta AI's memory feature, 2025) shows the creepiness threshold is crossed when:
1. The user didn't know learning was happening
2. The learning surfaces in unexpected ways (app "guesses" something correctly that the user didn't think it would know)
3. The user can't see or control what's stored

AI Polyglot Kit scores poorly on 1 and 3, and potentially on 2 as the system matures. The spec is entirely silent on privacy communication to the user.

### How to communicate local AI learning

The industry's best practice in 2025-2026 is to be radically transparent about what is local. Phrases that work with non-technical users:

- "Everything stays on your computer" (not "local DPAPI-encrypted SQLite")
- "The more you use it, the better it knows your words — no data leaves your device"
- "Your history is stored for 1 year, only on this PC. You can delete it any time."
- "These are the topics the app has learned you talk about: [IT / Renovation / Medical]. [Edit / Clear]"

The spec should define a Privacy Summary screen (one page, shown on first run and accessible from settings) that explains in plain language what is stored and how to delete it. This screen would also serve as onboarding for the learning feature.

### Profile export and forgotten passwords

The export flow (Section 13.3) requires a user password to re-encrypt history. This is necessary for security. But:

- What happens if the user forgets the password? The spec has no recovery path.
- History is permanently unrecoverable. The non-history data (graph, dictionary, scripts) still transfers.
- Is this explained to the user before they set the export password?

A non-technical user who loses their export password will try to import, get a decryption error, and conclude "the import is broken." They'll never understand why half their data came back and half didn't.

**Recommendation:** During export, show explicitly: "Your dictation history is protected by this password. If you lose it, your history cannot be recovered — but your vocabulary, dictionary, and settings will still transfer. Make sure to save this password somewhere safe." The export dialog should also list what will and won't transfer (the table from Section 13.3 is exactly right — it just needs to appear in the UI).

---

## Competitive Comparison

### Wispr Flow (Mac/Win/iOS, cloud-based)

**Strengths users love:** 95%+ accuracy from day one, works in every app, strong multilingual support (code-switching between languages in a single dictation), no setup beyond installation, instant productivity gains.

**Weaknesses users hate:** ~800MB idle RAM, 8–10 second startup, all audio processed on OpenAI/Meta cloud servers, poor support responsiveness, Windows reliability issues.

**What AI Polyglot Kit has that Wispr Flow doesn't:** Privacy (everything local), Ukrainian language quality (Wispr targets English/Spanish primarily), learned personal vocabulary, no subscription for LLM usage per dictation.

**What Wispr Flow has that the spec needs to address:** Day-one accuracy. Wispr doesn't have a cold start problem because it uses generic cloud AI with no personal learning. The spec's system is better long-term but worse out of the box.

### Monologue (Mac, privacy-focused)

**Strengths:** Offline model option (full local processing), custom tone per app, simple onboarding, $10/month vs Wispr's higher tier.

**Weaknesses:** Lower accuracy than cloud-based alternatives for technical/accented input, Mac-only.

**Comparison:** Monologue is the closest philosophical match to AI Polyglot Kit (privacy-first, per-app customization, local processing). AI Polyglot Kit's advantage is the learned context graph. Monologue's per-app "tone" is manually configured; AI Polyglot Kit's per-app context is automatically learned. This is a strong differentiator — but only after the learning period.

### SuperWhisper (Mac/iOS, offline-first)

**Strengths:** Offline operation, custom modes with manual prompts, strong accuracy with Whisper models, accessibility-friendly.

**Weaknesses:** Complex setup, users must manually clean up transcripts, no contextual disambiguation.

**Comparison:** SuperWhisper is for power users who want full control. AI Polyglot Kit targets a more casual user (just dictate, have it come out right). The context engine is a direct answer to SuperWhisper's weakness of requiring manual transcript cleanup. However, SuperWhisper's offline model is fully specified and available from day one — AI Polyglot Kit's offline fallback is not.

### Positioning conclusion

AI Polyglot Kit occupies a unique space: privacy-first (like Monologue/SuperWhisper) + auto-learning (unlike any competitor) + Windows-first with Ukrainian support (no competitor). The context engine is the right architecture to defend this position. The execution gaps are in cold-start UX and communication, not in the underlying system design.

---

## Recommendations (Prioritized)

### P0 — Must fix before shipping

**1. Define the offline fallback completely.**
Which model, how to install it, what the user sees when it activates. An app that silently stops working when internet is unavailable will receive one-star reviews.

**2. Add cold-start onboarding.**
First run: show a screen that sets expectations. Something like: "In the first week, the app learns your vocabulary. You'll see occasional suggestions to correct words — each correction teaches the app your specific terms. After about 50 dictations, most words will be recognized automatically." This converts a frustrating experience (why is it wrong again?) into an expected experience (it's still learning, I know what to do).

**3. Add LLM/STT failure UI.**
When a provider fails and the system falls back, show a subtle indicator. When the final fallback is reached (raw STT output), show a clear banner: "AI formatting unavailable — showing raw transcription." Users will trust an app that admits its limitations more than one that silently degrades.

### P1 — Should ship with v6

**4. Add a "Context & Learning" settings page.**
One page showing:
- Topics the app has learned (cluster display_names)
- Option to clear a specific topic or all context
- History retention setting (currently configurable in code, not in UI)
- A "Forget this conversation" action available from the overlay or tray

**5. Toast notification on exact-term promotion.**
When a correction is applied for the third time and auto-promoted to exact term, show: "'[word]' will now always be written as '[corrected]'." This is the most impactful one-sentence change for new user trust.

**6. Explicit privacy summary screen.**
Shown once on first run, accessible via Settings → Privacy. Plain-language explanation of what is stored, where, and how to delete it. Specifically frame it as: "Everything stays on this computer."

**7. Export dialog with explicit instructions on password recovery limitation.**
Before the user sets the export password, show what is and isn't recoverable if the password is forgotten.

### P2 — Nice to have post-launch

**8. Manual term override without waiting for 3 corrections.**
User can right-click/long-press a word in the correction UI and say "always use this." Shortcut to auto-promotion.

**9. Manual app-to-cluster assignment.**
Settings → Context → "For [VS Code], always treat as: [IT]." Lets power users skip the learning period for their primary apps.

**10. Learning progress indicator.**
A small, non-intrusive element (perhaps in the tray tooltip or a stats section) showing: "Context engine: 73 dictations — learning your vocabulary." Satisfies the users who want to know it's working without requiring them to understand graph theory.

**11. Wispr Flow's Day-1 accuracy challenge.**
Consider a "Quick Setup" flow where users manually confirm 3–5 app/topic pairs during first run: "When you use [Telegram], what topics do you usually discuss? [Work / Personal / Mixed]." This would let the system assign a cluster immediately to those apps rather than waiting for organic detection, cutting the cold-start period from 50 to ~10 dictations.

---

## Summary Verdict

The context engine architecture is technically sound and architecturally ambitious. The four-level resolution, organic cluster growth, and correction-driven learning are all well-designed. The privacy model (local, DPAPI, no cloud upload of context) is a genuine competitive differentiator.

The UX gaps are concentrated in three areas:
1. **Cold start communication** — the system's early-use weakness is unacknowledged and unmitigated in the spec
2. **Failure modes** — offline STT and full-provider-failure paths are undefined
3. **Transparency** — the user has no window into the system, no way to see it working, no way to course-correct it except through repeated corrections

None of these are architectural flaws. They are design omissions that can be addressed in the settings UI and onboarding flow without touching the core engine. The engine is ready. The user experience around it is not yet defined.

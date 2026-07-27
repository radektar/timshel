# Plan: Onboarding → First Digest (+ Sonnet 5 eval)

Status: PROPOSED (awaiting approval) · 2026-07-24

## Problem & hypothesis

Import alone activates nothing: the seen-set migration (PR #89) deliberately
marks an existing archive as consumed, so a new user who connects a full vault
still waits ~a week for the first digest. **Hypothesis:** Timshel's activation
moment is an insight generated from the user's *already existing* notes in the
first session — not the transcription of new recordings.

- **Binary success criterion:** every new tester gets ≥1 verdict-surviving
  connection from their own imported material in the first session (≤10 min).
- **Kill/pivot trigger:** first digests on imported archives are consistently
  empty (verdict drops everything) → the first-session value becomes Recall
  search; digest returns to the weekly cadence and onboarding is reframed.

## Steps

1. **Sonnet 5 digest eval (FIRST — its outcome sets the first-digest model).**
   Add `claude-sonnet-5` to `scripts/preview_digest.py` MODELS (3-way:
   Haiku 4.5 / Sonnet 5 / Opus 4.8) and to `scripts/eval_synthesis.py`;
   add its price row to `insight_metrics._PRICES_PER_MTOK` +
   `eval_synthesis`/`preview_digest` price tables. Pricing verified
   2026-07-24: **$2/$10 per MTok introductory through 2026-08-31, then
   $3/$15 standard** — use the standard rate in the tables (never model the
   promo as permanent) and note the intro rate in the eval report. Caveat:
   Sonnet 5's new tokenizer yields ~30% more tokens for the same text, so
   the real per-digest cost must be MEASURED from usage, not derived from
   list price alone. Run gold-cases +
   real-corpus preview; judge with the same criterion as the Haiku-vs-Opus
   round (depth of connections, hero-contradiction catch). Decision output:
   default synthesis model AND the first-digest model + its price tag.
2. **Best-window selection ($0, local).** New helper in
   `candidate_assembly`: pick the most *connectable* window from unseen
   material (maximize strong-channel density — tags/bridges/entities score we
   already compute for the gate) instead of newest-15. Used ONLY by the
   first-digest/onboarding path; production windowing unchanged.
3. **Wizard step "Masz już notatki?"** in `src/setup/wizard`: folder picker →
   existing `import_text` pipeline (text_fingerprint dedupe already works),
   progress + count summary. Skippable.
4. **First-digest step.** After import: "Wygeneruj pierwszy digest (~$X wg
   modelu z pkt 1)". Requires the API key — if absent, the key screen moves
   HERE (this is the BYOK activation hook). Runs the existing digest pipeline
   (force, best-window from pt 2), then opens the Insights window on the
   result. No key / skipped → normal weekly cadence, nothing new invented.
5. **Telemetry.** `metrics.jsonl` row for the onboarding run gets an
   `onboarding: true` marker → the binary success criterion is measurable
   per tester without asking them.
6. **Tests.** Best-window selection (unit), first-digest path with a stub
   synthesizer (window reaches the paid path, Insights handoff fires),
   wizard-step logic (no UI automation).
7. **Design split.** Tester-minimal UI now (wizard step + notification +
   Insights window — validates the hypothesis on live people). The target
   onboarding flow gets a page in the full-app redesign brief
   (`design-system/pages/app-redesign-brief.md`) — design-first, no polished
   UI before the design review.
8. **Rollout.** Tester DMG after merge + one-paragraph tester instruction
   (import → first digest → rate in Insights).

## Out of scope (deliberate)

- Auto-draining the rest of the archive after the first digest (stays behind
  `make digest-archive` / a future explicit "digest more" action).
- Embeddings (ON HOLD per ADR-002), digest batching, model cascades.
- Polished onboarding visuals (redesign brief owns them).

## Open questions (to resolve at approval)

- First digest cost ceiling: one window (~$0.45 on Opus, less on Sonnet 5) or
  up to two windows if the first yields nothing?
- FREE tier: is the first digest also the paywall demo (one free run on our
  key) or strictly BYOK? (Business call — parks in Strategia if not decided.)

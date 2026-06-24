# ADR-001: Cost & retrieval architecture for the connection digest

**Status:** Proposed
**Date:** 2026-06-23
**Deciders:** Radek
**Supersedes cost figures in:** `scripts/eval_synthesis.py` (had stale $15/$75 Opus pricing)

## Context

The "Zestawianie" connection digest (Phase 1, shipped beta.11) runs one Opus 4.8
synthesis call per digest over an assembled candidate set. Reported cost was
**$0.35–0.71/digest**, judged too expensive. This ADR is the result of a deep,
multi-agent research pass across four cost axes: engine/API, retrieval/embeddings,
note description/compression, tokenization.

### Finding 0 — the premise was ~⅔ a measurement error

`eval_synthesis.py` hard-coded **$15/$75 per 1M** for Opus — that is **Opus 4.1
(deprecated)** pricing. Verified against Anthropic's official pricing page
(2026-06-23): **Opus 4.8 = $5 / $25 per 1M**, with the **1M context window billed
at standard rates (no long-context premium)**. Price constants now fixed.

**Corrected baseline (from the real beta.11 run, 16 notes):**
- input ≈ 15,800 tok, output ≈ 1,600 tok → **~$0.12/digest**
- weekly cadence → **~$0.50/month** for a BYOK user (they pay their own key)
- the empty wide-window run was ~$0.20, not $0.71

So pure cost-cutting is largely over-engineering at this scale. The levers below
are kept because **two of them are quality fixes that happen to also cut cost**,
and the rest are near-free hygiene.

### Cost anatomy (corrected, measured)
- Input ≈ **76%** of cost; output ≈ 24% (but output is 5× the per-token price).
- Input driver: candidate notes × up to **2400 chars** of Polish summary each.
  Measured **1274 tok/note** (Polish encodes at ~1.8–2.1 chars/tok — heavier than
  assumed; Opus 4.7+ also uses a new tokenizer, ~35% heavier than Haiku).
- Per-call fixed overhead: system prompt ~400 tok, tool schema ~700 tok,
  per-note scaffolding (header+tags) ~82 tok/note.

## Decision

Two tracks. **Do not invest in cost for cost's sake** ($0.50/mo); invest where a
lever also fixes a quality bug or is effectively free.

### Track A — free hygiene (do now, ≤1 day, zero quality risk)
1. **Cap directions 4→2**, terser rationale, lower `SYNTHESIS_MAX_TOKENS`. Output
   is 5× input price; 2 directions is a UX improvement (less noise), not a depth cut.
2. **Drop the `tags:` line** from the synthesis prompt — tags duplicate the summary
   and were already consumed upstream by candidate selection. ~35 tok/note, zero cost.
3. **Hand-write a flat tool schema** (drop pydantic `$defs`/`title`/verbose
   descriptions). ~174 tok/call, fixed.
4. Tighten the system-prompt rules block. ~70 tok.
→ ~−20% input for free → **~$0.10/digest**.

### Track B — quality investment (the real architecture; cost saving is a bonus)
5. **Local-vector retrieval — "embeddings propose, LLM narrates."** Embed the
   corpus on-device (`fastembed` ONNX + `sqlite-vec`, multilingual-e5-small) at
   transcription time; per digest, cosine-select a tight 5–6-note cluster per
   window note and feed only those to Opus. This is the Phase 2 plan, pulled
   forward. **It is primarily a quality fix:** it directly cures the observed
   "30 diverse notes → 0 connections" dilution, and semantic match reaches
   temporally-distant-but-similar notes that recency+BM25 structurally cannot —
   which is exactly where `contradiction-over-time` lives. Incidentally cuts
   candidates 16→~6.
6. **Synthesis card at transcription time.** Replace the 2400-char summary fed to
   synthesis with a 3-field card (`Teza` / `Stanowisko` / `Klucz`: thesis + stance
   + 5 keyphrases). Measured **1274 → 343 tok/note (−73%)**. Generated once in the
   Haiku summary call that already runs per note (~$0.0005/note — effectively free),
   stored in frontmatter; `_summary_or_excerpt` prefers the card, falls back to the
   summary slice for old/AI-off notes. Keep the `Stanowisko` line — it is what
   `contradiction-over-time` diffs across dates (cheap, 79 tok, load-bearing).
   Gate behind one eval pass before flipping the default (compression can drop
   faint links — acceptable, aligns with "few strong > many weak").

Track B stacks multiplicatively (fewer notes × smaller each) → **~$0.01–0.02/digest**,
but the reason to do it is the dilution/distance quality bug, not the cents.

## Options Considered (and rejected)

| Lever | Est. $/digest | Verdict | Why |
|---|---|---|---|
| **Batch API (−50%)** | $0.06 | **Defer** | Real 50% off, but the digest is sync today; Batch needs async submit/poll plumbing across daemon ticks. Not worth it for $0.50/mo. Revisit if pattern-triggered volume or a subsidized (non-BYOK) tier grows. On-demand "Generate now" must stay sync regardless. |
| Two-pass Haiku→Opus (pairs/re-rank) | $0.09–0.15 | **Reject** | Routes the depth-determining step through a weaker model (Haiku's recall gates what Opus sees); re-rank variant is *more* expensive. Kills the product's differentiator. |
| Sonnet 4.6 as synthesis model | $0.08 | **Reject** | Already dropped on precision (false-friend). Trades the exact thing the product sells for ~$0.04. |
| Prompt caching | ~$0.12 (≈0) | **Reject** | Weekly cadence > cache TTL; cacheable part is only ~1.1k static tokens, notes change every run. Worthless here. |
| **second-brain** as retrieval backend | $0.07 | **Reject as backend** | Cloud (Supabase) → breaks 100%-local positioning; indexes the whole vault not just transcripts; `find_related` is currently **broken** (returns corrupted vector). OK only as a throwaway 1-day spike to pre-validate that tighter clusters improve quality. |
| PL→EN gist (reasoning in English) | $0.10 | **Reject** | Once the card exists, the *pure-encoding* marginal gain is only ~28% of an already-tiny 343-tok card (~$0.01/digest) — a second lossy transform for cents, with real entity/date/quote-fidelity risk. |
| Short note ids (`[[n07]]`) | -0.45k tok | **Reject (for now)** | ~25 tok/note, but the basename↔wikilink round-trip is load-bearing; effort/risk not worth it. |

## Trade-off Analysis

- **Cost vs effort:** at corrected prices the cost problem is already ~solved
  ($0.50/mo). Track A buys another ~20% for almost nothing. Track B's cents are
  not the point — its justification is quality.
- **Quality vs compression (card):** the card can drop faint, implicit links.
  Mitigation: keep `Stanowisko`; eval before flipping default. Net effect is
  "fewer, stronger connections" — the stated design goal.
- **Local-first:** local vector is a perfect fit (embeddings never leave the Mac);
  second-brain would violate positioning. Reasoning-language (EN gist) is
  orthogonal to data residency but rejected on quality ROI.
- **Retrieval quality direction:** semantic retrieval *improves* the hero feature
  (distant contradictions, anti-dilution), not just trims tokens — the strongest
  reason in this whole ADR.

## Consequences

- **Easier:** digests get cheaper and (via Track B) *better*; the feature becomes
  cheap enough to consider for a subsidized non-BYOK tier later.
- **Harder:** Track B adds an on-device embedding dependency (ONNX runtime +
  model download, à la whisper.cpp — net-new bundle weight) and a card-generation
  step in the summary stage + a frontmatter migration (old notes fall back).
- **Revisit:** Batch API if digest volume rises; card default only after an eval
  confirms recall holds.

## Action Items

1. [ ] Track A (free hygiene): cap directions 4→2, drop tags line, flatten tool
   schema, tighten system prompt. Re-measure with the (now-fixed) eval.
2. [ ] Decide Track B scope: do retrieval + card together (recommended), or card
   first (smaller, faster), or retrieval first (bigger quality win).
3. [ ] Card: emit in `summarizer.py`, persist in `markdown_frontmatter.py`, prefer
   in `candidate_assembly._summary_or_excerpt`; eval old-vs-card before default flip.
4. [ ] Retrieval: implement Phase 2 local vector + "propose→narrate" assembly;
   optional 1-day second-brain spike first to de-risk the quality assumption.
5. [ ] Leave Batch/Sonnet/caching/EN-gist explicitly out of scope (documented above).

**Key files:** `src/connections/synthesis.py` (prompt, schema, directions 2–4),
`src/config/config.py` (`SYNTHESIS_MAX_TOKENS`, `MAX_SYNTHESIS_NOTES`, `LLM_MODEL_SYNTHESIS`),
`src/connections/candidate_assembly.py` (`_summary_or_excerpt`, selection),
`src/summarizer.py` (card generation), `src/markdown_frontmatter.py` (persist card).

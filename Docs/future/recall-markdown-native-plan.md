# Plan: Markdown-native recall ("ask your whole corpus") — A + C

**Status:** Proposed (execution-ready, phased for autonomous build)
**Date:** 2026-06-30
**Deciders:** Radek
**Related:** ADR-001 (digest cost + the "card"), ADR-002 (digest retrieval engine). This plan REUSES their engine/store decisions for a *different granularity and feature* (pull/recall), and is explicitly scoped apart from them (see Non-goals).

---

## Goal (one sentence)

Make Malinche's notes substrate **app-agnostic markdown** (A) and add a **local-first "ask your whole corpus" recall** with grounded, citation-backed answers rendered in the existing Konstelacja grammar (C) — so the product delivers the pull/recall the landing already promises, without breaking the local-first privacy wedge.

## Why now

- The landing sells recall hard (step 3 + all four personas) and the product has **none** — pull is the single biggest promise↔product gap.
- "Must be Obsidian" is a shallow coupling (one opener file + digest wikilinks + default path), not a format lock-in — cheap to remove and it strengthens the "your files, any app" wedge.
- The recall engine (local embeddings + vector store) is the *same infrastructure* ADR-001/002 already chose for digest quality — building it for recall delivers that infra too.

## Non-goals (scope fence — do NOT pull these in)

- **ADR-001/002 card + digest retrieval** (note-level card vectors to improve the *push digest*) — a separate quality track. It shares this plan's engine+store but is its own feature; not built here.
- **Cloud PRO knowledge-base / diarization** (`Docs/future/knowledge-base-engine.md`) — out of scope.
- **Local-LLM answer generation as the v1 default** — supported by the architecture, deferred to GA hardening (see Open decision).

---

## Architecture — the reconciled spine

Always-on path is **100% local, zero network**. Only the *answer* step can optionally send retrieved excerpts to Claude.

```
SEARCH / RECALL (pull) — 100% local, NO LLM, nothing ever leaves the Mac:
whisper.cpp transcript
  → chunk: recursive ~350 tok, speaker/topic-aware, small-to-big, with provenance
  → embed: llama.cpp + multilingual GGUF (e5 family), task-prefixed, mean-pool + L2-norm
  → store: sqlite-vec (single file in .malinche/), exact cosine, incremental SQL
  → retrieve: tags (good labeling) ⊕ dense embeddings ⊕ BM25, fused RRF(k=60), parent blocks
  → [optional: local cross-encoder rerank — a ranking model, NOT a generative LLM]
  → present: ranked cited passages (note title + date + verbatim quote + char/ts anchor),
             click → open source. NO synthesized prose, NO hallucination surface.

INSIGHTS (push, and on-demand escalation) — the ONLY place an LLM runs:
  proactive digest (existing Konstelacja) — thesis → cited evidence → directions
  + optional "synthesize these results": hand a retrieved result-set to the insights
    LLM on EXPLICIT user action → renders as a Konstelacja card (only matched
    excerpts leave, only then).
```

### Locked technical decisions

| Decision | Choice | Rationale |
|---|---|---|
| Embedding **runtime** | **llama.cpp** (`llama-embedding` CLI), auto-downloaded via `runtime_deps.py` | 1:1 with the whisper.cpp pattern already shipped — no daemon, no torch, cleanest py2app. (Fallback: `fastembed`/ONNX — but carries onnxruntime native-lib bundling gotcha.) |
| Embedding **model** | **multilingual-e5 family as GGUF** (PL+EN-validated per ADR-002) as primary; **eval EmbeddingGemma-300M** (2026 multilingual SOTA) before locking | Radek's corpus is heavily Polish — do NOT take nomic's English lean. Gemma: ship Q8/BF16 (f16 trap), note non-OSI license if weights are redistributed. |
| **Chunking** | Recursive ~350 tok, ~10–15% overlap (A/B test overlap), pre-segment by speaker/topic, **small-to-big** (embed chunk, return parent block) | Benchmark default; semantic chunking not worth its cost; small-to-big fixes context starvation for spoken snippets. |
| **Provenance** (per chunk) | `chunk_id, note_id, parent_chunk_id, char_start/end, ts_start/end (if available), seq_index, source_version_hash` + one-line contextual header prepended into chunk text | Powers "note X, date, quote (~12:30)" citations; contextual header cuts retrieval failures (~67%, Anthropic-style). |
| **Vector store** | **sqlite-vec** `vault_vectors.db` in `.malinche/`, exact brute-force KNN | At 10k–50k vectors brute force wins; cleanest native story; SQL incremental (insert/delete, no rebuild). Pin the version (pre-v1). Fallback: flat NumPy `.npy`. |
| **Fusion** | **RRF, k=60** over BM25 top-50 ∪ dense top-50 | Rank-based → no score-scale tuning; vendor default; convex combo needs labels we lack. Keep BM25 (wins on names/codes/rare terms). |
| **Search uses NO LLM** | Recall = embeddings + tags + BM25 (+ optional rerank) → ranked cited passages. The LLM is reserved for **insights** only. | Radek's decision: search needs good labeling + vectorization, not generation. Keeps search 100% local, instant, zero-hallucination, zero-cost — nothing ever leaves the Mac for search. |
| **Synthesis-over-results** | Optional explicit escalation: hand a retrieved set to the **insights** LLM (Claude, BYOK) on user action → Konstelacja card. | Covers aggregate/conclude-type questions ("what did I decide about X") without putting an LLM in the raw search path. Mem's "tap on shoulder → deep dive." |
| **Provider swap at EVERY step** | Stay on Claude now, but make provider+model swappable per touchpoint: embeddings · summarizer · synthesis · results-synthesis. Extend `model_router.resolve_model` + `UserSettings`. | Radek's requirement: no hardcoded provider anywhere; each LLM/embedding step independently configurable. |
| **Reranker** | Defer to v1.1; then FlashRank-ONNX (EN) or `bge-reranker-v2-m3` GGUF (multilingual) via the same llama.cpp binary | Biggest single quality lever, latency irrelevant at one-query scale — but adds a model/dep; ship hybrid first, add on eval evidence. |

### Convergence note
The `embeddings.py` engine + `sqlite-vec` store built here are exactly what ADR-002 needs for the digest card-index. Recall uses **chunk-level** vectors over transcript bodies (for citations); ADR-002 uses **note-level** card vectors (for connection-finding). Same engine, two granularities/tables (`chunk_vectors`, later `note_vectors`). Building recall first delivers ADR-002's substrate.

---

## Phased plan (each phase ends at a binary gate → safe for auto-mode)

### Phase 0 — De-risk the two open techs (½–1 day)
- Throwaway script: `llama-embedding` embeds 3 Polish + 2 English sample notes + a query with the chosen GGUF; confirm sane cosine ranking. Verify EmbeddingGemma Q8/BF16 output is non-garbage (f16 trap).
- Confirm `sqlite-vec` `vec0.dylib` loads under the py2app/runtime-deps context.
- **Gate:** sane PL+EN ranking from a local embed + a sqlite-vec round-trip, on Apple Silicon. Locks model + runtime + store before any real build.

### Phase 1 — A: markdown-native decoupling (1–2 days, independent, ship first)
- Replace `obsidian://` URL builder in `src/ui/obsidian_link.py` with a **configurable opener strategy**: Obsidian / Pile / Finder-reveal (`open -R`) / default handler (`open`). Keep `resolve_note_path()` (app-agnostic) as-is.
- `src/connections/digest_writer.py`: make links **portable** — plain titles or relative `[name](name.md)` (configurable; default portable) instead of `[[wikilinks]]`.
- `src/config/defaults.py`: stop hardcoding the Obsidian iCloud path; pick output dir on first run (soften the "iCloud/Obsidian" heuristic in `app_core.py`).
- Add an **in-app dismiss** affordance so dismiss no longer requires editing `dismissed:` frontmatter in a markdown editor (closes the Finder/Pile gap; `dismissals.py` stays as the store).
- New `UserSettings` fields (note-opener app, link style) + Settings UI; `reload_config()` after save.
- **Gate:** point Malinche at a plain folder (or a Pile directory) with no Obsidian installed → transcripts write, digest links resolve via the opener, dismiss works in-app.

### Phase 2 — C engine: ingest → chunk → embed → store → hybrid-retrieve (3–5 days, always-on, offline)
- New `src/connections/embeddings.py`: llama.cpp GGUF embedder (auto-download), e5 task prefixes, mean-pool + L2-norm; sqlite-vec store with the provenance schema; incremental insert/delete at the post-transcription seam (`transcriber.py`); one-time backfill of the existing vault.
- Chunker (recursive ~350 tok, speaker/topic-aware, small-to-big, contextual header).
- Generalize `candidate_assembly._bm25_ranked` to **query→corpus** (currently window→older); add dense top-k; fuse RRF(k=60); return parent blocks.
- **Gate:** CLI `make ask Q="..."` returns hybrid-ranked top-k parent blocks with full provenance, **fully offline**; tests pass with a mocked embedder (no model download in CI).
- **✅ SHIPPED 2026-07-01** — `src/connections/recall/` (chunking · sqlite-vec store · swappable EmbeddingProvider (fastembed) · BM25 lexical · hybrid RRF retriever · indexer · RecallEngine facade · CLI · gated transcription seam). 24 tests green incl. real-fastembed multilingual e2e (PL query → right PL note, offline). Deps auto-install via `runtime_deps`. Embedding model = `paraphrase-multilingual-MiniLM-L12-v2` (light, configurable; e5/EmbeddingGemma are drop-in swaps to eval). Seam opt-in (`ENABLE_RECALL_INDEX`, default off).

### Phase 3 — C results presentation (NO LLM) + optional synthesis escalation (2–3 days)
- **Search results UI (no LLM):** present ranked cited passages — each = note title + date + verbatim quote + char/ts anchor; click → open source in the configured app; honest empty state ("nothing in your notes about X — closest match: …"). Pure retrieval; zero hallucination surface.
- Result payload per hit: `{note title, date, verbatim quote, char-anchor, ts if present, score}`.
- **Optional synthesis escalation (insights path, explicit):** a "synthesize these" action hands the retrieved set to the insights LLM (Claude, BYOK; provider-swappable) → renders a Konstelacja card. Only matched excerpts leave, only on this explicit action — never in the search path. Reuse the **plain-text** call shape from `summarizer.py:216-226` + client/circuit-breaker.
- **Gate:** `ask` returns ranked cited passages fully offline; "synthesize these" produces a grounded Konstelacja card from the result set on demand.
- **🟡 SHIPPED (results half) 2026-07-01** — no-LLM results surface ported 1:1 into `dashboard_window.py`: ask-bar strip (both modes) → local search; ranked cited rows (rank · date · title · verbatim quote · terracotta `↗ otwórz` → configured opener); honest abstinence state (calibrated confidence floor 0.60 on the real vault, dimmed near-miss). Headless brain in `src/ui/recall_presenter.py` + `HybridRetriever.search_scored` confidence = max(dense cosine, lexical overlap). Wired via `menu_app` → `seam.search_safe` (best-effort, shared lazy engine). Native path exercised under real AppKit; 748 tests pass. **Deferred to Phase 4:** the synthesis escalation (the one LLM door). **Open:** ask-bar is now always visible in the Insights window and returns "nothing found" until a backfill exists (auto-backfill = Phase 5) — decide gate-until-M5 vs ship-visible.

### Phase 4 — UX: hotkey ask-bar → Konstelacja-card answer (3–5 days, the "best UX" payoff)
- Global hotkey **ask-bar** (menu-bar native, Spotlight-style), optional **voice-to-ask** (reuse transcription).
- Answer **renders in the Konstelacja window** in the **same thesis → cited-evidence → directions grammar** as the push digest — the one decision that makes pull and push feel like one product (header differs: "You asked" vs "Surfaced for you").
- Click citation → open source in the configured app (Phase 1 opener). **Save answer to vault** as markdown with live citation links. Suggested follow-ups. Resumable thread / recent-asks list.
- Push↔pull link: "ask about this" on every insight card (pre-fills the ask-bar scoped to that insight).
- **Gate:** from anywhere → hotkey → ask → grounded cited answer card in the window → click citation opens the note → save answer. Indistinguishable-as-one-product from the digest.
- **✅ SHIPPED 2026-07-01** — synthesis escalation (the ONE LLM in the pull path) in `src/connections/recall/synthesis.py` (mirrors ConnectionSynthesizer: lazy client, circuit breaker, forced tool-use → schema-validated `RecallAnswer`; model swappable via `resolve_model("results_synthesis")`). Answer card (thesis → cited evidence with ↗ open → follow-up directions) over its grounding; "⤓ Zapisz do notatek" persists a linkable note (`answer_writer.py`, YAML-safe, `_unique_path` collision-safe). Push→pull bridge ("✦ Zapytaj o to" on insights). Hotkey **⌃⌥Space** (best-effort global NSEvent monitor; exclusive chord — NOT ⌥Space) → `focusRecall`; reuses the always-present ask-bar (separate spotlight overlay + voice-to-ask + resumable thread deferred to v1.1). All off-thread with a shared **epoch guard**; APIBillingError trips the shared breaker. Two code-review passes; 789 tests. **Deferred:** voice-to-ask, spotlight-panel visual, recent-asks list.

### Phase 5 — Indexing/onboarding UX + hardening (2–3 days)
- First-run **background backfill** with progress + honest time estimate; **answer-over-partial-index** with a status banner; incremental on new recordings; non-blocking; quiet status chip in the menu (Standby/Indexing/Ready/Error).
- Privacy disclosure copy: **search is 100% local (nothing leaves the Mac);** only **insights** use the cloud key (proactive digest + opt-in "synthesize these"), and only matched excerpts leave. **Sync the landing privacy section to match** — search needs no caveat; insights get an honest, narrow disclosure.
- (Optional) reranker if eval shows the need; (optional) audio-timestamp citations if transcript-format retains whisper segment timestamps.
- **Gate:** a fresh vault of N transcripts indexes in the background with honest progress; recall stays current as new recordings arrive; privacy copy is accurate to behavior.

### Phase 6 — Light markdown browser/reader (self-sufficient standalone; post-lens)

Position: Malinche stands alone on a bare folder — no Obsidian/Pile required. This is the **minimum to browse, read, understand, and lightly edit** notes in-app, **not** an Obsidian replacement. Sequenced after the lens (recall) ships; design (Claude Design brief) can run in parallel now.

- **Browse:** all-notes list (title + date, sort, filter/search → jump). Later: browse-by-topic (direction B — meaning, not folders).
- **Read + understand:** render markdown; frontmatter shown cleanly; summary (card) + transcript sections; **Malinche context on the note** (related insights/connections + tags — what makes it Malinche's reader, not Notepad); recall/insight citations open **here, in-app**, with the fragment highlighted; copy.
- **Edit (minimal):** edit the note body (simple markdown editor / render↔edit toggle), save to disk; light tag/title edit. Caveat: external-edit conflict (Obsidian open on the same file) → save + reload + stale-file warning, no merge.
- **Out of scope (anti-replacement guardrail):** wikilinks/backlinks/graph; plugins/templates/daily-notes/canvas; folder management / file moves; split-view/tabs; WYSIWYG; sync/mobile/collaboration.
- **Gate:** on a bare folder with no Obsidian installed, a user can browse → open → read (with Malinche context) → fix a transcript typo → save; a recall citation opens in the in-app reader.

Reuses: the note-opener strategy (Phase 1) — "open in-app" becomes a first-class opener alongside Obsidian/Pile/Finder; the markdown parsing helpers; the reader surface extends the Konstelacja window grammar.

---

## Key files (grounded in current code)

- **A:** `src/ui/obsidian_link.py` (opener), `src/connections/digest_writer.py` (links), `src/config/defaults.py` + `app_core.py` (default path), `src/connections/dismissals.py` + `dashboard_window.py` (in-app dismiss), `src/config/settings.py` + settings window.
- **C engine:** new `src/connections/embeddings.py`, `src/connections/candidate_assembly.py` (BM25 generalize + parsing reuse), `src/transcriber.py` (embed seam), `runtime_deps.py` (auto-download llama.cpp + model + sqlite-vec).
- **C answer/UX:** `src/summarizer.py` (reuse plain-text call shape), `src/ui/dashboard_window.py` (ask-bar + answer card + citation rows), `src/menu_app.py` (hotkey + callbacks wiring).
- **Config / provider abstraction:** `src/config/config.py` (`LLM_PROVIDER` hardcoded `claude` → make per-step), `model_router.py` (extend `resolve_model` to cover embeddings · summarizer · synthesis · results-synthesis, each provider+model swappable), `settings.py` + Settings UI.
- **Tests:** `tests/` — mock the embedder; `conftest.py` $HOME redirect; `test_connections_assembly.py` note-writer helper pattern.

## Risks & mitigations

1. **sqlite-vec pre-v1** → pin `vec0.dylib`; flat-NumPy fallback (~80 LOC).
2. **llama.cpp × multilingual GGUF** unverified → Phase 0 spike gates it; EmbeddingGemma f16 trap → Q8/BF16.
3. **Timestamp citations depend on stored timestamps** → the `## Transkrypcja` body is plain text today; v1 cites note+date+quote+char-anchor; audio-timestamp citation is gated on a transcript-format change to retain whisper segments.
4. **Decontextualized spoken chunks** ("he said it was fine") → contextual-header prepend.
5. **Provenance drift on re-transcription** → key chunks by `source_version_hash`, re-embed on change.
6. **Local-LLM UX cliff** (7–8B slow on long RAG context) → exactly why Claude-on-excerpts is a first-class v1 path, not an afterthought.
7. **py2app bundle weight** → GGUF + sqlite-vec are clean; avoid torch/sentence-transformers; onnxruntime only if the fastembed fallback is used.
8. **New deps via `runtime_deps.py` auto-download, NOT `requirements.txt`** (project rule: whisper.cpp/ffmpeg pattern).

## Decisions taken (2026-06-30)

- **Search = embeddings + tags + BM25, NO LLM.** Recall surfaces ranked cited passages; the LLM is reserved for insights. Search stays 100% local — nothing leaves the Mac. Fully resolves the landing privacy gap (search needs no disclosure; only insights touch the cloud key).
- **LLM (Claude, BYOK) only at insights:** the existing proactive digest + an optional on-demand "synthesize these results" escalation. Local-LLM for insights deferred to GA.
- **Provider + model swappable at every step.** Stay on Claude now; build the abstraction so embeddings · summarizer · synthesis · results-synthesis are each independently configurable (no hardcoded provider).
- **Positioning refined (2026-07-01): self-sufficient standalone, NOT lens-only and NOT an Obsidian replacement.** The recall/insights layer stays the moat, but Malinche must also stand alone on a **bare folder** — a user with no Obsidian/Pile still gets value. A **light in-app browse/read/edit** (Phase 6) delivers that minimum; handoff-to-external-app becomes **optional**, not required. Corrects the earlier "lens + handoff-only" framing, which re-introduced the very dependency the pivot rejected. Browsing is by **meaning** (topics), never a raw folder tree (that duplicates Obsidian at its strongest). Guardrail against replacement: no wikilinks/backlinks/graph, plugins, folder management, or WYSIWYG.

## UX must-haves (condensed; full set in research)

Hotkey ask-bar from anywhere · claim-level inline citations (title+date+quote+ts) · click→open source in user's app · honest abstention · streamed answer with citations attached to claims · answer in the Konstelacja grammar (same window as push) · save-answer-to-vault with live links · suggested follow-ups · background non-blocking indexing with honest progress · resumable thread. **Nice-to-have:** voice-to-ask, temporal/scope selectors, `/notes` corpus-only toggle, retrieval-transparency expander, push↔pull links, drag-cited-source-into-note, carry citations into the Claude/ChatGPT handoff.

## References

Internal: ADR-001, ADR-002. External (selected): [llama.cpp embeddings](https://github.com/ggml-org/llama.cpp/discussions/7712), [nomic-embed-text-v1.5 GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF), [EmbeddingGemma](https://huggingface.co/blog/embeddinggemma), [sqlite-vec](https://github.com/asg017/sqlite-vec), [RRF (Azure)](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking), [chunking benchmark (Chroma)](https://www.trychroma.com/research/evaluating-chunking), [small-to-big retrieval](https://medium.com/data-science/advanced-rag-01-small-to-big-retrieval-172181b396d4), [NotebookLM design](https://jasonspielman.com/notebooklm), [Granola chat](https://www.granola.ai/blog/chat-with-meetings-search-analyze-ai-2026), [Mem Heads Up](https://get.mem.ai/features/heads-up), [Smart Connections](https://smartconnections.app/smart-connections/), [RAG trust user study](https://arxiv.org/pdf/2601.14460).

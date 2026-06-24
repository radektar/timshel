# ADR-002: Retrieval engine for the connection digest — reuse second-brain's recipe, locally

**Status:** Proposed
**Date:** 2026-06-23
**Deciders:** Radek
**Related:** ADR-001 (digest cost). Answers "we already have second-brain on embeddings — optimise it for this project."

## Context

Malinche needs semantic retrieval to (a) cure the "30 diverse notes → 0 connections"
dilution and (b) reach temporally-distant-but-similar notes (where
`contradiction-over-time` lives). The question: reuse the existing `second_brain`
embedding system instead of building a new one.

I read the full `~/CODE/second_brain` setup. **Key correction to an earlier
assumption: the embedding engine is already 100% local.** Only the *database host*
is cloud.

### second-brain, as actually built

| Layer | Implementation | Verdict for Malinche |
|---|---|---|
| **Vectorisation engine** | `multilingual-e5-base`, **768-dim**, run **on-device** via HuggingFace Transformers.js (`@huggingface/transformers`), fp32, mean-pooled + L2-normalised, e5 task prefixes (`query:` / `passage:`), cosine. **No API key.** Model cached in `~/.cache/huggingface`. | **The crown jewel. Reuse the recipe** — it's validated on Radek's real PL+EN vault. |
| **Chunking / tokenisation** | `chunker.ts`: split on H2+, merge short, sliding window (max 400 / overlap 50 / min 50 tok), synthetic `metadata` chunk from frontmatter. `estimateTokens = chars/4` (under-counts Polish, which is ~2 chars/tok). Many chunks per note over the **full transcript**. | **Change.** Wrong granularity for connection-finding (averages dozens of transcript chunks into a blurry note vector). |
| **DB / storage** | Supabase/Postgres + pgvector, `ivfflat(lists=100, cosine)`, RLS-deny-by-default (service-role bypass), `search_notes(vec768, count, thr=0.3)` SQL RPC. `notes`(frontmatter jsonb, gin-indexed) + `note_chunks`(vector(768)). MD5 change-detection. There is a `migrate_to_local.sql` (they already migrated OpenAI-1536 → local-e5-768). | **Change host.** Cloud breaks 100%-local positioning; whole-vault scope leaks non-transcripts. |
| **Retrieval tools** | `search_notes` ✅ works (cosine, threshold 0.3, optional AND tag-filter on frontmatter). `find_related` ❌ **broken**: `select embedding` returns pgvector as a **string**, `meanPooling` does arithmetic on it as if `number[]` → garbage vector → "invalid input syntax for type vector". Also mean-pools all chunks (blurry) and is cloud + whole-vault. | `search_notes` pattern ✅. `find_related` impl ❌ — but its *concept* is exactly Malinche's need; do it right. |
| **Tagging** | Tags live in note frontmatter (jsonb, gin index); used as an AND filter. second-brain does **not** generate tags — it consumes them. | **Already aligned.** Malinche's own `tagger.py` + `TagIndex` produce the same frontmatter tags. No new tagging engine. |
| **Sync / freshness** | `npm run sync` (cron), globs vault, MD5 diff, re-embeds changed. Staleness between cron runs (documented caveat). | **Don't depend on it.** Malinche needs fresh-at-transcription. |

## Decision

**Reuse second-brain's embedding *recipe*, not its hosted *infrastructure*.** Build a
local, transcript-scoped, fresh-at-transcription twin inside Malinche. Do **not**
put the cloud Supabase instance in the value path (positioning + whole-vault scope
+ cron staleness + broken `find_related` + wrong granularity all disqualify it).

**The unlock that ties this to ADR-001:** the **synthesis card** (Teza / Stanowisko /
Klucz, ~343 tokens) we designed for cost compression is *also* the ideal embedding
input — one compact, signal-dense vector per note, well under e5's 512-token limit,
no chunking, no transcript noise. **One artifact, two wins** (cheap synthesis input
+ sharp note vector).

### What must change, per layer

1. **Engine — reuse the recipe in Python.** Same model (`multilingual-e5-base`),
   same prefixes, same mean-pool + normalise, same cosine. Implement via
   **`fastembed` (ONNX, no PyTorch)** so it fits Malinche's "ONNX-style runtime dep,
   auto-downloaded like whisper.cpp" pattern — the model is *not* bundled, it
   downloads on first use. Internal consistency is guaranteed because Malinche
   embeds both stored cards and queries with the same engine. (e5-**small** is the
   lighter fallback if base's download weight matters; base is what second-brain
   validated.)
2. **Granularity — one vector per note = the card.** Drop chunking entirely for the
   digest path. Embed the synthesis card as a single `passage:`; embed a window
   note's card as the `query:`.
3. **Storage — local, single-file.** **`sqlite-vec`** (one file in `.malinche/`,
   appliance-friendly, mirrors the existing `VaultIndex`/`DismissalStore` local-file
   pattern) over running a local Postgres. Port second-brain's minimal idea, not its
   server: a flat `note_vectors(fingerprint, basename, card, embedding)` table; for a
   few hundred notes an **exact cosine scan is instant** (no ivfflat/`analyze`
   needed). Drop RLS (single-user, local).
4. **Retrieval — "propose → narrate."** Per window note, cosine top-K its card
   against the store → a tight 5–6-note cluster → Opus narrates only that. This is
   `find_related` done right (single sharp card-vector, local, transcript-scoped).
   Keep cosine threshold ~0.3 as a starting point (second-brain's value).
5. **Tagging — no change.** Reuse Malinche's frontmatter tags as a **hybrid** signal
   layered on the vector hits (semantic ∪ tag-bridge), which `candidate_assembly`
   already blends with BM25. Embeddings *add* a signal; they don't replace the
   tag/lexical ones.
6. **Freshness — embed at transcription time.** Generate the card and its embedding
   at the existing post-transcription seam (fingerprint-keyed, same place the card is
   produced per ADR-001). No cron, always fresh.

### Vector-space compatibility (enables a cheap spike)
Because the recipe is identical on both sides, a locally-computed e5-base query
vector is compatible with second-brain's stored 768-d vectors. So a **1–2 day spike**
can validate "semantic retrieval makes better digests" *without building the twin*:
compute the query card-embedding locally → call second-brain's `search_notes` RPC →
filter results to `11-Transcripts/`. Accept the cloud + staleness **for the
experiment only**, then build the local twin if the quality lift is real.

## Options Considered

| Option | What | Verdict |
|---|---|---|
| **A. Local twin (recipe-reuse)** | fastembed e5-base + sqlite-vec, card-vectors, embed-at-transcription | **Adopt** — keeps 100%-local, fresh, scoped, sharp. |
| B. Client of cloud second-brain | Malinche calls the live Supabase instance | **Reject for value path** (positioning, whole-vault scope, staleness, broken find_related). **Use only as the spike.** |
| C. Local Postgres + pgvector (their schema verbatim) | Run Postgres locally, reuse `search_notes` SQL | **Reject** — a Postgres server is heavy for a menu-bar appliance; sqlite-vec gives the same result with zero daemon. |
| D. New/different embedding model | Pick a fresh model | **Reject** — e5-base is already validated on his PL+EN data; don't relitigate a solved choice. |

## Consequences
- **Easier:** retrieval becomes local, fresh, scoped; the card does double duty;
  the embedding choice is de-risked (proven on his vault).
- **Harder:** new on-device dependency (fastembed/ONNX + e5 model download) and
  sqlite-vec; a one-time backfill to embed existing notes' cards; a parity note if
  we ever want cross-compatibility with second-brain's stored vectors.
- **Revisit:** ivfflat/hnsw only if the corpus reaches tens of thousands of notes
  (flat scan is fine for hundreds–low-thousands).

## Action Items
1. [ ] (Optional, 1–2 d) **Spike** on the live second-brain instance to confirm the
   quality lift before building. Scope results to `11-Transcripts/`.
2. [ ] Python e5-base embedder via fastembed (auto-download pattern), same
   prefixes/pooling as `embedder.ts`.
3. [ ] `sqlite-vec` store in `.malinche/`; embed card at the post-transcription seam;
   one-time backfill.
4. [ ] Rework `candidate_assembly` to "propose → narrate" (semantic top-K ∪ tag/BM25),
   feeding the tight cluster to synthesis.
5. [ ] (Nice-to-have) Send second-brain a fix for `find_related`'s pgvector-string
   deserialisation — independent of Malinche, but it's a real bug.

**Files (Malinche):** `src/connections/candidate_assembly.py` (retrieval),
new `src/connections/embeddings.py` (engine + store), `src/transcriber.py` (seam),
`src/summarizer.py` (card, per ADR-001). **Reference (second_brain):**
`src/sync/embedder.ts` (recipe), `src/db/schema.sql` (schema), `src/tools/find-related.ts` (the pattern, and the bug to avoid).

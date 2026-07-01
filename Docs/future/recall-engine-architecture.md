# Recall engine — code architecture (Phase 2–3)

**Status:** Proposed (implementation-ready)
**Date:** 2026-06-30
**Related:** `recall-markdown-native-plan.md` (the plan), ADR-001/002 (digest retrieval — shares the engine), the in-repo code map.

Scope: the **local, no-LLM** retrieval engine — `ingest → chunk → embed → store → hybrid-retrieve` — plus the results contract. Search runs **fully offline**; the only optional cloud call is the explicit "synthesize these results" escalation (insights LLM). UI is Phase 4 (Claude Design brief). The digest/insights path is unchanged.

---

## Package layout (new)

`src/connections/recall/`:

| Module | Responsibility |
|---|---|
| `embedding.py` | `EmbeddingProvider` protocol + impls + resolver (the "swap at every step" keystone) |
| `chunking.py` | transcript → chunks with provenance (recursive ~350 tok, small-to-big) |
| `vector_store.py` | `sqlite-vec` store: upsert / delete / KNN (flat cosine) |
| `retriever.py` | `HybridRetriever`: BM25 ⊕ dense, RRF(k=60), parent-block expansion |
| `results.py` | `Result`/`Citation` payload (UI-facing) + optional `synthesize()` escalation hook |

Reuses: `candidate_assembly` (parsing helpers + generalized BM25), `config`/`model_router` (provider abstraction), `transcriber` (embed seam), `runtime_deps` (auto-download).

---

## Provider abstraction — "swap at every step" (Radek's requirement)

No hardcoded provider anywhere. A `Protocol` + a resolver mirroring the existing `model_router.resolve_model`.

```python
class EmbeddingProvider(Protocol):
    model_id: str
    dim: int
    def embed_documents(self, texts: list) -> list: ...   # "passage:" prefix, mean-pool, L2-norm
    def embed_query(self, text: str) -> list: ...          # "query:" prefix
```

- Impls: `FastembedProvider` (Phase-0-proven, ONNX, pip), `LlamaCppProvider` (GGUF, bundling-primary, whisper.cpp pattern), `OllamaProvider` (optional, local daemon).
- Selection: `model_router.resolve_embedder()` reads `Config.EMBED_PROVIDER` / `EMBED_MODEL`. **Embeddings are local + no API key** by contract.
- Per-step model ids extend `resolve_model`: `"summary"`, `"synthesis"`, **`"recall_synthesis"`** (the escalation) — each provider+model independently configurable in `UserSettings` + Settings UI. Call `reload_config()` after save.
- Internal consistency: stored chunks and queries embed through the *same* provider instance.

The embedding-runtime choice (llama.cpp vs fastembed) is settled by a **py2app bundling test in P2.1**; the abstraction makes it swappable, so the decision is low-risk and reversible.

---

## Data contracts (dataclasses)

```python
@dataclass(frozen=True)
class Chunk:
    note_id: str           # basename / stable id
    seq: int               # order within the note
    text: str              # the chunk (with contextual header prepended)
    char_start: int        # anchor into the markdown body
    char_end: int
    ts_start: float | None # audio timestamp if the transcript retains it
    ts_end: float | None
    parent_text: str       # the surrounding topic block (small-to-big)
    version_hash: str      # source_version_hash; re-embed on change

@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    channel: str           # "dense" | "lexical" | "fused"

@dataclass(frozen=True)
class Result:              # UI-facing (Phase 4 renders this; NO LLM)
    note_title: str
    date: str
    quote: str             # verbatim snippet
    char_anchor: int
    ts: float | None
    score: float
    parent_text: str       # fed to synthesis escalation, not shown raw
```

---

## Chunking (`chunking.py`)

- Input = the `## Transkrypcja` body (via `candidate_assembly._body_after_frontmatter`, marker is language-stable Polish per template).
- Recursive split ~350 tokens, ~10–15% overlap (**A/B test overlap** — 2026 evidence is mixed); hard-capped under the embedder's max sequence length.
- Pre-segment by speaker turn / topic boundary where detectable; recurse inside.
- **Small-to-big:** embed the ~350-tok chunk, carry the parent topic block (~1–2k tok) for the answerer/escalation.
- **Contextual header** prepended into chunk text (note title + date + speaker) — cuts retrieval failures (~67%, Anthropic-style); decontextualized spoken snippets ("he said it was fine") are the failure mode this guards.
- Provenance fully populated. **Note vs ADR-002:** recall chunks the *transcript* (citations need passage-level); ADR-002's digest path embeds one *card* vector per note — separate granularity, same engine/store.

---

## Vector store (`vector_store.py`, sqlite-vec)

- One file: `{vault}/.malinche/vault_vectors.db` (mirrors `VaultIndex`/`DismissalStore` local-file pattern).
- `CREATE VIRTUAL TABLE chunk_vectors USING vec0(embedding float[D])` + a metadata table keyed by `chunk_id` (note_id, seq, char_start/end, ts_*, version_hash, text, parent_text).
- **Flat brute-force cosine** (exact) — correct at 10k–50k vectors; no ivfflat/HNSW. L2 over L2-normalized vectors == cosine order.
- API: `upsert_note(note_id, stored_chunks)`, `delete_note(note_id)`, `knn(query_vec, k) -> list[Hit]`, `count()`.
- Incremental: new transcript → insert; edit/re-transcription → `delete_note` + insert (keyed by `version_hash`); no rebuild.
- **Pin the sqlite-vec version** (pre-v1). Documented fallback: flat NumPy `.npy` + sidecar (~80 LOC) if the extension can't load.

---

## Retriever (`retriever.py`, hybrid)

`HybridRetriever.search(query: str, k: int = 8) -> list[Result]`:

1. `embed_query(query)` → dense KNN top-50 from the store.
2. BM25 top-50 — **generalize `candidate_assembly._bm25_ranked`** to take query tokens vs the whole corpus (today it ranks `older` vs a `window` and excludes the window — small refactor, shared by digest + recall).
3. Fuse with **RRF, k=60** (rank-based → no score-scale tuning; BM25 unbounded vs cosine 0.33–1.0).
4. Map fused chunk hits → **parent blocks** → `Result[]`. Dense threshold ~0.3 to start.
5. **No LLM.** Optional cross-encoder rerank in v1.1 (FlashRank-ONNX or bge-reranker-v2-m3 GGUF) — latency irrelevant at one-query scale.

Lexical wins on names/codes/rare terms; dense wins on paraphrase/concept; hybrid beats either.

---

## Results + escalation (`results.py`)

- `Result[]` is the pure search payload the UI renders (Phase 4). Honest abstention when retrieval is thin: return empty/weak with the closest snippet.
- `synthesize(results, query) -> Card` — **optional, explicit escalation only.** Routes the parent blocks to the insights LLM via `resolve_model("recall_synthesis")`, reusing the **plain-text** call shape from `summarizer.py:216-226` + the client/circuit-breaker plumbing (NOT synthesis.py's forced-tool shape). Produces a Konstelacja card (thesis/evidence/directions). Only matched excerpts leave the Mac, only on this action.

---

## Integration seams

- **Transcription (fresh-at-transcription):** at the post-transcript seam (`transcriber.py` ~1891, where `scheduler.register_new_notes` is called), chunk + embed + `upsert_note`. A `make backfill-embeddings` command embeds the existing vault once (background, non-blocking — Phase 5 UX).
- **`candidate_assembly`:** extract the generalized BM25 so digest and recall share one lexical channel.
- **`config` / `model_router`:** add `EMBED_PROVIDER`, `EMBED_MODEL`, `LLM_MODEL_RECALL_SYNTHESIS`; `resolve_embedder()`; fields in `UserSettings` + `to_dict` + Settings UI; `reload_config()` on save.
- **`runtime_deps`:** register the embedding runtime via the **auto-download** pattern (llama.cpp binary via an install script like `install_whisper_cpp.sh`, or fastembed/onnxruntime into the pip target) — **never `requirements.txt`** (project rule).
- **`menu_app` / `dashboard_window`:** the `ask` callback + results rendering — Phase 4, per the Claude Design brief (`design-system/pages/recall-window-extension-brief.md`).

---

## Build order (each step a gate; auto-mode friendly)

| Step | Deliverable | Gate |
|---|---|---|
| P2.1 | `EmbeddingProvider` + resolver + FastembedProvider; py2app bundling spike | embed query/doc; sane PL+EN cosine (Phase-0 proven); bundling verdict on runtime |
| P2.2 | `vector_store` (sqlite-vec) | in-memory + on-disk upsert/knn/delete tests green |
| P2.3 | `chunking` + provenance + contextual header | transcript → chunks with anchors; tests |
| P2.4 | transcription seam + `backfill-embeddings` | new transcript auto-embeds; backfill runs |
| P2.5 | `HybridRetriever` (generalized BM25 + RRF) | **`make ask Q=…` returns offline top-k Results with provenance** |
| P3.1 | `results` + abstention | thin retrieval → honest empty, no fabrication |
| P3.2 | `synthesize()` escalation (insights LLM) | result-set → Konstelacja card on explicit call |

## Open / risks

- **Embedding runtime** (llama.cpp vs fastembed): decided at P2.1 by bundle weight; abstraction makes it swappable.
- **Timestamp provenance** depends on the transcript retaining whisper segment timestamps; today `## Transkrypcja` is plain text → v1 citations are note + date + char-anchor; audio-ts is a transcript-format follow-on.
- **sqlite-vec pre-v1** → pin; NumPy fallback.
- **py2app bundle weight** → GGUF + sqlite-vec clean; avoid torch; onnxruntime native-lib collection only if fastembed wins.

"""Hybrid retrieval: dense (sqlite-vec) + lexical (BM25), fused with RRF.

No LLM, no network. Returns ranked ``Result``s carrying the small-to-big parent
block for the UI to render and cite. An explicit "synthesize these results"
escalation (outside this package) is the only path that reaches an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from src.connections.recall.embedding import EmbeddingProvider
from src.connections.recall.lexical import bm25_rank
from src.connections.recall.vector_store import Hit, VaultVectorStore


@dataclass(frozen=True)
class Result:
    """A retrieved passage — the UI payload. Pure retrieval; nothing generated."""

    note_id: str
    quote: str  # verbatim passage — the citation
    parent_text: str  # surrounding block (small-to-big)
    char_start: int
    char_end: int
    score: float  # fused RRF score
    channels: str  # which channels found it: "dense", "lexical", "dense+lexical"


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], k: int = 60) -> List[Tuple[int, float]]:
    """RRF over rank lists — rank-based, so BM25/cosine score scales never collide."""
    scores: Dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


class HybridRetriever:
    """Fuse dense KNN and BM25 over the vault's chunks."""

    def __init__(
        self,
        store: VaultVectorStore,
        embedder: EmbeddingProvider,
        *,
        dense_k: int = 50,
        lexical_k: int = 50,
        rrf_k: int = 60,
    ):
        self._store = store
        self._embedder = embedder
        self._dense_k = dense_k
        self._lexical_k = lexical_k
        self._rrf_k = rrf_k

    def search(self, query: str, k: int = 8) -> List[Result]:
        query = (query or "").strip()
        if not query:
            return []
        all_hits = self._store.all_chunks()
        if not all_hits:
            return []
        by_id: Dict[int, Hit] = {h.chunk_id: h for h in all_hits}

        query_vec = self._embedder.embed_query(query)
        dense_ids = [h.chunk_id for h in self._store.knn(query_vec, self._dense_k)]
        # Fold the note_id (the filename/title) into each chunk's lexical doc. Proper
        # nouns, names and codes often live in the title but barely in the spoken body
        # (whisper rarely repeats a name) — without this, BM25 can't match them and the
        # channel loses exactly the named-entity queries it's meant to win.
        lexical_ids = bm25_rank(
            query,
            [(h.chunk_id, f"{h.note_id}\n{h.text}") for h in all_hits],
            limit=self._lexical_k,
        )

        dense_set, lex_set = set(dense_ids), set(lexical_ids)
        fused = reciprocal_rank_fusion([dense_ids, lexical_ids], k=self._rrf_k)

        results: List[Result] = []
        for chunk_id, score in fused[:k]:
            hit = by_id.get(chunk_id)
            if hit is None:
                continue
            channels = "+".join(
                c for c, present in (("dense", chunk_id in dense_set), ("lexical", chunk_id in lex_set)) if present
            )
            results.append(
                Result(
                    note_id=hit.note_id,
                    quote=hit.text,
                    parent_text=hit.parent_text,
                    char_start=hit.char_start,
                    char_end=hit.char_end,
                    score=score,
                    channels=channels,
                )
            )
        return results

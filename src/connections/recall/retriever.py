"""Hybrid retrieval: dense (sqlite-vec) + lexical (BM25), fused with RRF.

No LLM, no network. Returns ranked ``Result``s carrying the small-to-big parent
block for the UI to render and cite. An explicit "synthesize these results"
escalation (outside this package) is the only path that reaches an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from src.connections.candidate_assembly import _tokenize
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


def cosine_from_l2(distance: float) -> float:
    """Recover cosine similarity from sqlite-vec's L2 distance on unit vectors.

    Vectors are L2-normalized upstream, so ``||a-b||^2 = 2 - 2·cos`` → ``cos = 1 - d^2/2``.
    Clamped to ``[0, 1]`` to serve as a plain confidence signal for the results UI.
    """
    cos = 1.0 - (float(distance) ** 2) / 2.0
    return max(0.0, min(1.0, cos))


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
        return self.search_scored(query, k=k)[0]

    def search_scored(self, query: str, k: int = 8) -> Tuple[List[Result], float]:
        """Like :meth:`search`, plus a confidence signal in ``[0, 1]``.

        RRF always returns *something* while the store is non-empty, so "nothing about
        X" can't be decided by row count. Confidence is the stronger of two evidences:
        the top dense cosine similarity (semantic closeness) and the literal term
        overlap of the top hit (lexical closeness). Named-entity queries win via
        lexical, not dense — a dense-only floor would wrongly abstain on exactly the
        title matches the lexical channel is there to catch.
        """
        query = (query or "").strip()
        if not query:
            return [], 0.0
        all_hits = self._store.all_chunks()
        if not all_hits:
            return [], 0.0
        by_id: Dict[int, Hit] = {h.chunk_id: h for h in all_hits}

        query_vec = self._embedder.embed_query(query)
        dense_hits = self._store.knn(query_vec, self._dense_k)
        dense_ids = [h.chunk_id for h in dense_hits]
        top_sim = cosine_from_l2(dense_hits[0].distance) if dense_hits else 0.0
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

        confidence = top_sim
        if results:
            q_tokens = set(_tokenize(query))
            if q_tokens:
                doc_tokens = set(_tokenize(f"{results[0].note_id}\n{results[0].quote}"))
                overlap = len(q_tokens & doc_tokens) / len(q_tokens)
                confidence = max(confidence, overlap)
        return results, confidence

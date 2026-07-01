"""BM25 lexical channel of hybrid retrieval (query -> whole corpus).

Reuses the connection layer's PL+EN tokenizer so the lexical and semantic channels
normalize identically. A personal vault is at most tens of thousands of chunks, so an
in-memory scan per query is instant — no separate lexical index needed.

Lexical earns its place next to embeddings on exact names, codes, acronyms and rare
terms, where dense vectors blur.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Sequence, Tuple

from src.connections.candidate_assembly import _tokenize


def bm25_rank(
    query: str,
    docs: Sequence[Tuple[int, str]],
    *,
    k1: float = 1.5,
    b: float = 0.75,
    limit: int = 50,
) -> List[int]:
    """Return doc ids ranked by BM25 relevance to ``query`` (best first)."""
    q_terms = set(_tokenize(query))
    if not q_terms or not docs:
        return []

    tokenized = [(doc_id, _tokenize(text)) for doc_id, text in docs]
    n = len(tokenized)
    avgdl = (sum(len(toks) for _, toks in tokenized) / n) if n else 0.0

    df: Dict[str, int] = {}
    for _, toks in tokenized:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    idf = {
        t: math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
        for t in q_terms
    }

    scored: List[Tuple[float, int]] = []
    for doc_id, toks in tokenized:
        if not toks:
            continue
        tf = Counter(toks)
        dl = len(toks)
        score = 0.0
        for t in q_terms:
            freq = tf.get(t, 0)
            if not freq:
                continue
            denom = freq + k1 * (1 - b + b * dl / avgdl) if avgdl else freq + k1
            score += idf[t] * (freq * (k1 + 1)) / denom
        if score > 0:
            scored.append((score, doc_id))

    scored.sort(reverse=True)
    return [doc_id for _, doc_id in scored[:limit]]

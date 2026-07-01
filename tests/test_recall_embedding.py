"""Embedding provider abstraction + a real (slow) fastembed integration check."""

from __future__ import annotations

import math

import pytest

from src.connections.recall.embedding import (
    DEFAULT_EMBED_MODEL,
    EmbeddingProvider,
    l2_normalize,
    resolve_embedder,
)


class _Fake:
    model_id = "f"
    dim = 3

    def embed_documents(self, texts):
        return [[0.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [0.0, 0.0, 0.0]


def test_fake_satisfies_provider_protocol():
    assert isinstance(_Fake(), EmbeddingProvider)


def test_l2_normalize_unit_length_and_zero_safe():
    v = l2_normalize([3.0, 4.0])
    assert abs(math.sqrt(v[0] ** 2 + v[1] ** 2) - 1.0) < 1e-6
    assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]


def test_resolve_unknown_provider_raises():
    with pytest.raises(ValueError):
        resolve_embedder(provider="bogus", model="whatever")


@pytest.mark.integration
@pytest.mark.slow
def test_fastembed_real_multilingual_roundtrip():
    emb = resolve_embedder(provider="fastembed", model=DEFAULT_EMBED_MODEL)
    q = emb.embed_query("dostawa okien i dach")
    d = emb.embed_documents(["producenci okien nie odpowiadaja"])[0]
    assert len(q) == emb.dim == len(d)
    assert abs(math.sqrt(sum(x * x for x in q)) - 1.0) < 1e-4
    # PL query ~ PL doc about the same topic: cosine (dot of unit vecs) clearly positive
    cos = sum(a * b for a, b in zip(q, d))
    assert cos > 0.4

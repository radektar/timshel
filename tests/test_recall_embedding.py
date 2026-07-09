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


def test_fastembed_provider_forwards_threads(monkeypatch):
    """The ONNX thread cap must reach fastembed's TextEmbedding — without it
    onnxruntime takes all cores and oversubscribes against whisper-cli."""
    import sys
    import types

    captured = {}

    class _FakeTextEmbedding:
        def __init__(self, model_name=None, threads=None, **kwargs):
            captured["model_name"] = model_name
            captured["threads"] = threads

        def embed(self, texts):
            return iter([[0.0, 0.1, 0.2]])

    fake_mod = types.ModuleType("fastembed")
    fake_mod.TextEmbedding = _FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake_mod)
    monkeypatch.setattr("src.runtime_deps.ensure_importable", lambda name: None)

    from src.connections.recall.embedding import FastembedProvider

    provider = FastembedProvider("some-model", threads=3)

    assert captured["threads"] == 3
    assert provider.dim == 3


def test_resolve_embedder_cache_key_includes_threads(monkeypatch):
    """A changed thread cap must build a fresh provider, not return the old one."""
    from src.connections.recall import embedding as emb_mod

    built = []

    class _StubProvider:
        def __init__(self, model, threads=None):
            built.append(threads)

    monkeypatch.setattr(emb_mod, "FastembedProvider", _StubProvider)
    monkeypatch.setattr(emb_mod, "_CACHE", {})

    first = emb_mod.resolve_embedder(provider="fastembed", model="m", threads=2)
    again = emb_mod.resolve_embedder(provider="fastembed", model="m", threads=2)
    other = emb_mod.resolve_embedder(provider="fastembed", model="m", threads=4)

    assert built == [2, 4]  # cache hit for the repeat, rebuild for new cap
    assert first is again and first is not other


def test_embed_threads_auto_default(monkeypatch):
    """Config.EMBED_THREADS auto = half the cores, floor 1."""
    import os

    from src.config.config import Config

    # src.config.config is proxied in sys.modules, so patch os directly.
    monkeypatch.setattr(os, "cpu_count", lambda: 10)
    assert Config().EMBED_THREADS == 5
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert Config().EMBED_THREADS == 1


def test_embed_threads_user_override(monkeypatch, tmp_path):
    """A positive embed_threads in settings wins over the auto default."""
    from src.config.config import Config
    from src.config.settings import UserSettings

    config_file = tmp_path / "config.json"
    monkeypatch.setattr(
        UserSettings, "config_path", staticmethod(lambda: config_file)
    )
    UserSettings.mutate(lambda s: setattr(s, "embed_threads", 2))

    assert Config().EMBED_THREADS == 2


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

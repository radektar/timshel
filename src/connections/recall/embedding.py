"""Embedding providers — local, and swappable at every step (project requirement).

Search must stay fully local; embeddings never hit the network. The provider is an
interface, so the runtime (fastembed/ONNX today, llama.cpp GGUF later) swaps via
config without touching callers. Model + provider are read from ``Config``
(``EMBED_PROVIDER`` / ``EMBED_MODEL``); nothing is hardcoded in the call sites.
"""

from __future__ import annotations

import math
from typing import List, Optional, Protocol, Sequence, runtime_checkable

# Light, multilingual, and proven on Radek's PL+EN data in the Phase-0 spike.
# Configurable; e5-base/large (ADR-002) or an EmbeddingGemma GGUF are drop-in swaps.
DEFAULT_EMBED_PROVIDER = "fastembed"
DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@runtime_checkable
class EmbeddingProvider(Protocol):
    """What retrieval needs from any embedding backend."""

    model_id: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]: ...

    def embed_query(self, text: str) -> List[float]: ...


def l2_normalize(vec: Sequence[float]) -> List[float]:
    """Unit-normalize so cosine order == the store's L2 distance order."""
    norm = math.sqrt(sum(float(x) * float(x) for x in vec))
    if norm <= 0:
        return [float(x) for x in vec]
    return [float(x) / norm for x in vec]


class FastembedProvider:
    """fastembed (ONNX, torch-free). e5-family models get the query:/passage: prefixes.

    ``threads`` caps onnxruntime's intra/inter-op pools (fastembed forwards it
    to SessionOptions). ``None`` = library default = ALL cores, which
    oversubscribes against a concurrent whisper-cli (cores-2) — pass the
    Config cap in production.
    """

    def __init__(
        self, model_name: str = DEFAULT_EMBED_MODEL, threads: Optional[int] = None
    ):
        from src.runtime_deps import ensure_importable

        ensure_importable("fastembed")
        from fastembed import TextEmbedding  # lazy: keep package import light

        self._model = TextEmbedding(model_name=model_name, threads=threads)
        self.model_id = model_name
        self._e5 = "e5" in model_name.lower()
        probe = next(iter(self._model.embed(["dim probe"])))
        self.dim = len(list(probe))

    def _prep(self, text: str, kind: str) -> str:
        return f"{kind}: {text}" if self._e5 else text

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        prepped = [self._prep(t, "passage") for t in texts]
        return [l2_normalize(v) for v in self._model.embed(prepped)]

    def embed_query(self, text: str) -> List[float]:
        vec = next(iter(self._model.embed([self._prep(text, "query")])))
        return l2_normalize(vec)


_CACHE: dict = {}


def resolve_embedder(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    threads: Optional[int] = None,
) -> EmbeddingProvider:
    """Build (and cache) the configured provider. Reads ``Config`` when args omitted."""
    if provider is None or model is None or threads is None:
        try:
            from src.config.config import get_config

            cfg = get_config()
            provider = provider or getattr(cfg, "EMBED_PROVIDER", DEFAULT_EMBED_PROVIDER)
            model = model or getattr(cfg, "EMBED_MODEL", DEFAULT_EMBED_MODEL)
            if threads is None:
                threads = getattr(cfg, "EMBED_THREADS", None)
        except Exception:  # pragma: no cover - config unavailable in isolated tests
            provider = provider or DEFAULT_EMBED_PROVIDER
            model = model or DEFAULT_EMBED_MODEL

    # Fall back to defaults if config lookup left anything unset (keeps the
    # types concrete for the cache key + provider construction below).
    provider = provider or DEFAULT_EMBED_PROVIDER
    model = model or DEFAULT_EMBED_MODEL

    # threads is part of the key: a settings change must not silently return
    # an engine still running on the old thread cap.
    key = (provider, model, threads)
    if key in _CACHE:
        return _CACHE[key]
    if provider == "fastembed":
        emb: EmbeddingProvider = FastembedProvider(model, threads=threads)
    else:
        raise ValueError(f"Unknown embedding provider: {provider!r}")
    _CACHE[key] = emb
    return emb

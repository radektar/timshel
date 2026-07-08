"""Shared Anthropic client construction.

The lazy-import-then-construct dance was copy-pasted verbatim in five places
(summarizer, tagger, connections.synthesis, connections.verdict,
connections.recall.synthesis). Centralised here so the import guard and the
construction live in one spot; the error-classification half
(``APIBillingError`` / ``_is_permanent_api_error``) already lives in
``src.summarizer`` and is imported by the same call sites.
"""

from __future__ import annotations

from typing import Any


def build_anthropic_client(api_key: str) -> Any:
    """Construct an Anthropic SDK client, importing the package lazily.

    Kept lazy so importing a module that *might* call the API does not pull in
    the ``anthropic`` package (and its deps) unless a client is actually built.

    Raises:
        ImportError: the ``anthropic`` package is not installed.
    """
    try:
        from anthropic import Anthropic as AnthropicClient
    except ImportError as exc:  # pragma: no cover - install-time condition
        raise ImportError(
            "anthropic package not installed. Install with: pip install anthropic"
        ) from exc
    return AnthropicClient(api_key=api_key)

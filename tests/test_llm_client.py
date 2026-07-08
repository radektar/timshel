"""Tests for the shared Anthropic client builder."""

import sys
from unittest.mock import patch

import pytest

from src.llm.client import build_anthropic_client


def test_build_anthropic_client_constructs_with_key(monkeypatch):
    """The helper constructs the SDK client with the given key."""
    captured = {}

    class FakeClient:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key

    fake_anthropic = type(sys)("anthropic")
    fake_anthropic.Anthropic = FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    client = build_anthropic_client("secret-key")
    assert isinstance(client, FakeClient)
    assert captured["api_key"] == "secret-key"


def test_build_anthropic_client_raises_without_package():
    """A missing anthropic package surfaces as ImportError (not a silent None)."""
    with patch.dict(sys.modules, {"anthropic": None}):
        with pytest.raises(ImportError):
            build_anthropic_client("k")

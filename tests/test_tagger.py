"""Tests for tagger module."""

from unittest.mock import MagicMock, patch

import pytest

from src import tagger as tagger_module
from src.config import Config
from src.config.features import FeatureFlags
from src.summarizer import APIBillingError
from src.tagger import ClaudeTagger, get_tagger


def _patch_anthropic(monkeypatch, response_text: str) -> None:
    """Patch Anthropic client used by ClaudeTagger to return response_text."""

    class FakeMessages:
        def __init__(self, text: str) -> None:
            self._text = text

        def create(self, *_, **__):
            chunk = type("Chunk", (), {"text": self._text})()
            return type("Message", (), {"content": [chunk]})()

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            self.messages = FakeMessages(response_text)

    monkeypatch.setattr(tagger_module, "build_anthropic_client", lambda api_key: FakeClient(api_key))


def test_claude_tagger_parses_json(monkeypatch):
    """ClaudeTagger should parse unique tags from JSON response."""
    _patch_anthropic(monkeypatch, '["sauna", "zdrowie", "zamówienie telefoniczne"]')
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)

    tagger = ClaudeTagger(api_key="test", model="claude-test")

    tags = tagger.generate_tags(
        transcript="To jest przykładowa transkrypcja.",
        summary_markdown="## Podsumowanie\n\nTreść",
        existing_tags=["sauna"],
    )

    assert isinstance(tags, list)
    assert "sauna" in tags
    assert "zamowienie-telefoniczne" in tags
    assert len(tags) <= Config().MAX_TAGS_PER_NOTE


def test_claude_tagger_invalid_json_returns_empty(monkeypatch):
    """Invalid JSON should result in empty tag list."""
    _patch_anthropic(monkeypatch, "Brak JSON")
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)

    tagger = ClaudeTagger(api_key="test", model="claude-test")

    tags = tagger.generate_tags("Test", "Summary", [])

    assert tags == []


def test_claude_tagger_raises_api_billing_error(monkeypatch):
    """Credit balance exhaustion must surface as APIBillingError."""

    class FakeStatusError(Exception):
        status_code = 400
        message = "Your credit balance is too low"

        def __str__(self) -> str:
            return self.message

    class FakeMessages:
        def create(self, *_, **__):
            raise FakeStatusError()

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr(tagger_module, "build_anthropic_client", lambda api_key: FakeClient(api_key))
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)

    tagger = ClaudeTagger(api_key="test", model="claude-test")
    with pytest.raises(APIBillingError):
        tagger.generate_tags("Test", "Summary", [])


def test_get_tagger_disabled(monkeypatch):
    """Test that get_tagger returns None when LLM tagging is disabled."""
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", False)
    assert get_tagger() is None


def test_get_tagger_no_key_still_none(monkeypatch):
    """No API key → no tagger, regardless of tier (gating removed)."""
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)
    monkeypatch.setattr(tagger_module.config, "LLM_PROVIDER", "claude")
    monkeypatch.setattr(tagger_module.config, "LLM_API_KEY", None)
    assert get_tagger() is None


@patch("src.tagger.ClaudeTagger", return_value=MagicMock())
def test_get_tagger_builds_with_key(mock_ct, monkeypatch):
    """Tier gating removed: a Claude key alone yields a tagger."""
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)
    monkeypatch.setattr(tagger_module.config, "LLM_PROVIDER", "claude")
    monkeypatch.setattr(tagger_module.config, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(tagger_module.config, "LLM_MODEL", "claude-3-haiku-20240307")
    assert get_tagger() is not None
    mock_ct.assert_called_once_with(api_key="sk-test", model="claude-3-haiku-20240307")

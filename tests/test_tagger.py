"""Tests for tagger module."""

from unittest.mock import MagicMock, patch

import pytest

from src import tagger as tagger_module
from src.config import Config
from src.config.features import FeatureFlags
from src.summarizer import APIBillingError
from src.tagger import ClaudeTagger, get_tagger


def _patch_anthropic(monkeypatch, response_text: str) -> dict:
    """Patch Anthropic client used by ClaudeTagger to return response_text.

    Returns a dict that captures the kwargs of the last ``messages.create``
    call, so tests can assert on the request (prompt, max_tokens, timeout).
    """
    captured: dict = {}

    class FakeMessages:
        def __init__(self, text: str) -> None:
            self._text = text

        def create(self, *_, **kwargs):
            captured.update(kwargs)
            chunk = type("Chunk", (), {"text": self._text})()
            usage = type("Usage", (), {"input_tokens": 1200, "output_tokens": 40})()
            return type("Message", (), {"content": [chunk], "usage": usage})()

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            self.messages = FakeMessages(response_text)

    monkeypatch.setattr(
        tagger_module, "build_anthropic_client", lambda api_key: FakeClient(api_key)
    )
    return captured


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

    monkeypatch.setattr(
        tagger_module, "build_anthropic_client", lambda api_key: FakeClient(api_key)
    )
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
    monkeypatch.setattr(tagger_module.config, "LLM_MODEL_TAGS", None)
    assert get_tagger() is not None
    mock_ct.assert_called_once_with(api_key="sk-test", model="claude-3-haiku-20240307")


@patch("src.tagger.ClaudeTagger", return_value=MagicMock())
def test_get_tagger_honours_stage_override(mock_ct, monkeypatch):
    """``LLM_MODEL_TAGS`` must win over the global default (model router)."""
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)
    monkeypatch.setattr(tagger_module.config, "LLM_PROVIDER", "claude")
    monkeypatch.setattr(tagger_module.config, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(tagger_module.config, "LLM_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(tagger_module.config, "LLM_MODEL_TAGS", "claude-sonnet-5")
    assert get_tagger() is not None
    mock_ct.assert_called_once_with(api_key="sk-test", model="claude-sonnet-5")


class TestTaggerPrompt:
    """The prompt is the contract: tags must name entities, not activities."""

    def _prompt(self, monkeypatch, **kwargs) -> str:
        captured = _patch_anthropic(monkeypatch, '["x"]')
        monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)
        tagger = ClaudeTagger(api_key="test", model="claude-test")
        tagger.generate_tags(
            transcript=kwargs.pop("transcript", "Rozmowa o organizacji."),
            summary_markdown=kwargs.pop("summary_markdown", "## Podsumowanie\n\nTreść"),
            existing_tags=kwargs.pop("existing_tags", []),
            **kwargs,
        )
        return captured["messages"][0]["content"]

    def test_entity_priority_rules(self, monkeypatch):
        """Concrete-over-generic, with multi-word proper names allowed."""
        prompt = self._prompt(monkeypatch)

        assert "konkret bije ogólnik" in prompt
        assert "nazwy własne" in prompt
        assert "wielowyrazowe" in prompt
        assert "Tech to the Rescue" in prompt
        # The old rule that made multi-word proper names impossible is gone.
        assert "maks. 2 słowa" not in prompt

    def test_negative_examples_from_observed_failure(self, monkeypatch):
        """The deverbal-noun mush is named explicitly, not just forbidden."""
        prompt = self._prompt(monkeypatch)

        assert "planowanie strategii rozwoju" in prompt
        assert "mapowanie procesu" in prompt
        assert "konfiguracja narzędzia" in prompt

    def test_reuse_rule_explains_why(self, monkeypatch):
        """Reuse is motivated by recurrence — that is what scoring counts."""
        prompt = self._prompt(monkeypatch)

        assert "POWTARZA" in prompt
        assert "DOKŁADNIE" in prompt

    def test_known_entities_block_only_when_supplied(self, monkeypatch):
        """No glossary → no block; a fresh vault gets the baseline prompt."""
        without = self._prompt(monkeypatch)
        assert "ZNANE ENCJE" not in without

        with_block = self._prompt(
            monkeypatch, known_entities="- Tech to the Rescue\n- Impact Lab"
        )
        assert "ZNANE ENCJE" in with_block
        assert "- Impact Lab" in with_block
        assert "nie taguj z listy na siłę" in with_block

    def test_tag_language_follows_the_recording(self, monkeypatch):
        """A Polish note gets Polish tags; an English note, English ones."""
        polish = self._prompt(
            monkeypatch,
            transcript="Rozmawialiśmy o tym, że trzeba zbudować mechanizm.",
            summary_markdown="## Podsumowanie\n\nSpotkanie w sprawie platformy.",
        )
        assert "język polski" in polish

        english = self._prompt(
            monkeypatch,
            transcript="We talked about the platform and the coalition we want to build.",
            summary_markdown="## Summary\n\nA meeting about the platform.",
        )
        assert "język angielski" in english

    def test_existing_tags_reach_the_prompt(self, monkeypatch):
        """Vault tags are offered for reuse."""
        prompt = self._prompt(monkeypatch, existing_tags=["sauna", "digitakt"])
        assert "sauna, digitakt" in prompt


class TestTaggerRequestParams:
    """The API call itself: headroom, timeout and determinism."""

    def test_request_params(self, monkeypatch):
        """Enough output tokens, a real timeout, low temperature."""
        captured = _patch_anthropic(monkeypatch, '["sauna"]')
        monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)

        tagger = ClaudeTagger(api_key="test", model="claude-haiku-4-5-20251001")
        tagger.generate_tags("Transkrypcja", "## Podsumowanie", [])

        assert captured["max_tokens"] >= 256
        assert captured["timeout"] >= 30.0
        assert captured["temperature"] == 0.2

    def test_temperature_omitted_for_reasoning_models(self, monkeypatch):
        """Opus 4.x rejects ``temperature`` — it must not be sent."""
        captured = _patch_anthropic(monkeypatch, '["sauna"]')
        monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)

        tagger = ClaudeTagger(api_key="test", model="claude-opus-4-8")
        tagger.generate_tags("Transkrypcja", "## Podsumowanie", [])

        assert "temperature" not in captured


def test_last_usage_captured_for_cost_ledger(monkeypatch):
    """Per-note metering reads token counts off the tagger after each call."""
    _patch_anthropic(monkeypatch, '["projekt-x"]')
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)
    tagger = ClaudeTagger(api_key="test", model="claude-haiku-4-5-20251001")
    assert tagger.last_usage is None
    tagger.generate_tags(
        transcript="tekst",
        summary_markdown="## Podsumowanie\n\ntekst",
        existing_tags=[],
    )
    assert tagger.last_usage is not None
    assert tagger.last_usage.input_tokens == 1200
    assert tagger.last_usage.output_tokens == 40


def test_swallowed_api_error_clears_usage(monkeypatch):
    """Same contract as the summarizer: a failed call must not leave the
    previous note's tokens behind for the cost ledger to bill."""
    _patch_anthropic(monkeypatch, '["projekt-x"]')
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)
    tagger = ClaudeTagger(api_key="test", model="claude-haiku-4-5-20251001")
    tagger.generate_tags("Pierwsza", "Podsumowanie", [])
    assert tagger.last_usage is not None

    def _boom(*_a, **_kw):
        raise ConnectionError("no route")

    tagger.client.messages.create = _boom
    assert tagger.generate_tags("Druga", "Podsumowanie", []) == []
    assert tagger.last_usage is None


def test_disabled_tagging_clears_usage(monkeypatch):
    _patch_anthropic(monkeypatch, '["x"]')
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", True)
    tagger = ClaudeTagger(api_key="test", model="claude-haiku-4-5-20251001")
    tagger.generate_tags("Pierwsza", "Podsumowanie", [])
    monkeypatch.setattr(tagger_module.config, "ENABLE_LLM_TAGGING", False)
    assert tagger.generate_tags("Druga", "Podsumowanie", []) == []
    assert tagger.last_usage is None

"""Tests for summarizer module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.summarizer import (
    APIBillingError,
    BaseSummarizer,
    ClaudeSummarizer,
    get_summarizer,
)
from src.config import config
from src.config.features import FeatureFlags


class TestBaseSummarizer:
    """Test base summarizer interface."""

    def test_base_summarizer_is_abstract(self):
        """Test that BaseSummarizer cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseSummarizer()


class TestClaudeSummarizer:
    """Test Claude summarizer implementation."""

    @pytest.fixture
    def mock_anthropic(self):
        """Mock Anthropic client."""
        with patch("src.summarizer.Anthropic") as mock:
            client_instance = MagicMock()
            mock.return_value = client_instance
            yield client_instance

    @pytest.fixture
    def summarizer(self, mock_anthropic):
        """Create ClaudeSummarizer instance with mocked client."""
        return ClaudeSummarizer(api_key="test-key", model="claude-3-haiku-20240307")

    def test_claude_summarizer_initialization(self, summarizer):
        """Test ClaudeSummarizer initializes correctly."""
        assert summarizer.model == "claude-3-haiku-20240307"
        assert summarizer.max_words == config.SUMMARY_MAX_WORDS
        assert summarizer.title_max_length == config.TITLE_MAX_LENGTH

    def test_claude_summarizer_missing_package(self):
        """Test error when anthropic package is missing."""
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError):
                ClaudeSummarizer(api_key="test-key")

    def test_generate_success(self, summarizer, mock_anthropic):
        """Test successful summary generation."""
        # Mock API response with enhanced markdown format
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = (
            "TITLE: Rozmowa o projekcie\n\n"
            "SUMMARY: ## Podsumowanie\n\n"
            "Dyskusja na temat implementacji **nowych funkcji**. "
            "Omówiono kluczowe aspekty projektu.\n\n"
            "## Kluczowe punkty\n\n"
            "⚠️ **Krytyczne:**\n"
            "- Decyzja o terminie wdrożenia\n\n"
            "⚡ **Ważne:**\n"
            "- Monitorowanie postępów\n\n"
            "📝 **Informacyjne:**\n"
            "- Kontekst projektu\n\n"
            "## Cytaty\n\n"
            "### Temat: Wdrożenie\n"
            '> "Musimy to wdrożyć do końca miesiąca"\n'
            "> — *Kontekst: Dyskusja o terminach*\n\n"
            "## Lista działań (To-do)\n\n"
            "- Przygotować dokumentację\n"
            "- Skontaktować się z zespołem"
        )
        mock_anthropic.messages.create.return_value = mock_response

        transcript = "To jest przykładowa transkrypcja nagrania."
        result = summarizer.generate(transcript)

        assert "title" in result
        assert "summary" in result
        assert result["title"] == "Rozmowa o projekcie"
        assert "## Podsumowanie" in result["summary"]
        assert "## Kluczowe punkty" in result["summary"]
        assert "## Cytaty" in result["summary"]
        assert "## Lista działań (To-do)" in result["summary"]
        assert "⚠️" in result["summary"]
        assert "⚡" in result["summary"]
        assert "📝" in result["summary"]
        assert "Dyskusja" in result["summary"]
        mock_anthropic.messages.create.assert_called_once()

    def test_generate_empty_transcript(self, summarizer):
        """Test handling of empty transcript."""
        result = summarizer.generate("")

        assert "title" in result
        assert "summary" in result
        assert result["title"] == "Nagranie"
        # Fallback summary should include markdown structure with all sections
        assert "## Podsumowanie" in result["summary"]
        assert "## Kluczowe punkty" in result["summary"]
        assert "## Cytaty" in result["summary"]
        assert "## Lista działań (To-do)" in result["summary"]
        assert "⚠️" in result["summary"]
        assert "⚡" in result["summary"]
        assert "📝" in result["summary"]

    def test_generate_long_transcript_truncation(self, summarizer, mock_anthropic):
        """Test that long transcripts are truncated."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = (
            "TITLE: Test\n\n"
            "SUMMARY: ## Podsumowanie\n\nTest summary\n\n"
            "## Lista działań (To-do)\n\n- Task 1"
        )
        mock_anthropic.messages.create.return_value = mock_response

        # Create very long transcript
        long_transcript = "A" * 20000
        result = summarizer.generate(long_transcript)

        # Should still succeed
        assert "title" in result
        assert "## Podsumowanie" in result["summary"]
        # Verify truncation happened (check call args)
        call_args = mock_anthropic.messages.create.call_args
        prompt_text = call_args[1]["messages"][0]["content"]
        assert len(prompt_text) < len(long_transcript)

    def test_generate_api_error_fallback(self, summarizer, mock_anthropic):
        """Test fallback when API call fails."""
        mock_anthropic.messages.create.side_effect = Exception("API Error")

        transcript = "Test transcript"
        result = summarizer.generate(transcript)

        # Should return fallback summary with markdown structure including all sections
        assert "title" in result
        assert "summary" in result
        assert result["title"] == "Test transcript"
        assert "## Podsumowanie" in result["summary"]
        assert "## Kluczowe punkty" in result["summary"]
        assert "## Cytaty" in result["summary"]
        assert "## Lista działań (To-do)" in result["summary"]
        assert "⚠️" in result["summary"]
        assert "⚡" in result["summary"]
        assert "📝" in result["summary"]

    def test_generate_raises_api_billing_error_on_credit_balance(
        self, summarizer, mock_anthropic
    ):
        """Credit balance exhaustion must surface as APIBillingError."""

        class FakeStatusError(Exception):
            status_code = 400
            message = "Your credit balance is too low to access the API"

            def __str__(self) -> str:
                return self.message

        mock_anthropic.messages.create.side_effect = FakeStatusError()

        with pytest.raises(APIBillingError):
            summarizer.generate("Test transcript")

    def test_generate_raises_api_billing_error_on_invalid_key(
        self, summarizer, mock_anthropic
    ):
        """A rejected API key (HTTP 401) must surface as a permanent error, not
        be silently dropped — otherwise summaries/tags vanish with no signal."""

        class FakeAuthError(Exception):
            status_code = 401
            message = "invalid x-api-key"

            def __str__(self) -> str:
                return (
                    "Error code: 401 - {'type': 'error', 'error': "
                    "{'type': 'authentication_error', "
                    "'message': 'invalid x-api-key'}}"
                )

        mock_anthropic.messages.create.side_effect = FakeAuthError()

        with pytest.raises(APIBillingError):
            summarizer.generate("Test transcript")

    def test_generate_falls_back_on_other_api_errors(self, summarizer, mock_anthropic):
        """Non-billing API errors must still return a fallback summary."""

        class FakeStatusError(Exception):
            status_code = 500
            message = "internal server error"

            def __str__(self) -> str:
                return self.message

        mock_anthropic.messages.create.side_effect = FakeStatusError()

        result = summarizer.generate("Test transcript")
        assert "title" in result
        assert "## Podsumowanie" in result["summary"]

    def test_title_length_limit(self, summarizer, mock_anthropic):
        """Test that title is truncated to max length."""
        long_title = "A" * 200
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = (
            f"TITLE: {long_title}\n\n"
            "SUMMARY: ## Podsumowanie\n\nTest\n\n"
            "## Lista działań (To-do)\n\n- Task 1"
        )
        mock_anthropic.messages.create.return_value = mock_response

        result = summarizer.generate("Test")

        assert len(result["title"]) <= config.TITLE_MAX_LENGTH

    def test_parse_response_standard_format(self, summarizer):
        """Test parsing of standard response format with markdown."""
        response = (
            "TITLE: Test Title\n\n"
            "SUMMARY: ## Podsumowanie\n\n"
            "Test summary text here.\n\n"
            "## Kluczowe punkty\n\n"
            "⚠️ **Krytyczne:**\n"
            "- Test point\n\n"
            "## Cytaty\n\n"
            "### Temat: Test\n"
            '> "Test quote"\n\n'
            "## Lista działań (To-do)\n\n"
            "- Przygotować dokumentację\n"
            "- Skontaktować się z zespołem"
        )
        title, summary = summarizer._parse_response(response)

        assert title == "Test Title"
        assert "## Podsumowanie" in summary
        assert "## Kluczowe punkty" in summary
        assert "## Cytaty" in summary
        assert "## Lista działań (To-do)" in summary
        assert "Test summary" in summary

    def test_parse_response_fallback(self, summarizer):
        """Test parsing fallback for non-standard format."""
        response = "Some text\n\nMore text here"
        title, summary = summarizer._parse_response(response)

        assert title
        assert summary
        # Fallback should include markdown structure
        assert "## Podsumowanie" in summary

    def test_summary_markdown_structure(self, summarizer, mock_anthropic):
        """Test that summary contains proper markdown structure with all sections."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = (
            "TITLE: Spotkanie projektowe\n\n"
            "SUMMARY: ## Podsumowanie\n\n"
            "Podczas spotkania omówiono **kluczowe aspekty** projektu. "
            "Zidentyfikowano główne wyzwania i możliwości rozwoju. "
            "Ustalone zostały priorytety na najbliższe tygodnie.\n\n"
            "## Kluczowe punkty\n\n"
            "⚠️ **Krytyczne:**\n"
            "- Ustalenie terminów wdrożenia\n\n"
            "⚡ **Ważne:**\n"
            "- Monitorowanie postępów\n\n"
            "📝 **Informacyjne:**\n"
            "- Kontekst projektu\n\n"
            "## Cytaty\n\n"
            "### Temat: Priorytety\n"
            '> "Musimy ustalić priorytety na najbliższe tygodnie"\n'
            "> — *Kontekst: Dyskusja o planowaniu*\n\n"
            "## Lista działań (To-do)\n\n"
            "- Przygotować szczegółową dokumentację techniczną\n"
            "- Skontaktować się z zespołem deweloperskim\n"
            "- Zaplanować kolejne spotkanie"
        )
        mock_anthropic.messages.create.return_value = mock_response

        result = summarizer.generate("Test transcript")

        # Verify structure with all new sections
        assert "## Podsumowanie" in result["summary"]
        assert "## Kluczowe punkty" in result["summary"]
        assert "## Cytaty" in result["summary"]
        assert "## Lista działań (To-do)" in result["summary"]
        # Verify emoji are present
        assert "⚠️" in result["summary"]
        assert "⚡" in result["summary"]
        assert "📝" in result["summary"]
        # Verify summary content
        assert "omówiono" in result["summary"] or "Podczas" in result["summary"]
        # Verify to-do list items
        assert (
            "- Przygotować" in result["summary"] or "Przygotować" in result["summary"]
        )
        assert (
            "- Skontaktować" in result["summary"] or "Skontaktować" in result["summary"]
        )


class TestGetSummarizer:
    """Test summarizer factory function."""

    def test_get_summarizer_disabled(self, monkeypatch):
        """Test that None is returned when summarization is disabled."""
        monkeypatch.setattr(config, "ENABLE_SUMMARIZATION", False)
        result = get_summarizer()
        assert result is None

    @patch("src.summarizer.ClaudeSummarizer")
    def test_get_summarizer_no_longer_tier_gated(self, mock_claude, monkeypatch):
        """Tier gating removed: a Claude key alone yields a summarizer."""
        monkeypatch.setattr(config, "ENABLE_SUMMARIZATION", True)
        monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
        monkeypatch.setattr(config, "LLM_API_KEY", "sk-test")
        monkeypatch.setattr(config, "LLM_MODEL", "claude-3-haiku-20240307")
        mock_instance = MagicMock()
        mock_claude.return_value = mock_instance
        result = get_summarizer()
        assert result is mock_instance
        mock_claude.assert_called_once_with(
            api_key="sk-test", model="claude-3-haiku-20240307"
        )

    def test_get_summarizer_claude_no_key(self, monkeypatch):
        """Test that None is returned when Claude key is missing."""
        monkeypatch.setattr(config, "ENABLE_SUMMARIZATION", True)
        monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
        monkeypatch.setattr(config, "LLM_API_KEY", None)

        result = get_summarizer()
        assert result is None

    @patch("src.summarizer.ClaudeSummarizer")
    def test_get_summarizer_claude_success(self, mock_claude, monkeypatch):
        """Test successful Claude summarizer creation."""
        monkeypatch.setattr(config, "ENABLE_SUMMARIZATION", True)
        monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
        monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
        monkeypatch.setattr(config, "LLM_MODEL", "claude-3-haiku-20240307")

        mock_instance = MagicMock()
        mock_claude.return_value = mock_instance

        result = get_summarizer()

        assert result is not None
        mock_claude.assert_called_once_with(
            api_key="test-key", model="claude-3-haiku-20240307"
        )

    def test_get_summarizer_unknown_provider(self, monkeypatch):
        """Test handling of unknown provider."""
        monkeypatch.setattr(config, "ENABLE_SUMMARIZATION", True)
        monkeypatch.setattr(config, "LLM_PROVIDER", "unknown")

        result = get_summarizer()
        assert result is None


class TestPromptLanguageDirective:
    """The detected language is turned into an explicit, named output directive."""

    @pytest.fixture
    def summarizer(self):
        with patch("src.summarizer.Anthropic"):
            return ClaudeSummarizer(api_key="test-key", model="m")

    def test_prompt_embeds_english_directive(self, summarizer):
        """An English transcript injects an explicit ENGLISH output directive."""
        prompt = summarizer._build_prompt("We will ship the API on Wednesday.")
        assert "WRITE THE ENTIRE RESPONSE IN ENGLISH" in prompt
        assert "PO POLSKU" not in prompt

    def test_prompt_embeds_polish_directive(self, summarizer):
        """A Polish transcript injects an explicit POLISH output directive."""
        prompt = summarizer._build_prompt("Musimy wysłać wycenę w przyszłym tygodniu.")
        assert "NAPISZ CAŁĄ ODPOWIEDŹ PO POLSKU" in prompt
        assert "IN ENGLISH" not in prompt

    def test_prompt_omits_directive_when_language_unclear(self, summarizer):
        """No hard directive when the language can't be decided — generic rule wins."""
        prompt = summarizer._build_prompt("12345 — 67890 !!!")
        assert "WRITE THE ENTIRE RESPONSE IN ENGLISH" not in prompt
        assert "NAPISZ CAŁĄ ODPOWIEDŹ PO POLSKU" not in prompt
        # The generic in-prompt language rule is always present as a fallback.
        assert "OUTPUT LANGUAGE" in prompt


class TestPromptConnectionSections:
    """Stances / Open threads: the connection-engine sections and their guards.

    These sections feed the insight pipeline (entity channel via [[wikilinks]],
    contradiction detection via ✅/❌/🔄 markers), so the prompt must both ask
    for them AND fence them with anti-hallucination rules. The guards are the
    contract — an invented stance poisons ground truth downstream.
    """

    @pytest.fixture
    def prompt(self):
        with patch("src.summarizer.Anthropic"):
            summarizer = ClaudeSummarizer(api_key="test-key", model="m")
        return summarizer._build_prompt("Fundacja Ziemi to świetny pomysł.")

    def test_prompt_defines_both_sections(self, prompt):
        assert "## Stances" in prompt
        assert "## Open threads" in prompt
        # Deterministic Polish headings, so a downstream parser can match them.
        assert '"## Stanowiska"' in prompt
        assert '"## Wątki otwarte"' in prompt

    def test_stances_are_fenced_against_invention(self, prompt):
        """The defensive rules: omit-when-none, no-doubt, no relayed opinions."""
        assert "ZERO stances" in prompt
        assert "When in doubt, leave it out" in prompt
        assert "An invented stance is far\n     worse than a missing one" in prompt
        # Explicit negative catalogue: neutral facts / relayed opinions / hedges.
        assert "NOT stances" in prompt

    def test_stances_use_machine_readable_markers(self, prompt):
        for marker in ("✅", "❌", "🔄"):
            assert marker in prompt
        # Entities as wikilinks in base (dictionary) form — feeds entity_keys().
        assert "[[double brackets]]" in prompt
        assert "BASE dictionary form" in prompt

    def test_open_threads_must_be_voiced_not_derived(self, prompt):
        assert "EXPLICITLY voices" in prompt
        assert "Do NOT derive" in prompt

    def test_vocabulary_preservation_rule_present(self, prompt):
        """Distinctive terms stay verbatim — BM25/bridge channels depend on it."""
        assert "VOCABULARY" in prompt
        assert "VERBATIM" in prompt


class TestPromptKnownTerms:
    """The KNOWN TERMS block: personal glossary + its no-invention guards."""

    @pytest.fixture
    def summarizer(self):
        with patch("src.summarizer.Anthropic"):
            return ClaudeSummarizer(api_key="test-key", model="m")

    def test_block_absent_without_glossary(self, summarizer):
        """A fresh vault gets the baseline prompt — no dangling KNOWN TERMS."""
        prompt = summarizer._build_prompt("Zwykła notatka o planach.")
        assert "KNOWN TERMS" not in prompt

    def test_block_present_with_glossary_and_guards(self, summarizer):
        block = "- Tech to the Rescue (aliases: TTTR, TekTutoreski)"
        prompt = summarizer._build_prompt("Notatka o TTTR.", known_terms_block=block)
        assert "KNOWN TERMS" in prompt
        assert "- Tech to the Rescue (aliases: TTTR, TekTutoreski)" in prompt
        # The defensive contract, verbatim anchors:
        assert "Canonicalise ONLY on a clear match" in prompt
        assert "NEVER mention a known term the recording does not refer to" in prompt
        assert "NEVER expand an abbreviation" in prompt
        # Quotes stay evidence — mangled forms survive there.
        assert 'The "Quotes" section stays verbatim' in prompt

    def test_generate_threads_block_into_prompt(self, summarizer):
        """generate(known_terms_block=...) must reach _build_prompt."""
        captured = {}

        def fake_build(transcript, block=""):
            captured["block"] = block
            return "PROMPT"

        summarizer._build_prompt = fake_build
        summarizer.client.messages.create.side_effect = Exception("stop here")
        summarizer.generate("Notatka.", known_terms_block="- Haetta")
        assert captured["block"] == "- Haetta"


class TestDetectLanguage:
    """Pure, API-free output-language detection (drives the prompt directive)."""

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Anna will finish the database changes by Wednesday.", "en"),
            ("The rollout plan goes to the team by end of day.", "en"),
            ("Ustaliliśmy, że prototyp ma być gotowy do końca miesiąca.", "pl"),
            # Polish without diacritics still resolves via stopwords (się/że/nie).
            ("Musimy sie spotkac, zeby ustalic budzet, bo nie wiemy.", "pl"),
            ("", None),
            ("   ", None),
            ("99 + 1 = 100 !!!", None),
        ],
    )
    def test_detect_language(self, text, expected):
        from src.summarizer import detect_language

        assert detect_language(text) == expected

    def test_diacritics_dominate(self):
        """A single Polish diacritic is a decisive Polish signal."""
        from src.summarizer import detect_language

        assert detect_language("Spotkanie zakończyło się sukcesem") == "pl"

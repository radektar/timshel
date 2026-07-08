"""Alias judge in the production summary path (transcriber).

The judge/retry loop was previously only in scripts/resummarize_vault.py; these
pin its behaviour now that it runs on every live transcription.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.transcriber import Transcriber
from src.vocabulary import find_alias_misses, strip_quotes_section


# --------------------------------------------------------------------------- #
# Pure helpers.
# --------------------------------------------------------------------------- #


def test_strip_quotes_section_removes_only_the_quotes_block():
    md = (
        "## Podsumowanie\nTTTR robi swoje.\n\n"
        "## Cytaty\n„TTTR to skrót”\n\n"
        "## Stanowiska\nTTTR znów.\n"
    )
    stripped = strip_quotes_section(md)
    assert "„TTTR to skrót”" not in stripped  # quote body gone
    assert "## Podsumowanie" in stripped
    assert "## Stanowiska" in stripped  # section after quotes preserved


def test_strip_quotes_section_noop_without_quotes():
    md = "## Podsumowanie\nbody\n"
    assert strip_quotes_section(md) == md


def test_find_alias_misses_delegates_to_vocab_without_quotes():
    vocab = MagicMock()
    vocab.find_alias_hits.return_value = [("TTTR", "Tech to the Rescue")]
    md = "## Podsumowanie\nTTTR\n\n## Cytaty\n„TTTR verbatim”\n"

    misses = find_alias_misses(md, vocab)

    assert misses == [("TTTR", "Tech to the Rescue")]
    # The judge must be handed the summary WITHOUT the quotes block.
    passed = vocab.find_alias_hits.call_args[0][0]
    assert "verbatim" not in passed


# --------------------------------------------------------------------------- #
# Transcriber._canonicalize_aliases — judge + one corrective retry.
# --------------------------------------------------------------------------- #


def _transcriber_with(summarizer, vocab):
    t = Transcriber.__new__(Transcriber)
    t.summarizer = summarizer
    t.vocabulary = vocab
    t._disable_ai = MagicMock()
    return t


def test_no_miss_means_no_retry_call():
    vocab = MagicMock()
    vocab.find_alias_hits.return_value = []  # clean
    summarizer = MagicMock()
    t = _transcriber_with(summarizer, vocab)

    original = {"title": "T", "summary": "clean body"}
    out = t._canonicalize_aliases(original, "transcript", "known")

    assert out is original
    summarizer.generate.assert_not_called()  # no extra Haiku call when clean


def test_miss_then_clean_uses_corrected_summary():
    # First judge finds a miss; after the retry the corrected summary is clean.
    vocab = MagicMock()
    vocab.find_alias_hits.side_effect = [
        [("TTTR", "Tech to the Rescue")],  # judge on original
        [],  # judge on retry -> clean
    ]
    summarizer = MagicMock()
    summarizer.generate.return_value = {"title": "T", "summary": "Tech to the Rescue body"}
    t = _transcriber_with(summarizer, vocab)

    out = t._canonicalize_aliases(
        {"title": "T", "summary": "TTTR body"}, "transcript", "known"
    )

    assert out["summary"] == "Tech to the Rescue body"
    summarizer.generate.assert_called_once()
    # The correction string names the specific miss.
    assert "TTTR" in summarizer.generate.call_args.kwargs["correction"]


def test_surviving_miss_keeps_retry_and_logs(caplog):
    vocab = MagicMock()
    vocab.find_alias_hits.side_effect = [
        [("TTTR", "Tech to the Rescue")],  # original
        [("TTTR", "Tech to the Rescue")],  # still missed after retry
    ]
    summarizer = MagicMock()
    summarizer.generate.return_value = {"title": "T", "summary": "still TTTR body"}
    t = _transcriber_with(summarizer, vocab)

    import logging

    with caplog.at_level(logging.WARNING):
        out = t._canonicalize_aliases(
            {"title": "T", "summary": "TTTR body"}, "transcript", "known"
        )

    assert out["summary"] == "still TTTR body"  # retry kept, never patched
    assert any("alias-miss survived retry" in r.message for r in caplog.records)


def test_fallback_retry_is_rejected():
    vocab = MagicMock()
    vocab.find_alias_hits.side_effect = [[("TTTR", "Tech to the Rescue")], []]
    summarizer = MagicMock()
    # The retry degraded to a fallback template — must NOT overwrite the first.
    summarizer.generate.return_value = {
        "title": "Nagranie",
        "summary": "## Cytaty\n*Brak cytatów - wymagana ręczna analiza transkrypcji*",
    }
    t = _transcriber_with(summarizer, vocab)

    original = {"title": "T", "summary": "TTTR body"}
    out = t._canonicalize_aliases(original, "transcript", "known")

    assert out is original  # original kept despite the miss


def test_billing_error_on_retry_keeps_first_summary():
    from src.summarizer import APIBillingError

    vocab = MagicMock()
    vocab.find_alias_hits.return_value = [("TTTR", "Tech to the Rescue")]
    summarizer = MagicMock()
    summarizer.generate.side_effect = APIBillingError("quota")
    t = _transcriber_with(summarizer, vocab)

    original = {"title": "T", "summary": "TTTR body"}
    out = t._canonicalize_aliases(original, "transcript", "known")

    assert out is original
    t._disable_ai.assert_called_once()

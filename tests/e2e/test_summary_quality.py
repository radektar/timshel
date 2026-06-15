"""L3 scenario tests: real Claude summaries (BYOK) and their quality.

Unlike L2, these call the *real* Claude API, so they need an
``ANTHROPIC_API_KEY`` (read from the environment, or loaded from the repo
``.env`` the same way the app does). Every key-dependent test skips cleanly when
no key is present — this layer is for nightly / pre-release, not every commit.

Two quality lenses (see ``Docs/TESTING-E2E-STRATEGY.md`` decision B):
- **B1 — structural:** the summary has the contracted shape (non-empty title
  within the length cap, a non-trivial Markdown body).
- **B2 — LLM-as-judge:** a second Claude call scores how well the summary
  reflects the transcript; we assert a threshold, never an exact string (the
  model is non-deterministic, so golden-file comparison is meaningless).

One test here needs no key: the alpha.18 regression — literal ``{}`` in
AI-generated content must not break Markdown templating.

Marked ``e2e`` + ``slow``. Run with ``make test-e2e`` (needs the key).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

#: Cheap, current model — keeps the API spend of a full L3 run to fractions of
#: a cent while still exercising the real contract.
JUDGE_MODEL = "claude-haiku-4-5-20251001"

_EN_TRANSCRIPT = (
    "Okay so for tomorrow's standup, the main thing is the payment service "
    "migration. Anna will finish the database changes by Wednesday, and then "
    "Marek takes over the API layer. We also need to decide whether to keep "
    "the old endpoints alive for backwards compatibility. Let's book thirty "
    "minutes on Thursday to settle that. Action item: I will send the rollout "
    "plan to the team by end of day."
)
_PL_TRANSCRIPT = (
    "Dzień dobry, nagrywam notatkę po spotkaniu z klientem. Ustaliliśmy, że "
    "prototyp modułu ma być gotowy do końca miesiąca. Trzeba zamówić materiały "
    "na ścianę i sprawdzić koszt izolacji. Zadanie dla mnie: przygotować "
    "wycenę i wysłać ją w przyszłym tygodniu."
)


def _get_api_key() -> Optional[str]:
    """Resolve the Anthropic key from the environment or the repo ``.env``."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        from src.env_loader import load_env_file

        load_env_file()
    except Exception:
        return None
    return os.environ.get("ANTHROPIC_API_KEY")


requires_claude = pytest.mark.skipif(
    _get_api_key() is None,
    reason="requires ANTHROPIC_API_KEY (env or repo .env) for real Claude calls",
)

try:
    import anthropic as _anthropic

    _API_STATUS_ERRORS = (_anthropic.APIStatusError,)
except Exception:  # pragma: no cover - anthropic always present in dev
    _API_STATUS_ERRORS = ()

#: Substrings that mean "the account/key can't serve requests right now" — an
#: environment limitation, not a defect in the code under test. We skip on
#: these (a dev box with no credits must not turn L3 red), but let genuine bad
#: requests / server errors fail loudly.
_UNAVAILABLE_MARKERS = (
    "credit balance",
    "billing",
    "authentication",
    "permission",
    "quota",
    "rate limit",
)


def _run_or_skip(fn):
    """Run *fn*; turn billing/auth/quota API errors into a clean skip."""
    from src.summarizer import APIBillingError

    try:
        return fn()
    except APIBillingError as exc:
        pytest.skip(f"Anthropic API unavailable (billing): {exc}")
    except _API_STATUS_ERRORS as exc:
        if any(marker in str(exc).lower() for marker in _UNAVAILABLE_MARKERS):
            pytest.skip(f"Anthropic API unavailable: {exc}")
        raise


# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def summarizer():
    """A real ClaudeSummarizer wired to the BYOK key."""
    from src.summarizer import ClaudeSummarizer

    return ClaudeSummarizer(api_key=_get_api_key(), model=JUDGE_MODEL)


@pytest.fixture(scope="module")
def judge_client():
    """A raw Anthropic client used as an independent quality judge."""
    from anthropic import Anthropic

    return Anthropic(api_key=_get_api_key())


def _judge_score(client, question: str) -> int:
    """Ask Claude to answer *question* with a single 1–5 digit; return it.

    Defaults to 0 (a failing score) if the model returns no parseable digit, so
    a malformed judge response fails loudly rather than passing by accident.
    """
    msg = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=8,
        messages=[{"role": "user", "content": question}],
    )
    text = msg.content[0].text if msg.content else ""
    match = re.search(r"[1-5]", text)
    return int(match.group()) if match else 0


# --------------------------------------------------------------------------- #
# B1 — structural.
# --------------------------------------------------------------------------- #


@requires_claude
def test_real_summary_has_expected_structure(summarizer):
    """A real Claude summary has a non-empty title (capped) and a body."""
    result = _run_or_skip(lambda: summarizer.generate(_EN_TRANSCRIPT))

    title = result.get("title", "")
    summary = result.get("summary", "")

    assert title.strip(), "title was empty"
    assert len(title) <= 60, f"title exceeds the 60-char cap: {title!r}"
    assert len(summary.strip()) >= 30, f"summary suspiciously short: {summary!r}"
    # The prompt asks for a Markdown-sectioned body; a heading is the cheap,
    # stable signal that the contract was honoured.
    assert "#" in summary, f"summary has no Markdown structure: {summary!r}"


# --------------------------------------------------------------------------- #
# B2 — LLM-as-judge.
# --------------------------------------------------------------------------- #


@requires_claude
def test_summary_is_judged_relevant(summarizer, judge_client):
    """An independent Claude judge rates the summary's faithfulness >= 4/5."""
    result = _run_or_skip(lambda: summarizer.generate(_EN_TRANSCRIPT))
    question = (
        "You are grading a meeting-note summary against its transcript.\n"
        "Rate from 1 (unrelated/wrong) to 5 (accurate and faithful) how well "
        "the SUMMARY captures the key points of the TRANSCRIPT. "
        "Reply with a single digit 1-5 only.\n\n"
        f"TRANSCRIPT:\n{_EN_TRANSCRIPT}\n\n"
        f"SUMMARY:\n{result.get('summary', '')}"
    )
    score = _run_or_skip(lambda: _judge_score(judge_client, question))
    assert score >= 4, f"judge scored summary {score}/5 (expected >= 4)"


@requires_claude
def test_polish_transcript_yields_polish_summary(summarizer, judge_client):
    """A Polish transcript must produce a Polish summary (language fidelity)."""
    result = _run_or_skip(lambda: summarizer.generate(_PL_TRANSCRIPT))
    question = (
        "Is the following text written primarily in Polish? "
        "Reply 5 for definitely Polish, 1 for definitely not Polish, "
        "a single digit only.\n\n"
        f"{result.get('summary', '')}"
    )
    score = _run_or_skip(lambda: _judge_score(judge_client, question))
    assert score >= 4, f"summary not judged Polish (score {score}/5)"


# --------------------------------------------------------------------------- #
# alpha.18 regression — no API key required.
# --------------------------------------------------------------------------- #


def test_braces_in_ai_content_do_not_break_markdown(tmp_path):
    """Literal ``{}`` in AI title/summary/transcript must not crash templating.

    alpha.18: an AI-generated title containing ``{}`` raised KeyError/ValueError
    inside ``str.format()``. The generator now escapes braces; this guards that
    fix end-to-end without spending an API call.
    """
    from src.markdown_generator import MarkdownGenerator

    generator = MarkdownGenerator()
    summary = {
        "title": "Plan {projekt} i {action}",
        "summary": "## Podsumowanie\n\nOmówiono {budżet} oraz {harmonogram}.",
    }
    metadata = {
        "recording_datetime": datetime(2026, 6, 15, 10, 0, 0),
        "source_file": "rec_{weird}.m4a",
        "duration_formatted": "00:01:23",
    }

    out = generator.create_markdown_document(
        transcript="Mówię o {czymś} w nawiasach {klamrowych}.",
        summary=summary,
        metadata=metadata,
        output_dir=tmp_path,
        tags=["transcription"],
        extra_frontmatter={"language": "pl", "model": "small"},
    )

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # The literal braces must survive into the rendered note, not be consumed
    # or doubled by the templating layer.
    assert "{projekt}" in text
    assert "{czymś}" in text
    assert "{budżet}" in text

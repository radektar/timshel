"""L3 scenario tests: real Claude tags (BYOK) and their quality.

Tags are one of only three per-note signals the digest gets (tags, the
Stanowiska section, the summary text), and connection scoring only counts a tag
that RECURS across notes. So a tag naming a concrete entity is worth something
downstream and a generic process noun is worth nothing — which is exactly what
this layer checks, and what unit tests on the prompt cannot.

Same two lenses as ``test_summary_quality.py``: B1 structural (shape, count,
sanitised form), B2 LLM-as-judge (a second Claude call scores concreteness).

Marked ``e2e`` + ``slow``. Run with ``make test-e2e`` (needs the key).
"""

from __future__ import annotations

import os
import re
from typing import Optional

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

JUDGE_MODEL = "claude-haiku-4-5-20251001"

#: Shaped after the real recording that exposed the problem: a named
#: organisation discussed throughout, plus plenty of process talk that the old
#: prompt turned into "planowanie-strategii-rozwoju" style mush.
_PL_TRANSCRIPT = (
    "Nie ma sensu myśleć o tym tylko jako Tech to the Rescue, tylko koalicja "
    "organizacji, które mają swoje programy wsparcia. To rozwiązanie powinno "
    "zbierać wszystkie programy, które dzieją się w ramach takiej koalicji, i "
    "mieć po drugiej stronie assessment tych programów. Na przykład do jakiego "
    "poziomu dopasowany jest Impact Lab, a do jakiego scaling program. "
    "Assessment to będzie połowa wartości, druga połowa, być może ważniejsza, "
    "to są rekomendacje. Musimy spotkać się z Magdą i zastanowić się, jak "
    "oceniamy programy pod kątem rekomendacji."
)

_PL_SUMMARY = (
    "## Podsumowanie\n\n"
    "Rozmowa dotyczy koncepcji **platformy koalicji Tech to the Rescue**, "
    "która łączyłaby ocenę organizacji z rekomendacją programów wsparcia "
    "(m.in. Impact Lab).\n\n"
    "## Kluczowe punkty\n\n"
    "- ⚡ **Ważne:** rekomendacje są równie ważne co sam assessment\n"
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


@pytest.fixture(scope="module")
def tagger():
    """A real ClaudeTagger wired to the BYOK key."""
    from src.tagger import ClaudeTagger

    return ClaudeTagger(api_key=_get_api_key(), model=JUDGE_MODEL)


@pytest.fixture(scope="module")
def judge_client():
    from anthropic import Anthropic

    return Anthropic(api_key=_get_api_key())


@pytest.fixture(scope="module")
def tags(tagger):
    """Tags for the reference recording — generated once per module.

    Tagging is off in the test config; a BYOK run is exactly the case where it
    is on, and it is the feature under test here.
    """
    from src.config import config

    previous = config.ENABLE_LLM_TAGGING
    config.ENABLE_LLM_TAGGING = True
    try:
        return _run_or_skip(
            lambda: tagger.generate_tags(
                transcript=_PL_TRANSCRIPT,
                summary_markdown=_PL_SUMMARY,
                existing_tags=["organizacje-pozarzadowe", "sauna"],
                known_entities="- Tech to the Rescue\n- Impact Lab",
            )
        )
    finally:
        config.ENABLE_LLM_TAGGING = previous


def _judge_score(client, question: str) -> int:
    """Ask Claude to answer *question* with a single 1–5 digit; return it."""
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
def test_tags_have_contracted_shape(tags):
    """Non-empty, capped, and already in Obsidian-safe form."""
    from src.config import config
    from src.tag_index import TagIndex

    assert tags, "tagger returned nothing for a content-rich recording"
    assert len(tags) <= config.MAX_TAGS_PER_NOTE
    for tag in tags:
        assert tag == TagIndex.sanitize_tag_value(tag)
        assert tag == tag.lower()
        assert " " not in tag


@requires_claude
def test_multi_word_entity_survives_as_a_tag(tags):
    """The regression: 'maks. 2 słowa' made 'tech-to-the-rescue' impossible.

    The recording names one organisation throughout — that name is the single
    most connectable thing about the note, so it must reach the frontmatter.
    """
    assert any("tech" in tag for tag in tags), tags


# --------------------------------------------------------------------------- #
# B2 — LLM-as-judge.
# --------------------------------------------------------------------------- #


@requires_claude
def test_tags_name_concrete_subjects_not_generic_activities(tags, judge_client):
    """Concreteness is the property that makes a tag connect two notes."""
    question = (
        "Oto transkrypcja nagrania:\n\n"
        f"{_PL_TRANSCRIPT}\n\n"
        f"Oto wygenerowane tagi: {', '.join(tags)}\n\n"
        "Oceń w skali 1-5, czy tagi nazywają KONKRETNE podmioty i tematy tego "
        "nagrania (nazwy organizacji, projektów, konkretne zagadnienia), a nie "
        "ogólne czynności pasujące do dowolnego nagrania (typu 'planowanie "
        "strategii', 'mapowanie procesu', 'omówienie tematu'). "
        "5 = same konkrety, 1 = sama ogólna papka proceduralna. "
        "Odpowiedz WYŁĄCZNIE jedną cyfrą."
    )
    score = _run_or_skip(lambda: _judge_score(judge_client, question))
    assert score >= 4, f"tags too generic (score {score}): {tags}"


@requires_claude
def test_tags_are_grounded_in_the_recording(tags, judge_client):
    """No invented topics — the old prompt produced 'konfiguracja narzędzia'
    for a recording that never mentioned tooling."""
    question = (
        "Oto transkrypcja nagrania:\n\n"
        f"{_PL_TRANSCRIPT}\n\n"
        f"Oto wygenerowane tagi: {', '.join(tags)}\n\n"
        "Oceń w skali 1-5, czy KAŻDY tag da się uzasadnić treścią tej "
        "transkrypcji (nic nie jest zmyślone). "
        "5 = wszystkie tagi ugruntowane, 1 = większość zmyślona. "
        "Odpowiedz WYŁĄCZNIE jedną cyfrą."
    )
    score = _run_or_skip(lambda: _judge_score(judge_client, question))
    assert score >= 4, f"tags not grounded (score {score}): {tags}"

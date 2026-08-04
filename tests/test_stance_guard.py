"""Tests for the deterministic stance-subject guard (src/stance_guard.py)."""

from __future__ import annotations

import json

import pytest

from src.config import config
from src.connections.stance import parse_stances
from src.stance_guard import (
    debracket_stance_subjects,
    find_junk_stance_subjects,
    guard_stance_subjects,
)
from src.vocabulary import VocabularyIndex


def _summary(stance_lines: str, extra: str = "") -> str:
    return (
        "## Podsumowanie\n\n"
        "Rozmowa o platformie i o [[Automatyzacja rekomendacji]] poza sekcją.\n\n"
        "## Stanowiska\n\n"
        f"{stance_lines}\n\n"
        "## Cytaty\n\n"
        '> "cytat o [[Assessment]]"\n'
        f"{extra}"
    )


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    monkeypatch.setattr(config, "VOCABULARY_ENABLED", True)
    return tmp_path


class TestJunkDetection:
    """What counts as an entity, and what is process language."""

    @pytest.mark.parametrize(
        "subject",
        [
            "Assessment",  # EN deverbal, the observed failure
            "Automatyzacja rekomendacji",  # PL phrase, second word lowercase
            "proces doboru mentorów",  # all lowercase
            "Onboarding",  # EN gerund
            "pomysł",  # generic single noun
            "Projekt",  # generic, capitalised
        ],
    )
    def test_flags_activities_and_concepts(self, subject):
        md = _summary(f"- [[{subject}]] ✅ dobry kierunek")
        assert find_junk_stance_subjects(md) == [subject]

    @pytest.mark.parametrize(
        "subject",
        [
            "Fundacja Ziemi",  # PL name whose head ends in -acja
            "Tech to the Rescue",  # lowercase particles inside a real name
            "Impact Lab",
            "Magda",
            "Notion",  # short -tion word: a product, not a process
            "TekTutoreski",  # mangled proper name (internal capital)
            "TTTR",  # acronym
            "Digitakt",
            "Maria de la Cruz",  # name particles are not content words
            "Ludwig van Beethoven",
        ],
    )
    def test_keeps_named_entities(self, subject):
        md = _summary(f"- [[{subject}]] ✅ dobry kierunek")
        assert find_junk_stance_subjects(md) == []

    def test_wikilink_harvested_term_is_not_an_exemption(self, vault):
        """The poison loop, closed.

        vocabulary.py harvests every [[wikilink]] as a confirmed term, so a
        junk stance subject lands in the glossary via the very note that wrote
        it. Measured on a real note: [[Assessment]] and [[Automatyzacja
        rekomendacji]] were already glossary terms. If the guard trusted that,
        it would protect exactly the junk it exists to remove.
        """
        _note = vault / "a.md"
        _note.write_text(
            "## Stanowiska\n\n- [[Assessment]] ✅ dobre\n", encoding="utf-8"
        )
        vocab = VocabularyIndex(vault)
        assert "assessment" in vocab.build()  # harvested, as in production

        md = _summary("- [[Assessment]] ✅ dobre")
        assert find_junk_stance_subjects(md, vocab) == ["Assessment"]

    def test_glossary_term_is_never_flagged(self, vault):
        """A CURATED term outranks every morphological heuristic."""
        sidecar = vault / ".timshel"
        sidecar.mkdir()
        (sidecar / "vocabulary.json").write_text(
            json.dumps({"terms": [{"canonical": "Assessment", "aliases": []}]}),
            encoding="utf-8",
        )
        md = _summary("- [[Assessment]] ✅ to działa")

        assert find_junk_stance_subjects(md, VocabularyIndex(vault)) == []
        assert find_junk_stance_subjects(md) == ["Assessment"]  # without glossary

    def test_no_stance_section_means_nothing_to_do(self):
        md = "## Podsumowanie\n\nTekst o [[Automatyzacja rekomendacji]].\n"
        assert find_junk_stance_subjects(md) == []

    def test_duplicates_reported_once(self):
        md = _summary(
            "- [[Assessment]] ✅ dobre\n- [[Assessment]] ❌ jednak nie",
        )
        assert find_junk_stance_subjects(md) == ["Assessment"]


class TestDebracket:
    """Surgical rewrite: the stance section only, brackets only."""

    def test_removes_brackets_inside_section_only(self):
        md = _summary("- [[Assessment]] ✅ dobre")
        out = debracket_stance_subjects(md, ["Assessment"])

        assert "- Assessment ✅ dobre" in out
        # The quote keeps its wikilink verbatim — quotes are evidence.
        assert '> "cytat o [[Assessment]]"' in out
        # And so does prose outside the stance section.
        assert "[[Automatyzacja rekomendacji]] poza sekcją" in out

    def test_keeps_other_subjects_bracketed(self):
        md = _summary("- [[Assessment]] ✅ dobre\n- [[Fundacja Ziemi]] ❌ nie")
        out = debracket_stance_subjects(md, ["Assessment"])

        assert "- Assessment ✅ dobre" in out
        assert "- [[Fundacja Ziemi]] ❌ nie" in out

    def test_handles_piped_wikilink(self):
        md = _summary("- [[Automatyzacja rekomendacji|automatyzacja]] ✅ tak")
        out = debracket_stance_subjects(md, ["Automatyzacja rekomendacji"])

        assert "- Automatyzacja rekomendacji ✅ tak" in out
        assert "[[" not in out.split("## Cytaty")[0].split("## Stanowiska")[1]

    def test_idempotent(self):
        md = _summary("- [[Assessment]] ✅ dobre")
        once = guard_stance_subjects(md)
        twice = guard_stance_subjects(once)

        assert once == twice

    def test_no_subjects_returns_input_unchanged(self):
        md = _summary("- [[Fundacja Ziemi]] ✅ dobre")
        assert guard_stance_subjects(md) == md


class TestStanceChannelSurvives:
    """The whole point: cleaning must not cost the contradiction channel."""

    def test_parsed_stances_identical_before_and_after(self):
        md = _summary(
            "- [[Assessment]] ✅ to połowa wartości\n"
            "- [[Fundacja Ziemi]] ❌ nie tym razem"
        )
        before = parse_stances(md)
        after = parse_stances(guard_stance_subjects(md))

        assert [s.subject for s in before] == [s.subject for s in after]
        assert [s.polarity for s in before] == [s.polarity for s in after]
        assert [s.keys for s in before] == [s.keys for s in after]

    def test_guard_logs_what_it_caught(self, caplog):
        md = _summary("- [[Assessment]] ✅ dobre")
        with caplog.at_level("WARNING"):
            guard_stance_subjects(md)

        assert "stance-subject de-bracketed" in caplog.text
        assert "Assessment" in caplog.text

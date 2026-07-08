"""Pure tests for the v2 re-summarize migration (no API calls).

The invariants that make --apply safe to run on a real vault:
frontmatter and the transcript block survive byte-for-byte, malformed or
placeholder notes are refused, and an API-fallback summary can never
overwrite a real one.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "resummarize_vault",
    Path(__file__).resolve().parents[1] / "scripts" / "resummarize_vault.py",
)
rsv = importlib.util.module_from_spec(_SPEC)
sys.modules["resummarize_vault"] = rsv
_SPEC.loader.exec_module(rsv)

# The alias judge + fallback detector moved to their canonical homes and are
# now shared with the production summary path; test them there.
from src.summarizer import is_fallback_summary  # noqa: E402
from src.vocabulary import find_alias_misses  # noqa: E402


_NOTE = (
    '---\ntitle: "Strategia TekTutoreski"\ndate: 2026-06-01\n'
    "fingerprint: sha256:abc\nversion: 1\ntags: [transcription]\n---\n\n"
    "## Podsumowanie\n\nStare podsumowanie o TekTutoreski.\n\n"
    "## Transkrypcja\n\n TekTutoreski. Po rozmowie z Gosią...\n"
)


class TestSplitRebuild:
    def test_roundtrip_is_byte_identical(self):
        fm, old_summary, transcript = rsv.split_note(_NOTE)
        assert rsv.rebuild_note(fm, old_summary, transcript) == _NOTE

    def test_frontmatter_and_transcript_preserved_verbatim(self):
        fm, _, transcript = rsv.split_note(_NOTE)
        rebuilt = rsv.rebuild_note(fm, "## Podsumowanie\n\nNowe.", transcript)
        assert rebuilt.startswith(fm)
        assert rebuilt.endswith(transcript)
        assert 'title: "Strategia TekTutoreski"' in rebuilt  # title untouched
        assert "Po rozmowie z Gosią" in rebuilt
        assert "Stare podsumowanie" not in rebuilt

    def test_note_without_transcript_section_is_refused(self):
        assert (
            rsv.split_note('---\ntitle: "x"\n---\n\n## Podsumowanie\nTekst.\n') is None
        )

    def test_note_without_frontmatter_is_refused(self):
        assert rsv.split_note("## Podsumowanie\n\n## Transkrypcja\nfoo\n") is None

    def test_english_transcript_heading_supported(self):
        note = _NOTE.replace("## Transkrypcja", "## Transcript")
        parts = rsv.split_note(note)
        assert parts is not None
        assert parts[2].startswith("## Transcript")


class TestEligibility:
    def test_placeholder_transcript_skipped(self, tmp_path):
        note = _NOTE.replace(
            " TekTutoreski. Po rozmowie z Gosią...",
            "(Brak rozpoznawalnej mowy w nagraniu)",
        )
        p = tmp_path / "a.md"
        p.write_text(note, encoding="utf-8")
        ok, reason = rsv.eligible(p)
        assert not ok and "placeholder" in reason

    def test_short_transcript_skipped(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text(
            _NOTE.replace(" TekTutoreski. Po rozmowie z Gosią...", "krótko"),
            encoding="utf-8",
        )
        ok, reason = rsv.eligible(p)
        assert not ok and "too short" in reason

    def test_real_note_eligible(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text(
            _NOTE.replace(
                "Po rozmowie z Gosią...", "Po rozmowie z Gosią o strategii. " * 5
            ),
            encoding="utf-8",
        )
        ok, _ = rsv.eligible(p)
        assert ok


class _FakeVocab:
    """Minimal vocab double: reports the one alias we care about, wherever it
    appears in the text handed to it."""

    def find_alias_hits(self, text):
        return (
            [("TekTutoreski", "Tech to the Rescue")] if "TekTutoreski" in text else []
        )


class TestFindAliasMisses:
    """The judge detects (never rewrites) aliases the model left, and treats
    the Quotes section as evidence — an alias there is not a miss."""

    def test_miss_outside_quotes_is_reported(self):
        summary = "## Podsumowanie\n\nStrategia TekTutoreski rośnie.\n"
        assert find_alias_misses(summary, _FakeVocab()) == [
            ("TekTutoreski", "Tech to the Rescue")
        ]

    def test_alias_only_in_quotes_is_not_a_miss(self):
        summary = (
            "## Podsumowanie\n\nStrategia Tech to the Rescue rośnie.\n\n"
            '## Cytaty\n\n> "TekTutoreski. Po rozmowie..."\n\n'
            "## Wątki otwarte\n\n- Czy skaluje?\n"
        )
        assert find_alias_misses(summary, _FakeVocab()) == []

    def test_miss_after_quotes_section_still_caught(self):
        summary = (
            "## Podsumowanie\n\nOK.\n\n"
            '## Cytaty\n\n> "cytat"\n\n'
            "## Wątki otwarte\n\n- Czy TekTutoreski skaluje?\n"
        )
        assert find_alias_misses(summary, _FakeVocab()) == [
            ("TekTutoreski", "Tech to the Rescue")
        ]

    def test_clean_summary_has_no_misses(self):
        summary = "## Podsumowanie\n\nStrategia Tech to the Rescue rośnie.\n"
        assert find_alias_misses(summary, _FakeVocab()) == []


class TestGuards:
    def test_fallback_summaries_detected(self):
        assert is_fallback_summary("## Podsumowanie\n\nBrak podsumowania AI. ...")
        assert is_fallback_summary("...\nNie udało się wygenerować podsumowania")
        assert not is_fallback_summary("## Podsumowanie\n\nPrawdziwa treść.")
        # A real action item that merely mentions reviewing the transcript must
        # NOT be misread as a fallback (would discard a good alias-fix retry).
        assert not is_fallback_summary("## Lista działań\n- Przejrzeć transkrypcję ręcznie")

    def test_discovery_ignores_subfolders(self, tmp_path):
        (tmp_path / "a.md").write_text("x", encoding="utf-8")
        digests = tmp_path / "Timshel Digests"
        digests.mkdir()
        (digests / "2026-07-01 Synthesis.md").write_text("x", encoding="utf-8")
        names = [p.name for p in rsv.discover_notes(tmp_path)]
        assert names == ["a.md"]

    def test_select_only_and_limit(self, tmp_path):
        paths = []
        for name in ["25-12-04 - Impact.md", "26-05-14 - TTTR.md", "26-06-01 - X.md"]:
            p = tmp_path / name
            p.write_text("x", encoding="utf-8")
            paths.append(p)
        only = rsv._select(paths, ["tttr"], None, False)
        assert [p.name for p in only] == ["26-05-14 - TTTR.md"]
        limited = rsv._select(paths, [], 2, False)
        assert len(limited) == 2
        everything = rsv._select(paths, [], 2, True)
        assert len(everything) == 3

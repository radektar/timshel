"""Tests for the personal vocabulary index (src/vocabulary.py)."""

from __future__ import annotations

import json

import pytest

from src.config import config
from src.vocabulary import VocabularyIndex


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Point TRANSCRIBE_DIR (glossary root + alias-file anchor) at tmp."""
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    monkeypatch.setattr(config, "VOCABULARY_ENABLED", True)
    monkeypatch.setattr(config, "WHISPER_GLOSSARY_ENABLED", True)
    return tmp_path


def _note(vault, name, body):
    (vault / name).write_text(body, encoding="utf-8")


class TestHarvest:
    def test_wikilink_target_confirmed_from_single_note(self, vault):
        _note(vault, "a.md", "Rozmowa o [[Tech to the Rescue|TTTR]] i planach.")
        terms = VocabularyIndex(vault).build()
        assert "tech to the rescue" in terms
        # Display form keeps the original casing, alias part is stripped.
        assert terms["tech to the rescue"].canonical == "Tech to the Rescue"

    def test_capitalised_run_needs_two_notes(self, vault):
        _note(vault, "a.md", "Spotkanie z Impact Chat wczoraj.")
        idx = VocabularyIndex(vault)
        assert "impact chat" not in idx.build()
        _note(vault, "b.md", "Impact Chat rośnie dalej.")
        assert "impact chat" in idx.build(force_refresh=True)

    def test_raw_transcript_section_is_never_harvested(self, vault):
        # "TekTutoreski" lives below ## Transkrypcja — the mangled zone.
        _note(
            vault,
            "a.md",
            "## Podsumowanie\nPlan bez nazw.\n\n## Transkrypcja\n\n"
            "Strategia TekTutoreski Wielka. Strategia TekTutoreski Wielka.",
        )
        _note(vault, "b.md", "## Transkrypcja\nStrategia TekTutoreski Wielka.")
        assert "strategia tektutoreski wielka" not in VocabularyIndex(vault).build()

    def test_alias_file_merges_and_wins(self, vault):
        malinche = vault / ".timshel"
        malinche.mkdir()
        (malinche / "vocabulary.json").write_text(
            json.dumps(
                {
                    "terms": [
                        {
                            "canonical": "Tech to the Rescue",
                            "aliases": ["TTTR", "TekTutoreski"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        terms = VocabularyIndex(vault).build()
        term = terms["tech to the rescue"]
        assert term.curated
        assert term.aliases == ["TTTR", "TekTutoreski"]

    def test_corrupt_alias_file_is_skipped_not_fatal(self, vault):
        malinche = vault / ".timshel"
        malinche.mkdir()
        (malinche / "vocabulary.json").write_text("{nope", encoding="utf-8")
        _note(vault, "a.md", "Notatka o [[Haetta]] i planach.")
        terms = VocabularyIndex(vault).build()
        assert "haetta" in terms

    def test_missing_root_yields_empty(self, vault):
        idx = VocabularyIndex(vault / "does-not-exist")
        assert idx.build() == {}


class TestViews:
    def test_curated_ranks_before_wikilinked_before_runs(self, vault):
        malinche = vault / ".timshel"
        malinche.mkdir()
        (malinche / "vocabulary.json").write_text(
            json.dumps({"terms": [{"canonical": "Zeta Project", "aliases": []}]}),
            encoding="utf-8",
        )
        _note(vault, "a.md", "O [[Alfa Team]] oraz Beta Runda w tle.")
        _note(vault, "b.md", "Znowu Beta Runda w rozmowie.")
        ranked = [t.canonical for t in VocabularyIndex(vault).ranked_terms()]
        assert ranked == ["Zeta Project", "Alfa Team", "Beta Runda"]

    def test_known_terms_block_lists_aliases(self, vault):
        malinche = vault / ".timshel"
        malinche.mkdir()
        (malinche / "vocabulary.json").write_text(
            json.dumps(
                {"terms": [{"canonical": "Tech to the Rescue", "aliases": ["TTTR"]}]}
            ),
            encoding="utf-8",
        )
        block = VocabularyIndex(vault).known_terms_block()
        assert "- Tech to the Rescue (aliases: TTTR)" in block

    def test_canonical_terms_block_omits_aliases(self, vault):
        """The tagger runs on canonicalised text — aliases are noise there."""
        malinche = vault / ".timshel"
        malinche.mkdir()
        (malinche / "vocabulary.json").write_text(
            json.dumps(
                {"terms": [{"canonical": "Tech to the Rescue", "aliases": ["TTTR"]}]}
            ),
            encoding="utf-8",
        )
        block = VocabularyIndex(vault).canonical_terms_block()
        assert "- Tech to the Rescue" in block
        assert "TTTR" not in block
        assert "aliases" not in block

    def test_canonical_terms_block_honours_master_switch(self, vault, monkeypatch):
        _note(vault, "a.md", "Notatka o [[Haetta]].")
        monkeypatch.setattr(config, "VOCABULARY_ENABLED", False)
        assert VocabularyIndex(vault).canonical_terms_block() == ""

    def test_whisper_prompt_includes_acronym_alias_and_respects_cap(
        self, vault, monkeypatch
    ):
        malinche = vault / ".timshel"
        malinche.mkdir()
        (malinche / "vocabulary.json").write_text(
            json.dumps(
                {
                    "terms": [
                        {
                            "canonical": "Tech to the Rescue",
                            # Acronym joins the glossary; a long lowercase
                            # alias (mangled form) must NOT — we don't want to
                            # bias whisper TOWARD the mangling.
                            "aliases": ["TTTR", "TekTutoreski"],
                        },
                        {"canonical": "Impact Chat", "aliases": []},
                    ]
                }
            ),
            encoding="utf-8",
        )
        prompt = VocabularyIndex(vault).whisper_prompt()
        assert "Tech to the Rescue" in prompt
        assert "TTTR" in prompt
        assert "TekTutoreski" not in prompt

        monkeypatch.setattr(config, "VOCABULARY_WHISPER_MAX_CHARS", 20)
        capped = VocabularyIndex(vault).whisper_prompt()
        assert len(capped) <= 20

    def test_master_switch_silences_both_views(self, vault, monkeypatch):
        _note(vault, "a.md", "Notatka o [[Haetta]].")
        monkeypatch.setattr(config, "VOCABULARY_ENABLED", False)
        idx = VocabularyIndex(vault)
        assert idx.known_terms_block() == ""
        assert idx.whisper_prompt() == ""

    def test_whisper_switch_independent(self, vault, monkeypatch):
        _note(vault, "a.md", "Notatka o [[Haetta]].")
        monkeypatch.setattr(config, "WHISPER_GLOSSARY_ENABLED", False)
        idx = VocabularyIndex(vault)
        assert idx.whisper_prompt() == ""
        assert "Haetta" in idx.known_terms_block()


class TestFindAliasHits:
    """Detection only — the judge half of canonicalisation (never rewrites)."""

    @pytest.fixture
    def idx(self, vault):
        malinche = vault / ".timshel"
        malinche.mkdir()
        (malinche / "vocabulary.json").write_text(
            json.dumps(
                {
                    "terms": [
                        {
                            "canonical": "Tech to the Rescue",
                            "aliases": ["TTTR", "TekTutoreski"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return VocabularyIndex(vault)

    def test_reports_alias_and_canonical(self, idx):
        hits = idx.find_alias_hits("Strategia TekTutoreski rośnie.")
        assert hits == [("TekTutoreski", "Tech to the Rescue")]

    def test_case_insensitive_but_reports_found_form(self, idx):
        hits = idx.find_alias_hits("mowa o tttr wczoraj")
        assert hits == [("tttr", "Tech to the Rescue")]

    def test_canonical_form_is_not_a_miss(self, idx):
        assert idx.find_alias_hits("Strategia Tech to the Rescue rośnie.") == []

    def test_disabled_switch_reports_nothing(self, idx, monkeypatch):
        monkeypatch.setattr(config, "VOCABULARY_ENABLED", False)
        assert idx.find_alias_hits("Strategia TekTutoreski rośnie.") == []


class TestHarvestScope:
    """What the app writes about itself is never a glossary term."""

    def test_digest_subfolder_is_not_harvested(self, vault):
        """A digest is made of [[note basename]] links.

        Harvesting it put 73 note FILENAMES into a real vault's glossary —
        which then biased whisper's decoding prompt and the summarizer's
        KNOWN TERMS block toward filenames.
        """
        _note(vault, "real.md", "Rozmowa o [[Impact Chat]] i planach.")
        digests = vault / config.DIGEST_DIR_NAME
        digests.mkdir()
        (digests / "2026-06-25 Synthesis.md").write_text(
            "---\ntype: timshel-digest\n---\n\n"
            "Łączy [[26-06-03 - Przygotowania do Eight Moons - okna]] "
            "z [[26-07-01 - Zmiana nazwy projektu]].\n",
            encoding="utf-8",
        )

        terms = VocabularyIndex(vault).build()

        assert "impact chat" in terms
        assert not [t for t in terms if t.startswith("26-")]

    def test_sidecar_backups_are_not_harvested(self, vault):
        """.timshel holds pre-migration COPIES — harvesting them double-counts
        every term and resurrects ones the vault has since dropped."""
        _note(vault, "real.md", "Notatka o [[Impact Chat]].")
        backup = vault / ".timshel" / "resummarize-backup" / "20260707"
        backup.mkdir(parents=True)
        (backup / "old.md").write_text(
            "Stara kopia o [[Nieaktualny Term]].\n", encoding="utf-8"
        )

        terms = VocabularyIndex(vault).build()

        assert "impact chat" in terms
        assert "nieaktualny term" not in terms

    def test_stray_top_level_digest_is_skipped(self, vault):
        _note(vault, "real.md", "Notatka o [[Impact Chat]].")
        (vault / "stray.md").write_text(
            "---\ntype: timshel-digest\n---\n\nŁączy [[26-06-03 - Cos tam]].\n",
            encoding="utf-8",
        )

        terms = VocabularyIndex(vault).build()

        assert "impact chat" in terms
        assert not [t for t in terms if t.startswith("26-")]

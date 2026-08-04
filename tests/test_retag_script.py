"""Tests for scripts/retag_existing_transcripts.py (no API)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "retag_existing_transcripts.py"
)


@pytest.fixture(scope="module")
def retag_module():
    spec = importlib.util.spec_from_file_location("retag_existing_transcripts", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _note(path: Path, tags: str = "transcription, stary-tag") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\ntitle: "n"\ndate: 2026-06-20\ntags: [{tags}]\n---\n\n'
        "## Podsumowanie\n\nTreść podsumowania.\n\n"
        "## Transkrypcja\nTreść transkrypcji nagrania.\n",
        encoding="utf-8",
    )


@pytest.fixture
def retagger(retag_module, tmp_path, monkeypatch):
    """A retagger with the API stubbed out."""
    monkeypatch.setattr(retag_module.config, "ENABLE_LLM_TAGGING", True)
    monkeypatch.setattr(
        retag_module,
        "get_tagger",
        lambda: MagicMock(**{"generate_tags.return_value": ["nowy-tag"]}),
    )

    def _build(**kwargs):
        return retag_module.TranscriptRetagger(root_dir=tmp_path, **kwargs)

    return _build


def test_subfolders_are_never_touched(retagger, tmp_path):
    """Regression: a recursive walk rewrote .timshel/resummarize-backup.

    Those are pre-migration copies of notes. Rewriting them burns API calls on
    files nothing reads and destroys the backup's fidelity.
    """
    _note(tmp_path / "live.md")
    backup = tmp_path / ".timshel" / "resummarize-backup" / "20260707" / "live.md"
    _note(backup)
    digest = tmp_path / "Timshel Digests" / "2026-06-25 Synthesis.md"
    _note(digest)
    original_backup = backup.read_text(encoding="utf-8")
    original_digest = digest.read_text(encoding="utf-8")

    retagger(force=True).run()

    assert "nowy-tag" in (tmp_path / "live.md").read_text(encoding="utf-8")
    assert backup.read_text(encoding="utf-8") == original_backup
    assert digest.read_text(encoding="utf-8") == original_digest


def test_force_regenerates_already_sanitized_tags(retagger, tmp_path):
    """Without --force a prompt change can never reach the corpus."""
    _note(tmp_path / "a.md", tags="transcription, czysty-tag")

    without = retagger()
    without.run()
    assert without.updated == 0 and without.skipped == 1

    with_force = retagger(force=True)
    with_force.run()
    assert with_force.updated == 1
    assert "nowy-tag" in (tmp_path / "a.md").read_text(encoding="utf-8")


def test_only_filters_by_filename(retagger, tmp_path):
    _note(tmp_path / "Koalicja Tech to the Rescue.md")
    _note(tmp_path / "inna notatka.md")

    runner = retagger(force=True, only="Koalicja Tech")
    runner.run()

    assert runner.updated == 1
    assert "nowy-tag" not in (tmp_path / "inna notatka.md").read_text(encoding="utf-8")


def test_tagger_gets_glossary_and_ranked_tags(retagger, tmp_path):
    """Same inputs as the production path (Transcriber._finalize_note)."""
    _note(tmp_path / "a.md")

    runner = retagger(force=True)
    expected_tags = list(runner.existing_tags)  # captured before the run mutates it
    runner.run()

    _, kwargs = runner.tagger.generate_tags.call_args
    assert "known_entities" in kwargs
    assert expected_tags == runner.tag_index.existing_tags_ranked()
    assert kwargs["existing_tags"][: len(expected_tags)] == expected_tags


class TestByteFaithfulRewrite:
    """The rewriter runs over the user's whole vault — it must not deform notes."""

    def test_only_the_tags_line_changes(self, retagger, retag_module, tmp_path):
        """The old rewriter re-assembled the note: it injected a blank line
        after the frontmatter and dropped the trailing newline, on EVERY run."""
        note = tmp_path / "a.md"
        _note(note)
        before = note.read_text(encoding="utf-8")

        retagger(force=True).run()
        after = note.read_text(encoding="utf-8")

        assert after != before
        assert after.endswith("\n") and not after.endswith("\n\n\n")
        expected = retag_module.replace_tags(before, ["transcription", "nowy-tag"])
        assert after == expected
        # Everything outside the tags line is byte-identical.
        diff = [
            (a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b
        ]
        assert len(diff) == 1 and diff[0][0].startswith("tags:")

    def test_rewrite_is_idempotent(self, retagger, tmp_path):
        """Re-running must not accumulate blank lines."""
        _note(tmp_path / "a.md")
        retagger(force=True).run()
        once = (tmp_path / "a.md").read_text(encoding="utf-8")
        retagger(force=True).run()
        twice = (tmp_path / "a.md").read_text(encoding="utf-8")

        assert once == twice

    def test_block_style_tags_are_preserved(self, retagger, retag_module, tmp_path):
        """Obsidian's property editor writes a block list; rewriting it as an
        inline line left the old items dangling — invalid YAML in the vault."""
        note = tmp_path / "block.md"
        note.write_text(
            "---\ntitle: n\ndate: 2026-06-20\ntags:\n  - transcription\n  - stary\n---\n\n"
            "## Podsumowanie\n\nTreść.\n\n## Transkrypcja\nTranskrypcja.\n",
            encoding="utf-8",
        )

        assert retag_module.parse_tags(note.read_text(encoding="utf-8")) == [
            "transcription",
            "stary",
        ]

        retagger(force=True).run()
        after = note.read_text(encoding="utf-8")

        assert "tags:\n  - transcription\n  - nowy-tag\n---" in after
        assert "tags: [" not in after
        assert "  - stary" not in after

    def test_dry_run_writes_nothing(self, retagger, tmp_path):
        _note(tmp_path / "a.md")
        before = (tmp_path / "a.md").read_text(encoding="utf-8")

        runner = retagger(force=True, dry_run=True)
        runner.run()

        assert runner.updated == 1
        assert (tmp_path / "a.md").read_text(encoding="utf-8") == before
        assert not runner.backup_dir.exists()

    def test_original_is_backed_up_before_the_write(self, retagger, tmp_path):
        _note(tmp_path / "a.md")
        before = (tmp_path / "a.md").read_text(encoding="utf-8")

        runner = retagger(force=True)
        runner.run()

        assert (runner.backup_dir / "a.md").read_text(encoding="utf-8") == before

    def test_billing_error_aborts_instead_of_walking_the_vault(
        self, retagger, retag_module, tmp_path
    ):
        """A dead key must stop the run, not log one error per note and
        report 'finished'."""
        for name in ("a.md", "b.md"):
            _note(tmp_path / name)
        runner = retagger(force=True)
        runner.tagger.generate_tags.side_effect = retag_module.APIBillingError(
            "no credits"
        )

        with pytest.raises(retag_module.APIBillingError):
            runner.run()

        assert runner.tagger.generate_tags.call_count == 1


class TestRewriteEdgeCases:
    """Inputs a real vault produces that the rewriter must not choke on."""

    def test_crlf_note_is_parsed_and_rewritten(self, retagger, retag_module, tmp_path):
        """A CRLF file on disk round-trips.

        Note what carries this: ``read_text`` applies universal-newline
        translation, so ``\\r`` never reaches the regexes — the guarantee is at
        the read boundary, not in the patterns. This test pins the end-to-end
        path so a future switch to byte-level reading cannot break it quietly.
        """
        note = tmp_path / "crlf.md"
        note.write_bytes(
            (
                "---\r\ntitle: n\r\ntags: [transcription, stary]\r\n---\r\n\r\n"
                "## Podsumowanie\r\n\r\nTreść.\r\n\r\n## Transkrypcja\r\nTekst.\r\n"
            ).encode("utf-8")
        )

        assert retag_module.parse_tags(note.read_text(encoding="utf-8")) == [
            "transcription",
            "stary",
        ]

        retagger(force=True).run()
        after = note.read_text(encoding="utf-8")
        assert "nowy-tag" in after
        assert "## Podsumowanie" in after and "Tekst." in after
        # Line endings are normalised to LF on read (universal newlines) — the
        # same as before this change; the fix here is that the note is no
        # longer read as untagged and then dropped after the API call.

    def test_note_without_tags_key_gets_one(self, retagger, tmp_path):
        """We already paid for the tags — adding the key beats skipping."""
        note = tmp_path / "notags.md"
        note.write_text(
            "---\ntitle: n\ndate: 2026-06-20\n---\n\n"
            "## Podsumowanie\n\nTreść.\n\n## Transkrypcja\nTekst.\n",
            encoding="utf-8",
        )

        runner = retagger(force=True)
        runner.run()
        after = note.read_text(encoding="utf-8")

        assert runner.updated == 1
        assert "tags: [transcription, nowy-tag]" in after
        assert after.count("---") == 2
        assert "## Podsumowanie" in after

    def test_backup_keeps_the_true_original_on_a_stamp_collision(
        self, retagger, tmp_path
    ):
        """Two runs sharing a stamp folder must not overwrite the original
        with the first run's output."""
        note = tmp_path / "a.md"
        _note(note)
        pristine = note.read_text(encoding="utf-8")

        retagger(force=True, stamp="fixed").run()
        retagger(force=True, stamp="fixed").run()

        backup = tmp_path / ".timshel" / "retag-backup" / "fixed" / "a.md"
        assert backup.read_text(encoding="utf-8") == pristine

    def test_unrewritable_tags_key_is_skipped_not_duplicated(
        self, retagger, retag_module, tmp_path
    ):
        """A `tags:` key we can't rewrite must leave the note alone.

        Appending a second `tags:` line would make a DUPLICATE mapping key:
        invalid YAML, with the user's own value silently orphaned. A skipped
        note is recoverable; a corrupted one is not.
        """
        variants = {
            "bare.md": "tags:",
            "scalar.md": "tags: notatka",
            "null.md": "tags: null",
            "empty.md": 'tags: ""',
        }
        for name, tags_line in variants.items():
            (tmp_path / name).write_text(
                f"---\ntitle: n\ndate: 2026-06-20\n{tags_line}\n---\n\n"
                "## Podsumowanie\n\nTreść.\n\n## Transkrypcja\nTekst.\n",
                encoding="utf-8",
            )
        before = {n: (tmp_path / n).read_text(encoding="utf-8") for n in variants}

        retagger(force=True).run()

        for name, original in before.items():
            after = (tmp_path / name).read_text(encoding="utf-8")
            assert after == original, name
            assert after.count("tags:") == 1, name

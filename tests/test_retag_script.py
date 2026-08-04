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
    """Same inputs as the production path (transcriber._summarize_and_render)."""
    _note(tmp_path / "a.md")

    runner = retagger(force=True)
    expected_tags = list(runner.existing_tags)  # captured before the run mutates it
    runner.run()

    _, kwargs = runner.tagger.generate_tags.call_args
    assert "known_entities" in kwargs
    assert expected_tags == runner.tag_index.existing_tags_ranked()
    assert kwargs["existing_tags"][: len(expected_tags)] == expected_tags

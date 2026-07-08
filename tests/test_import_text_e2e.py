"""Broad end-to-end coverage for loading real text files into the vault.

Exercises ``Transcriber.import_text_file`` on real .txt / .md / .vtt files
through the actual pipeline (ingest parse → _finalize_note → render → index),
mocking nothing but the absent LLM (no API key → deterministic fallback
summary). This is the tester-build "Import transcripts…" seeding path, which
had zero end-to-end coverage. Fast: no whisper, no network.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.transcriber import Transcriber


@pytest.fixture
def transcriber(tmp_path):
    """Transcriber on a throwaway vault, AI off (offline fallback summary)."""
    from src.config.config import Config

    cfg = Config()
    cfg.TRANSCRIBE_DIR = tmp_path / "vault"
    cfg.TRANSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOCAL_RECORDINGS_DIR = tmp_path / "staging"
    cfg.ENABLE_RECALL_INDEX = False  # keep the post-note hook cheap/deterministic
    with patch("src.transcriber.logger"):
        t = Transcriber(config=cfg)
    t.summarizer = None  # force the offline fallback path
    t.tagger = None
    return t


def _vault_notes(transcriber) -> list[Path]:
    return sorted(Path(transcriber.config.TRANSCRIBE_DIR).glob("*.md"))


# --------------------------------------------------------------------------- #
# Per-format loading.
# --------------------------------------------------------------------------- #


def test_import_txt_creates_note(transcriber, tmp_path):
    src = tmp_path / "meeting notes.txt"
    src.write_text(
        "Rozmowa o strategii produktu. Ustaliliśmy trzy priorytety na Q3.",
        encoding="utf-8",
    )

    assert transcriber.import_text_file(src) is True

    notes = _vault_notes(transcriber)
    assert len(notes) == 1
    body = notes[0].read_text(encoding="utf-8")
    assert "source_type: import" in body
    assert "origin: txt" in body  # _parse_plain records the file suffix
    assert "trzy priorytety" in body  # transcript text preserved
    assert "## Transkrypcja" in body


def test_import_md_creates_note(transcriber, tmp_path):
    src = tmp_path / "note.md"
    src.write_text("# Tytuł\n\nTreść notatki o projekcie Timshel.", encoding="utf-8")

    assert transcriber.import_text_file(src) is True
    body = _vault_notes(transcriber)[0].read_text(encoding="utf-8")
    assert "source_type: import" in body
    assert "projekcie Timshel" in body


def test_import_vtt_strips_scaffolding(transcriber, tmp_path):
    src = tmp_path / "call.vtt"
    src.write_text(
        "WEBVTT\n\n"
        "NOTE this is a note block that must be dropped\n\n"
        "1\n"
        "00:00:00.000 --> 00:00:03.500\n"
        "<v Radek>Zaczynamy spotkanie o wdrożeniu.\n\n"
        "2\n"
        "00:00:03.500 --> 00:00:07.000\n"
        "Druga kwestia to budżet na testy.\n",
        encoding="utf-8",
    )

    assert transcriber.import_text_file(src) is True
    body = _vault_notes(transcriber)[0].read_text(encoding="utf-8")
    # Spoken text kept…
    assert "Zaczynamy spotkanie o wdrożeniu" in body
    assert "Druga kwestia to budżet" in body
    # …scaffolding stripped.
    assert "WEBVTT" not in body
    assert "00:00:00.000" not in body
    assert "this is a note block" not in body
    assert "<v Radek>" not in body


# --------------------------------------------------------------------------- #
# Dedup, batching, rejects.
# --------------------------------------------------------------------------- #


def test_reimport_is_deduped_by_fingerprint(transcriber, tmp_path):
    src = tmp_path / "dup.txt"
    src.write_text("Ta sama treść zaimportowana dwa razy pod rząd.", encoding="utf-8")

    assert transcriber.import_text_file(src) is True
    assert transcriber.import_text_file(src) is True  # duplicate reported ok
    # …but only ONE note exists.
    assert len(_vault_notes(transcriber)) == 1


def test_batch_of_mixed_formats_all_land(transcriber, tmp_path):
    (tmp_path / "a.txt").write_text("Pierwsza notatka o rekrutacji.", encoding="utf-8")
    (tmp_path / "b.md").write_text("Druga notatka o pricingu.", encoding="utf-8")
    (tmp_path / "c.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nTrzecia notatka o retencji.\n",
        encoding="utf-8",
    )

    ok = sum(
        transcriber.import_text_file(tmp_path / name)
        for name in ("a.txt", "b.md", "c.vtt")
    )
    assert ok == 3
    assert len(_vault_notes(transcriber)) == 3


def test_unsupported_extension_rejected(transcriber, tmp_path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 not really parseable text")
    with pytest.raises(ValueError):
        transcriber.import_text_file(src)
    assert _vault_notes(transcriber) == []


def test_empty_file_rejected(transcriber, tmp_path):
    src = tmp_path / "empty.txt"
    src.write_text("   \n\n  ", encoding="utf-8")
    with pytest.raises(ValueError):
        transcriber.import_text_file(src)
    assert _vault_notes(transcriber) == []


def test_imported_note_is_indexed_for_dedup(transcriber, tmp_path):
    src = tmp_path / "indexed.txt"
    src.write_text("Notatka która musi trafić do vault_index.", encoding="utf-8")

    assert transcriber.import_text_file(src) is True
    # The fingerprint must now resolve in the index (else the pending loop
    # would re-import the same file forever — the regression _index_completed_
    # transcription fixed for the TXT path).
    from src.ingest import parse, text_fingerprint

    doc = parse(src)
    fp = text_fingerprint(doc.text, doc.source_name)
    assert transcriber.vault_index.lookup(fp) is not None

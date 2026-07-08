"""End-to-end tests for Transcriber.import_text_file (text → note)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.transcriber import RetranscribeLockBusyError, Transcriber


@pytest.fixture
def transcriber(tmp_path, monkeypatch):
    from src.config.config import Config
    from src import config as config_module

    cfg = Config()
    cfg.TRANSCRIBE_DIR = tmp_path / "vault"
    cfg.TRANSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOCAL_RECORDINGS_DIR = tmp_path / "staging"
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", cfg.TRANSCRIBE_DIR)
    with patch("src.transcriber.logger"):
        return Transcriber(config=cfg)


def _notes(vault: Path):
    return [p for p in vault.glob("*.md")]


def test_import_txt_creates_note_with_provenance(transcriber, tmp_path):
    src = tmp_path / "moja notatka.txt"
    src.write_text("myślę że prefabrykaty to dobry kierunek", encoding="utf-8")

    assert transcriber.import_text_file(src) is True

    notes = _notes(transcriber.config.TRANSCRIBE_DIR)
    assert len(notes) == 1
    body = notes[0].read_text(encoding="utf-8")
    assert "source_type: import" in body
    assert "origin: txt" in body
    assert "myślę że prefabrykaty to dobry kierunek" in body


def test_import_registers_in_vault_index(transcriber, tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("treść do zaindeksowania", encoding="utf-8")

    from src.ingest import text_fingerprint

    fp = text_fingerprint("treść do zaindeksowania", "note.txt")

    transcriber.import_text_file(src)

    assert transcriber.vault_index.lookup(fp) is not None


def test_reimport_same_file_dedups(transcriber, tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("ta sama treść", encoding="utf-8")

    assert transcriber.import_text_file(src) is True
    assert transcriber.import_text_file(src) is True  # dedup, still success

    assert len(_notes(transcriber.config.TRANSCRIBE_DIR)) == 1


def test_import_vtt_end_to_end(transcriber, tmp_path):
    src = tmp_path / "call.vtt"
    src.write_text(
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nDecyzja o oknach zapadła.\n",
        encoding="utf-8",
    )

    assert transcriber.import_text_file(src) is True
    body = _notes(transcriber.config.TRANSCRIBE_DIR)[0].read_text(encoding="utf-8")
    assert "origin: vtt" in body
    assert "Decyzja o oknach zapadła." in body


def test_import_busy_when_workflow_lock_held(transcriber, tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("cokolwiek", encoding="utf-8")

    assert transcriber._workflow_lock.acquire(blocking=False)
    try:
        with pytest.raises(RetranscribeLockBusyError):
            transcriber.import_text_file(src)
    finally:
        transcriber._workflow_lock.release()

    assert _notes(transcriber.config.TRANSCRIBE_DIR) == []  # nothing written


def test_import_unsupported_type_raises(transcriber, tmp_path):
    bad = tmp_path / "scan.pdf"
    bad.write_bytes(b"%PDF-1.4")
    with pytest.raises(ValueError):
        transcriber.import_text_file(bad)
    # lock released afterwards
    assert transcriber._workflow_lock.acquire(blocking=False)
    transcriber._workflow_lock.release()

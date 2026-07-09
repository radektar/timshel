"""E2E: manual import runs the real pipeline end-to-end.

Generates a real audio file, imports it via ``Transcriber.import_audio_file``
(stage → real whisper → Markdown note), and asserts a valid note lands in the
vault. Excluded from ``make test`` (``-m "not e2e"``); run via ``make test-e2e``
or ``pytest tests/e2e/test_manual_import_e2e.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.fixtures import whisper_runtime as wr
from tests.fixtures.audio_factory import AudioFactory, say_available

requires_runtime = pytest.mark.skipif(
    wr.find_whisper_install() is None
    or wr.find_ffmpeg() is None
    or not say_available(),
    reason="requires a real whisper install, ffmpeg, and macOS `say`",
)


@pytest.fixture(scope="module")
def factory() -> AudioFactory:
    return AudioFactory()


@pytest.mark.e2e
@pytest.mark.slow
@requires_runtime
@pytest.mark.parametrize("ext", [".mp3", ".flac", ".wav", ".m4a", ".ogg"])
def test_manual_import_full_pipeline(factory, ext, tmp_path):
    """Importing a real audio file stages it and produces a Markdown note."""
    from src.transcriber import Transcriber

    # A real generated sample, living outside the staging dir.
    source = factory.make(lang="en_US", ext=ext)

    cfg = wr.make_e2e_config(tmp_path / "vault", language="en", model="small")
    cfg.LOCAL_RECORDINGS_DIR = tmp_path / "staging"
    with patch("src.transcriber.logger"):
        transcriber = Transcriber(config=cfg)
    # Offline fallback summary/tags — keep this an L2 (whisper-only) run.
    transcriber.summarizer = None
    transcriber.tagger = None

    assert transcriber.import_audio_file(source) is True

    # The file was staged (copied, original untouched).
    staged = list((tmp_path / "staging").glob(f"*{ext}"))
    assert len(staged) == 1
    assert source.exists()

    # A single Markdown note was produced from the staged copy.
    notes = list(Path(cfg.TRANSCRIBE_DIR).glob("*.md"))
    assert len(notes) == 1, f"expected one note, got {notes}"
    body = notes[0].read_text(encoding="utf-8").lower()
    assert "recording" in body, "transcript text missing from the note body"

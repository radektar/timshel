"""import_text_file reports duplicate vs freshly-written via the status dict.

Regression: a re-import is a no-op (fingerprint dedup) but the UI reported
"Imported N", so the user looked for notes that were never re-written.
"""

from pathlib import Path

import pytest

from src.transcriber import Transcriber


@pytest.fixture
def transcriber(tmp_path, monkeypatch):
    from src.config import config as cfg

    monkeypatch.setattr(type(cfg), "TRANSCRIBE_DIR", tmp_path, raising=False)
    t = Transcriber()
    return t


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_first_import_marks_not_duplicate(transcriber, tmp_path):
    src = _write(tmp_path, "note.md", "# Spotkanie\n\nUstalenia projektu Helios.")
    st: dict = {}
    assert transcriber.import_text_file(src, status=st) is True
    assert st.get("duplicate") is False


def test_reimport_marks_duplicate(transcriber, tmp_path):
    src = _write(tmp_path, "note.md", "# Spotkanie\n\nUstalenia projektu Helios.")
    transcriber.import_text_file(src)  # seed

    st: dict = {}
    assert transcriber.import_text_file(src, status=st) is True
    assert st.get("duplicate") is True


def test_status_is_optional(transcriber, tmp_path):
    # Back-compat: callers that don't pass status still work.
    src = _write(tmp_path, "note.md", "# X\n\ncontent")
    assert transcriber.import_text_file(src) is True

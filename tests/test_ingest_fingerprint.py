"""Tests for the imported-text content fingerprint."""

from src.ingest.fingerprint import text_fingerprint


def test_fingerprint_is_deterministic():
    a = text_fingerprint("hello world", "note.txt")
    b = text_fingerprint("hello world", "note.txt")
    assert a == b
    assert a.startswith("sha256:")


def test_fingerprint_differs_on_content():
    a = text_fingerprint("hello world", "note.txt")
    b = text_fingerprint("hello there", "note.txt")
    assert a != b


def test_fingerprint_differs_on_source_name():
    a = text_fingerprint("same text", "a.txt")
    b = text_fingerprint("same text", "b.txt")
    assert a != b  # two files with identical text stay distinct notes

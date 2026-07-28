"""Tests for fingerprint module."""

from pathlib import Path

from src.fingerprint import compute_fingerprint


def test_compute_fingerprint_is_stable(tmp_path: Path) -> None:
    """Fingerprint is deterministic for same file."""
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"a" * 2048)
    first = compute_fingerprint(audio)
    second = compute_fingerprint(audio)
    assert first == second
    assert first.startswith("sha256:")


def test_compute_fingerprint_differs_for_different_files(tmp_path: Path) -> None:
    """Different file content yields different fingerprint."""
    audio1 = tmp_path / "one.mp3"
    audio2 = tmp_path / "two.mp3"
    audio1.write_bytes(b"a" * 2048)
    audio2.write_bytes(b"b" * 2048)
    assert compute_fingerprint(audio1) != compute_fingerprint(audio2)

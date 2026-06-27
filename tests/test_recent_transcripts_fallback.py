"""The Insights rail must reflect on-disk transcripts when the vault index is
empty (fresh install, or transcripts written by an older build)."""

from __future__ import annotations

import os

from src.menu_app import MalincheMenuApp


def _app():
    return MalincheMenuApp.__new__(MalincheMenuApp)


def test_disk_fallback_lists_newest_first_excluding_digests(tmp_path, monkeypatch):
    monkeypatch.setattr("src.menu_app.config.TRANSCRIBE_DIR", tmp_path)
    monkeypatch.setattr("src.menu_app.config.DIGEST_DIR_NAME", "Malinche Digests")

    old = tmp_path / "Old.md"
    new = tmp_path / "sub" / "New.md"
    new.parent.mkdir(parents=True)
    old.write_text("x", encoding="utf-8")
    new.write_text("y", encoding="utf-8")
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))

    # noise that must be excluded
    digest = tmp_path / "Malinche Digests" / "Digest.md"
    digest.parent.mkdir(parents=True)
    digest.write_text("d", encoding="utf-8")
    sidecar = tmp_path / ".malinche" / "index.md"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("i", encoding="utf-8")

    rows = _app()._recent_transcripts_from_disk()
    labels = [r["label"] for r in rows]
    assert labels == ["New", "Old"]  # newest first, digests/sidecar excluded


def test_index_empty_triggers_disk_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("src.menu_app.config.TRANSCRIBE_DIR", tmp_path)
    monkeypatch.setattr("src.menu_app.config.DIGEST_DIR_NAME", "Malinche Digests")
    (tmp_path / "On Disk.md").write_text("x", encoding="utf-8")

    class _EmptyIndex:
        def recent_entries(self, limit=5):
            return []

    app = _app()
    app.transcriber = type("T", (), {"vault_index": _EmptyIndex()})()

    rows = app._recent_transcripts_for_insights()
    assert [r["label"] for r in rows] == ["On Disk"]

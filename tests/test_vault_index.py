"""Tests for vault index module."""

from pathlib import Path

from src.vault_index import IndexEntry, VaultIndex


def test_vault_index_add_and_lookup(tmp_path: Path) -> None:
    """Can add and read a fingerprint entry."""
    idx = VaultIndex(tmp_path)
    idx.load()
    fingerprint = "sha256:test"
    idx.add(
        fingerprint,
        IndexEntry(
            fingerprint=fingerprint,
            source_filename="DS0001.MP3",
            source_volume="LS-P1",
            markdown_path="note.md",
            versions=[{"version": 1, "transcribed_at": "2026-01-01T00:00:00"}],
        ),
    )
    loaded = idx.lookup(fingerprint)
    assert loaded is not None
    assert loaded.markdown_path == "note.md"


def test_vault_index_add_version(tmp_path: Path) -> None:
    """Can append additional versions."""
    idx = VaultIndex(tmp_path)
    idx.load()
    fingerprint = "sha256:test"
    idx.add(
        fingerprint,
        IndexEntry(
            fingerprint=fingerprint,
            source_filename="DS0001.MP3",
            source_volume="LS-P1",
            markdown_path="note.md",
            versions=[],
        ),
    )
    idx.add_version(
        fingerprint,
        {
            "version": 2,
            "transcribed_at": "2026-01-01T01:00:00",
            "markdown_path": "note.v2.md",
        },
    )
    loaded = idx.lookup(fingerprint)
    assert loaded is not None
    assert loaded.markdown_path == "note.v2.md"
    assert len(loaded.versions) == 1


def test_lookup_by_filename_size_matches_exact(tmp_path: Path) -> None:
    """Cheap pre-filter returns entry on (filename, size) match."""
    idx = VaultIndex(tmp_path)
    idx.load()
    idx.add(
        "sha256:a",
        IndexEntry(
            fingerprint="sha256:a",
            source_filename="DS0001.MP3",
            source_volume="LS-P1",
            markdown_path="note.md",
            source_size=12345,
        ),
    )
    assert idx.lookup_by_filename_size("DS0001.MP3", 12345) is not None
    assert idx.lookup_by_filename_size("DS0001.MP3", 999) is None
    assert idx.lookup_by_filename_size("OTHER.MP3", 12345) is None


def test_lookup_by_filename_size_ignores_premigration_entries(tmp_path: Path) -> None:
    """Entries with source_size == 0 are pre-migration and never match."""
    idx = VaultIndex(tmp_path)
    idx.load()
    idx.add(
        "sha256:b",
        IndexEntry(
            fingerprint="sha256:b",
            source_filename="DS0002.MP3",
            source_volume="LS-P1",
            markdown_path="note2.md",
            source_size=0,
        ),
    )
    assert idx.lookup_by_filename_size("DS0002.MP3", 50000) is None


def test_add_preserves_existing_size_when_new_entry_has_zero(tmp_path: Path) -> None:
    """Lazy migration: once a real size is stored, later add() calls with size=0 keep it."""
    idx = VaultIndex(tmp_path)
    idx.load()
    fp = "sha256:c"
    idx.add(
        fp,
        IndexEntry(
            fingerprint=fp,
            source_filename="DS0003.MP3",
            source_volume="LS-P1",
            markdown_path="note3.md",
            source_size=98765,
        ),
    )
    # Re-add without size (e.g. reconciliation path)
    idx.add(
        fp,
        IndexEntry(
            fingerprint=fp,
            source_filename="DS0003.MP3",
            source_volume="LS-P1",
            markdown_path="note3.md",
            source_size=0,
        ),
    )
    assert idx.lookup_by_filename_size("DS0003.MP3", 98765) is not None

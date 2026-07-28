"""Unit tests for the shared importable-file discovery (src/ingest/discovery)."""

import pytest

from src.config import config
from src.ingest import is_vault_path, list_importable


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / config.DIGEST_DIR_NAME).mkdir(parents=True)
    (v / config.SIDECAR_DIR_NAME).mkdir(parents=True)
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", v)
    return v


def test_vault_itself_is_refused(vault, tmp_path):
    assert is_vault_path(vault) is True
    assert is_vault_path(vault / config.DIGEST_DIR_NAME) is True
    assert is_vault_path(tmp_path / "elsewhere") is False


def test_digest_and_hidden_dirs_excluded(vault, tmp_path):
    src = tmp_path / "notes"
    (src / "sub").mkdir(parents=True)
    (src / ".obsidian").mkdir()
    (src / config.DIGEST_DIR_NAME).mkdir()
    (src / "a.md").write_text("x", encoding="utf-8")
    (src / "sub" / "b.txt").write_text("x", encoding="utf-8")
    (src / ".obsidian" / "workspace.md").write_text("x", encoding="utf-8")
    (src / config.DIGEST_DIR_NAME / "2026-07-01 Synthesis.md").write_text(
        "x", encoding="utf-8"
    )
    (src / "skip.pdf").write_text("x", encoding="utf-8")

    found = {p.name for p in list_importable(src)}
    assert found == {"a.md", "b.txt"}  # no app state, no digests, no pdf


def test_count_and_import_agree(vault, tmp_path):
    """The wizard counts with the same call the import walks — the number the
    user consents to is the number that gets paid for."""
    from src.setup.wizard import SetupWizard

    src = tmp_path / "notes"
    src.mkdir()
    for i in range(5):
        (src / f"n{i}.md").write_text("x", encoding="utf-8")
    (src / "ignored.pdf").write_text("x", encoding="utf-8")

    assert SetupWizard._count_importable(src) == len(list_importable(src)) == 5


def test_traversal_is_bounded(vault, tmp_path, monkeypatch):
    import src.ingest.discovery as discovery

    monkeypatch.setattr(discovery, "MAX_SCANNED_ENTRIES", 3)
    src = tmp_path / "notes"
    src.mkdir()
    for i in range(10):
        (src / f"n{i}.md").write_text("x", encoding="utf-8")
    assert len(list_importable(src)) <= 3  # cap honoured, no hang on ~

"""Unit tests for the shared importable-file discovery (src/ingest/discovery)."""

from pathlib import Path

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


def test_parent_of_vault_is_importable(vault, tmp_path, monkeypatch):
    """The flagship layout: transcripts live INSIDE an Obsidian vault, so
    importing the Obsidian root must work — only the vault subtree is
    dropped, and files sitting directly in the parent are kept."""
    obsidian = tmp_path / "Obsidian"
    transcripts = obsidian / "11-Transcripts"
    (transcripts / "sub").mkdir(parents=True)
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", transcripts)
    (obsidian / "root-note.md").write_text("x", encoding="utf-8")
    (obsidian / "Daily").mkdir()
    (obsidian / "Daily" / "d.md").write_text("x", encoding="utf-8")
    (transcripts / "own.md").write_text("x", encoding="utf-8")
    (transcripts / "sub" / "deep.md").write_text("x", encoding="utf-8")

    assert is_vault_path(obsidian) is False  # parent NOT refused
    assert is_vault_path(transcripts) is True
    assert is_vault_path(transcripts / "sub") is True
    found = {p.name for p in list_importable(obsidian)}
    assert found == {"root-note.md", "d.md"}  # vault subtree excluded


def test_bound_stops_the_walk_not_just_the_result(vault, tmp_path, monkeypatch):
    """The cap must bound the WORK — a sorted() over the whole tree would
    finish the walk before any cap could apply (the wizard counts on the UI
    path, so picking ~ must not hang it)."""
    import src.ingest.discovery as discovery

    src = tmp_path / "notes"
    src.mkdir()
    for i in range(20):
        (src / f"n{i:02d}.md").write_text("x", encoding="utf-8")

    visited = []
    real_rglob = Path.rglob

    def _counting_rglob(self, pattern):
        for p in real_rglob(self, pattern):
            visited.append(p)
            yield p

    monkeypatch.setattr(Path, "rglob", _counting_rglob)
    monkeypatch.setattr(discovery, "MAX_SCANNED_ENTRIES", 5)
    list_importable(src)
    assert len(visited) <= 6  # walk stopped, tree never fully materialised


def test_importing_ingest_has_no_filesystem_side_effects(tmp_path):
    """src/ingest must stay dependency-light: importing it may not create the
    vault/app dirs or freeze the Config singleton (a module-scope
    `from src.logger import logger` silently did exactly that)."""
    import subprocess
    import sys

    home = tmp_path / "home"
    home.mkdir()
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import src.ingest, sys; print('src.logger' in sys.modules)",
        ],
        cwd=repo,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"  # src.logger not pulled in
    assert list(home.rglob("*")) == []  # nothing written under HOME
